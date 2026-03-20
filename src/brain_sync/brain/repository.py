"""Portable brain persistence boundary.

`BrainRepository` is the runtime control layer for durable brain artifacts
under the brain root. It owns path-safe persistence and managed-layout policy
for manifests, managed markdown, attachments, summaries, journals, and
per-area insight sidecars.

It does not own runtime DB / daemon state and it does not own higher-level
workflow orchestration such as sync loops, reconcile policy, or regen
planning. Those callers orchestrate behavior above this boundary and call into
this module for portable-brain reads and writes.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from brain_sync.brain import sidecar as sidecar_store
from brain_sync.brain.fileops import (
    atomic_write_bytes,
    canonical_prefix,
    clean_insights_tree,
    iterdir_paths,
    path_exists,
    path_is_dir,
    path_is_file,
    read_bytes,
    read_text,
    rediscover_local_path,
    rglob_paths,
    win_long_path,
    write_bytes_if_changed,
    write_if_changed,
)
from brain_sync.brain.layout import (
    ATTACHMENTS_DIRNAME,
    BRAIN_MANIFEST_VERSION,
    JOURNAL_DIRNAME,
    MANAGED_DIRNAME,
    area_insight_state_path,
    area_insights_dir,
    area_journal_dir,
    area_summary_path,
    brain_manifest_path,
    knowledge_root,
)
from brain_sync.brain.managed_markdown import extract_source_id, prepend_managed_header
from brain_sync.brain.manifest import (
    SourceManifest,
    clear_manifest_missing,
    delete_source_manifest,
    mark_manifest_missing,
    read_all_source_manifests,
    read_source_manifest,
    update_manifest_materialization,
    write_source_manifest,
)
from brain_sync.brain.tree import normalize_path
from brain_sync.util.text import slugify

log = logging.getLogger(__name__)

_JOURNAL_HEADING_RE = re.compile(r"^## \d{2}:\d{2}\s*$", re.MULTILINE)


def source_dir_id(canonical_id: str) -> str:
    """Return the durable per-source directory name used under attachments/."""
    return canonical_prefix(canonical_id).rstrip("-")


def attachment_local_path(canonical_id: str, attachment_id: str, title: str | None) -> str:
    """Return the managed relative path for one attachment."""
    return attachment_local_path_for_source_dir(source_dir_id(canonical_id), attachment_id, title)


def attachment_local_path_for_source_dir(source_dir: str, attachment_id: str, title: str | None) -> str:
    """Return the managed relative path for one attachment by source-dir id."""
    if title:
        clean = title.split("?")[0]
        stem = Path(clean).stem
        ext = Path(clean).suffix
        filename = f"a{attachment_id}-{_slug(stem)}{ext}"
    else:
        filename = f"a{attachment_id}"
    return f"{MANAGED_DIRNAME}/{ATTACHMENTS_DIRNAME}/{source_dir}/{filename}"


def ensure_attachment_dir(target_dir: Path, canonical_id: str) -> Path:
    """Create and return the managed attachment dir for a source in an area."""
    return ensure_attachment_dir_for_source_dir(target_dir, source_dir_id(canonical_id))


def ensure_attachment_dir_for_source_dir(target_dir: Path, source_dir: str) -> Path:
    """Create and return the managed attachment dir for one source-dir id."""
    att_dir = target_dir / MANAGED_DIRNAME / ATTACHMENTS_DIRNAME / source_dir
    att_dir.mkdir(parents=True, exist_ok=True)
    return att_dir


def source_attachment_dir(target_dir: Path, canonical_id: str) -> Path:
    """Return the managed attachment dir path for a source in an area."""
    return target_dir / MANAGED_DIRNAME / ATTACHMENTS_DIRNAME / source_dir_id(canonical_id)


def remove_source_attachment_dir(target_dir: Path, canonical_id: str) -> bool:
    """Delete one source's managed attachment dir if present."""
    att_dir = source_attachment_dir(target_dir, canonical_id)
    if not path_is_dir(att_dir):
        return False
    shutil.rmtree(str(win_long_path(att_dir)))
    return True


@dataclass(frozen=True)
class SourceResolution:
    canonical_id: str
    path: Path | None
    resolution: Literal["direct", "identity", "prefix", "missing", "unmaterialized"]


@dataclass(frozen=True)
class ManifestMove:
    canonical_id: str
    old_target_path: str
    new_target_path: str
    knowledge_path: str


@dataclass(frozen=True)
class MaterializationResult:
    canonical_id: str
    target_path: str
    materialized_path: str
    changed: bool
    duplicate_files_removed: tuple[str, ...] = ()


class BrainRepositoryInvariantError(RuntimeError):
    """Raised when a strict repository mutation receives invalid input."""


class PortableBrainLockError(RuntimeError):
    """Raised when a managed portable-brain write is blocked by filesystem locking."""

    def __init__(self, operation: str, target: Path, original_error: PermissionError) -> None:
        self.operation = operation
        self.target = target
        self.original_error = original_error
        super().__init__(f"{operation} blocked by filesystem lock at '{target}': {original_error}")


def _raise_if_lock_contention(operation: str, target: Path, exc: PermissionError) -> None:
    if getattr(exc, "winerror", None) == 5:
        raise PortableBrainLockError(operation, target, exc) from exc
    raise exc


class BrainRepository:
    """Portable-brain persistence mediator rooted at one brain."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._knowledge_root = knowledge_root(root)

    @property
    def knowledge_root(self) -> Path:
        return self._knowledge_root

    def ensure_knowledge_dir(self, knowledge_path: str) -> Path:
        """Create and return one knowledge area directory."""
        normalized = self._normalize_relative_knowledge_path(knowledge_path, operation="ensure_knowledge_dir")
        target_dir = self._knowledge_root / Path(normalized) if normalized else self._knowledge_root
        target_dir.mkdir(parents=True, exist_ok=True)
        return target_dir

    def write_brain_manifest(self) -> Path:
        """Write the portable brain manifest file under .brain-sync/."""
        manifest_path = brain_manifest_path(self.root)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(
            manifest_path,
            (json.dumps({"version": BRAIN_MANIFEST_VERSION}, indent=2) + "\n").encode("utf-8"),
        )
        return manifest_path

    def save_source_manifest(self, manifest: SourceManifest) -> None:
        """Persist one source manifest."""
        write_source_manifest(self.root, manifest)

    def add_local_file(self, source: Path, target_path: str, *, copy: bool = True) -> Path:
        """Copy or move a local file into one knowledge area with collision handling."""
        if not source.exists() or not source.is_file():
            raise BrainRepositoryInvariantError(f"add_local_file: source '{source}' does not exist or is not a file")
        dest_dir = self.ensure_knowledge_dir(target_path)
        dest = dest_dir / source.name
        if path_exists(dest):
            stem = dest.stem
            suffix = dest.suffix
            resolved = None
            for index in range(2, 11):
                candidate = dest_dir / f"{stem}-{index}{suffix}"
                if not path_exists(candidate):
                    resolved = candidate
                    break
            if resolved is None:
                raise BrainRepositoryInvariantError(
                    f"add_local_file: file exists and all numeric suffixes are taken for '{source.name}'"
                )
            dest = resolved
        if copy:
            shutil.copy2(str(source), str(dest))
        else:
            shutil.move(str(source), str(dest))
        return dest

    def delete_local_file(self, knowledge_path: str) -> bool:
        """Delete one local non-synced file from the knowledge tree."""
        normalized = self._normalize_relative_knowledge_path(knowledge_path, operation="delete_local_file")
        target = self._knowledge_root / Path(normalized)
        self._require_under_knowledge_root(target, operation="delete_local_file")
        if not path_exists(target):
            return False
        if not path_is_file(target):
            raise BrainRepositoryInvariantError(f"delete_local_file: '{normalized}' is not a file")
        target.unlink()
        return True

    def delete_source_registration(self, canonical_id: str) -> bool:
        """Delete one source manifest if it exists."""
        existed = read_source_manifest(self.root, canonical_id) is not None
        if existed:
            delete_source_manifest(self.root, canonical_id)
        return existed

    def update_source_sync_settings(
        self,
        canonical_id: str,
        *,
        sync_attachments: bool | None = None,
    ) -> bool:
        """Update durable manifest-backed source settings."""
        manifest = read_source_manifest(self.root, canonical_id)
        if manifest is None:
            return False
        if sync_attachments is not None:
            manifest.sync_attachments = sync_attachments
        write_source_manifest(self.root, manifest)
        return True

    def mark_source_missing(self, canonical_id: str, utc_now: str | None = None) -> bool:
        """Mark a manifest missing if it exists."""
        del utc_now
        manifest = read_source_manifest(self.root, canonical_id)
        if manifest is None:
            return False
        mark_manifest_missing(self.root, canonical_id)
        return True

    def clear_source_missing(self, canonical_id: str) -> bool:
        """Clear missing status and mark the source stale if the manifest exists."""
        manifest = read_source_manifest(self.root, canonical_id)
        if manifest is None:
            return False
        clear_manifest_missing(self.root, canonical_id)
        return True

    def mark_source_stale(self, canonical_id: str, *, knowledge_path: str | None = None) -> bool:
        """Persist a portable stale transition for a source that must rematerialize."""
        manifest = read_source_manifest(self.root, canonical_id)
        if manifest is None:
            return False
        if knowledge_path is not None:
            manifest.knowledge_path = self._normalize_relative_knowledge_path(
                knowledge_path,
                operation="mark_source_stale",
            )
        if manifest.knowledge_state not in {"awaiting", "missing"}:
            manifest.knowledge_state = "stale"
        write_source_manifest(self.root, manifest)
        return True

    def set_source_area_path(
        self,
        canonical_id: str,
        target_path: str,
    ) -> bool:
        """Update the anchored knowledge_path to a different area."""
        manifest = read_source_manifest(self.root, canonical_id)
        if manifest is None:
            return False
        filename = Path(manifest.knowledge_path).name or f"{source_dir_id(canonical_id)}.md"
        normalized_area = self._normalize_relative_knowledge_path(target_path, operation="set_source_area_path")
        manifest.knowledge_path = normalize_path(Path(normalized_area) / filename) if normalized_area else filename
        if manifest.knowledge_state not in {"awaiting", "missing"}:
            manifest.knowledge_state = "stale"
        write_source_manifest(self.root, manifest)
        return True

    def source_attachment_dir(self, target_dir: Path, canonical_id: str) -> Path:
        """Return the managed attachment dir path for a source in an area."""
        return source_attachment_dir(target_dir, canonical_id)

    def resolve_source_file(
        self,
        manifest: SourceManifest,
        *,
        identity_index: dict[str, Path] | None = None,
    ) -> SourceResolution:
        """Resolve a materialized source file using durable source semantics."""
        canonical_id = manifest.canonical_id

        if manifest.knowledge_path:
            direct = self._knowledge_root / manifest.knowledge_path
            if path_is_file(direct):
                return SourceResolution(canonical_id=canonical_id, path=direct, resolution="direct")

            indexed = identity_index.get(canonical_id) if identity_index is not None else None
            if indexed is not None:
                indexed_path = self._knowledge_root / indexed
                if path_is_file(indexed_path):
                    return SourceResolution(canonical_id=canonical_id, path=indexed_path, resolution="identity")

            scanned = self._find_file_by_identity(canonical_id)
            if scanned is not None:
                return SourceResolution(canonical_id=canonical_id, path=scanned, resolution="identity")

        rediscovered = rediscover_local_path(self._knowledge_root, canonical_id)
        if rediscovered is not None:
            return SourceResolution(canonical_id=canonical_id, path=rediscovered, resolution="prefix")

        if manifest.knowledge_state == "awaiting":
            return SourceResolution(canonical_id=canonical_id, path=None, resolution="unmaterialized")

        return SourceResolution(canonical_id=canonical_id, path=None, resolution="missing")

    def sync_manifest_to_found_path(self, canonical_id: str, found_path: Path) -> tuple[str, str]:
        """Update a source manifest to match a resolved filesystem path."""
        operation = "sync_manifest_to_found_path"
        manifest = read_source_manifest(self.root, canonical_id)
        if manifest is None:
            raise BrainRepositoryInvariantError(f"{operation}: manifest not found for {canonical_id}")

        found_file = self._require_file_under_knowledge_root(found_path, operation=operation)
        knowledge_path = normalize_path(found_file.relative_to(self._knowledge_root))
        target_path = normalize_path(found_file.parent.relative_to(self._knowledge_root))
        changed = False

        if manifest.knowledge_path != knowledge_path:
            manifest.knowledge_path = knowledge_path
            changed = True
        if manifest.knowledge_state != "awaiting" and manifest.knowledge_state != "missing":
            if manifest.knowledge_state != "stale":
                manifest.knowledge_state = "stale"
                changed = True
        elif manifest.knowledge_state == "missing":
            manifest.knowledge_state = "stale"
            changed = True

        if changed:
            write_source_manifest(self.root, manifest)

        return knowledge_path, target_path

    def materialize_markdown(
        self,
        *,
        knowledge_path: str,
        filename: str,
        canonical_id: str,
        markdown: str,
        source_type: str,
        source_url: str,
        content_hash: str,
        remote_fingerprint: str,
        materialized_utc: str,
    ) -> MaterializationResult:
        """Persist one managed markdown file and update its manifest metadata."""
        target_dir = self.ensure_knowledge_dir(knowledge_path)
        target = target_dir / filename
        target_markdown = prepend_managed_header(
            canonical_id,
            markdown,
            source_type=source_type,
            source_url=source_url,
        )
        try:
            changed = write_if_changed(target, target_markdown)

            duplicate_files_removed: list[str] = []
            for candidate in iterdir_paths(target_dir):
                if candidate == target or candidate.suffix.lower() != ".md" or not path_is_file(candidate):
                    continue
                if extract_source_id(candidate) != canonical_id:
                    continue
                try:
                    candidate.unlink()
                except PermissionError as exc:
                    if getattr(exc, "winerror", None) == 5:
                        log.warning(
                            "materialize_markdown left duplicate managed file in place after successful write: %s",
                            candidate,
                        )
                        continue
                    raise
                duplicate_files_removed.append(candidate.name)
        except PermissionError as exc:
            _raise_if_lock_contention("materialize_markdown", target, exc)

        materialized_path = normalize_path(target.relative_to(self._knowledge_root))
        target_path = normalize_path(target.parent.relative_to(self._knowledge_root))
        if read_source_manifest(self.root, canonical_id) is not None:
            update_manifest_materialization(
                self.root,
                canonical_id,
                knowledge_path=materialized_path,
                content_hash=content_hash,
                remote_fingerprint=remote_fingerprint,
                materialized_utc=materialized_utc,
            )

        return MaterializationResult(
            canonical_id=canonical_id,
            target_path=target_path,
            materialized_path=materialized_path,
            changed=changed,
            duplicate_files_removed=tuple(sorted(duplicate_files_removed)),
        )

    def rewrite_managed_identity(
        self,
        file_path: Path,
        *,
        canonical_id: str,
        source_type: str | None = None,
        source_url: str | None = None,
    ) -> None:
        """Rewrite managed identity frontmatter on an existing managed file."""
        managed_file = self._require_file_under_knowledge_root(file_path, operation="rewrite_managed_identity")
        content = read_text(managed_file, encoding="utf-8")
        updated = prepend_managed_header(
            canonical_id,
            content,
            source_type=source_type,
            source_url=source_url,
        )
        atomic_write_bytes(managed_file, updated.encode("utf-8"))

    def iter_orphan_attachment_dirs(self, manifests: dict[str, SourceManifest]) -> list[Path]:
        """Return managed attachment dirs with no matching registered source."""
        expected = {source_dir_id(manifest.canonical_id) for manifest in manifests.values()}
        orphans: list[Path] = []
        for attachments_dir in rglob_paths(self._knowledge_root, ATTACHMENTS_DIRNAME):
            if attachments_dir.parent.name != MANAGED_DIRNAME or not path_is_dir(attachments_dir):
                continue
            for child in iterdir_paths(attachments_dir):
                if path_is_dir(child) and child.name not in expected:
                    orphans.append(child)
        return orphans

    def remove_attachment_dir(self, attachment_dir: Path) -> bool:
        """Delete an orphan managed attachment dir."""
        rel = self._require_under_knowledge_root(attachment_dir, operation="remove_attachment_dir")
        if attachment_dir.parent.name != ATTACHMENTS_DIRNAME or attachment_dir.parent.parent.name != MANAGED_DIRNAME:
            raise BrainRepositoryInvariantError(
                f"remove_attachment_dir: path '{normalize_path(rel)}' is not a managed attachment directory"
            )
        if not path_is_dir(attachment_dir):
            return False
        shutil.rmtree(str(win_long_path(attachment_dir)))
        return True

    def iter_source_attachment_dirs(self, canonical_id: str, *, target_path: str | None = None) -> list[Path]:
        """Return every managed attachment directory owned by one source."""
        source_dir = source_dir_id(canonical_id)
        matches: list[Path] = []
        seen: set[Path] = set()

        if target_path is not None:
            normalized = self._normalize_relative_knowledge_path(
                target_path,
                operation="iter_source_attachment_dirs",
            )
            target_dir = self._knowledge_root / Path(normalized) if normalized else self._knowledge_root
            candidate = target_dir / MANAGED_DIRNAME / ATTACHMENTS_DIRNAME / source_dir
            if path_is_dir(candidate):
                matches.append(candidate)
                seen.add(candidate)

        for attachments_dir in rglob_paths(self._knowledge_root, ATTACHMENTS_DIRNAME):
            if attachments_dir.parent.name != MANAGED_DIRNAME or not path_is_dir(attachments_dir):
                continue
            candidate = attachments_dir / source_dir
            if path_is_dir(candidate) and candidate not in seen:
                matches.append(candidate)
                seen.add(candidate)

        return matches

    def remove_source_attachment_dirs(self, canonical_id: str, *, target_path: str | None = None) -> bool:
        """Delete every managed attachment directory owned by one source."""
        deleted = False
        for attachment_dir in self.iter_source_attachment_dirs(canonical_id, target_path=target_path):
            shutil.rmtree(str(win_long_path(attachment_dir)))
            deleted = True
        return deleted

    def move_knowledge_tree(self, source_path: str, dest_path: str) -> bool:
        """Move one knowledge area directory to another knowledge-relative path."""
        source_rel = self._normalize_relative_knowledge_path(source_path, operation="move_knowledge_tree(source_path)")
        dest_rel = self._normalize_relative_knowledge_path(dest_path, operation="move_knowledge_tree(dest_path)")
        source_dir = self._knowledge_root / Path(source_rel) if source_rel else self._knowledge_root
        dest_dir = self._knowledge_root / Path(dest_rel) if dest_rel else self._knowledge_root
        if source_dir == dest_dir or not path_exists(source_dir):
            return False
        dest_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(win_long_path(source_dir)), str(win_long_path(dest_dir)))
        return True

    def move_source_attachment_dir(self, source_path: str, dest_path: str, canonical_id: str) -> bool:
        """Move one source attachment directory between two knowledge areas."""
        source_rel = self._normalize_relative_knowledge_path(
            source_path,
            operation="move_source_attachment_dir(source_path)",
        )
        dest_rel = self._normalize_relative_knowledge_path(
            dest_path,
            operation="move_source_attachment_dir(dest_path)",
        )
        source_dir = self._knowledge_root / Path(source_rel) if source_rel else self._knowledge_root
        dest_dir = self._knowledge_root / Path(dest_rel) if dest_rel else self._knowledge_root
        old_att = self.source_attachment_dir(source_dir, canonical_id)
        new_att = self.source_attachment_dir(dest_dir, canonical_id)
        if not path_is_dir(old_att) or path_exists(new_att):
            return False
        new_att.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(win_long_path(old_att)), str(win_long_path(new_att)))
        return True

    def apply_folder_move_to_manifests(self, src_rel: str, dest_rel: str) -> list[ManifestMove]:
        """Update manifest portable paths after a knowledge-folder move."""
        src_rel = self._normalize_relative_knowledge_path(src_rel, operation="apply_folder_move_to_manifests(src_rel)")
        dest_rel = self._normalize_relative_knowledge_path(
            dest_rel,
            operation="apply_folder_move_to_manifests(dest_rel)",
        )
        if not src_rel or not dest_rel:
            raise BrainRepositoryInvariantError("apply_folder_move_to_manifests: folder move paths must be non-empty")
        updates: list[ManifestMove] = []
        for manifest in read_all_source_manifests(self.root).values():
            old_kp = manifest.knowledge_path
            old_tp = manifest.target_path

            if old_kp == src_rel or old_kp.startswith(src_rel + "/"):
                manifest.knowledge_path = dest_rel + old_kp[len(src_rel) :]
                if manifest.knowledge_state not in {"awaiting", "missing"}:
                    manifest.knowledge_state = "stale"

            if manifest.knowledge_path != old_kp:
                write_source_manifest(self.root, manifest)
                updates.append(
                    ManifestMove(
                        canonical_id=manifest.canonical_id,
                        old_target_path=old_tp,
                        new_target_path=manifest.target_path,
                        knowledge_path=manifest.knowledge_path,
                    )
                )
        return updates

    def write_attachment_bytes(self, *, target_dir: Path, local_path: str, data: bytes) -> bool:
        """Persist attachment bytes under one managed area path."""
        safe_target_dir = self._require_dir_under_knowledge_root(
            target_dir,
            operation="write_attachment_bytes(target_dir)",
        )
        rel_path = self._normalize_relative_portable_path(local_path, operation="write_attachment_bytes(local_path)")
        target = safe_target_dir / Path(rel_path)
        self._require_under_knowledge_root(target, operation="write_attachment_bytes")
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            return write_bytes_if_changed(target, data)
        except PermissionError as exc:
            _raise_if_lock_contention("write_attachment_bytes", target, exc)
            raise AssertionError("unreachable") from exc

    def migrate_legacy_attachment_context(self, target_dir: Path, *, source_dir: str, primary_canonical_id: str) -> int:
        """Best-effort migration from legacy attachment locations into .brain-sync/."""
        area_dir = self._require_dir_under_knowledge_root(target_dir, operation="migrate_legacy_attachment_context")
        migrated = 0
        new_dir = ensure_attachment_dir_for_source_dir(area_dir, source_dir)

        legacy_root = area_dir / "_sync-context"
        if path_is_dir(legacy_root):
            legacy_att_dir = legacy_root / "attachments"
            if path_is_dir(legacy_att_dir):
                for file_path in iterdir_paths(legacy_att_dir):
                    if not path_is_file(file_path):
                        continue
                    shutil.move(str(win_long_path(file_path)), str(win_long_path(new_dir / file_path.name)))
                    migrated += 1
            shutil.rmtree(str(win_long_path(legacy_root)))

        bare_id = primary_canonical_id.split(":", 1)[1]
        legacy_attachment_dir = area_dir / "_attachments" / bare_id
        if path_is_dir(legacy_attachment_dir):
            for file_path in iterdir_paths(legacy_attachment_dir):
                if not path_is_file(file_path):
                    continue
                shutil.move(str(win_long_path(file_path)), str(win_long_path(new_dir / file_path.name)))
                migrated += 1
            legacy_attachment_dir.rmdir()

        return migrated

    def remove_legacy_context_dir(self, legacy_dir: Path) -> bool:
        """Delete one legacy `_sync-context/` directory under the knowledge tree."""
        rel = self._require_under_knowledge_root(legacy_dir, operation="remove_legacy_context_dir")
        if legacy_dir.name != "_sync-context":
            raise BrainRepositoryInvariantError(
                f"remove_legacy_context_dir: path '{normalize_path(rel)}' is not a legacy _sync-context directory"
            )
        if not path_is_dir(legacy_dir):
            return False
        shutil.rmtree(str(win_long_path(legacy_dir)))
        return True

    def write_summary(self, knowledge_path: str, summary_text: str) -> Path:
        """Write one area summary under the managed insights subtree."""
        normalized = self._normalize_relative_knowledge_path(knowledge_path, operation="write_summary")
        summary_path = area_summary_path(self.root, normalized)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            atomic_write_bytes(summary_path, summary_text.encode("utf-8"))
        except PermissionError as exc:
            _raise_if_lock_contention("write_summary", summary_path, exc)
        return summary_path

    def save_portable_insight_state(
        self,
        knowledge_path: str,
        *,
        content_hash: str,
        summary_hash: str | None = None,
        structure_hash: str | None = None,
        last_regen_utc: str | None = None,
    ) -> bool:
        """Persist the durable insight-state sidecar for one knowledge area."""
        normalized = self._normalize_relative_knowledge_path(knowledge_path, operation="save_portable_insight_state")
        if not content_hash:
            raise BrainRepositoryInvariantError("save_portable_insight_state: content_hash is required")
        insights_dir = area_insights_dir(self.root, normalized)
        try:
            return sidecar_store.write_regen_meta(
                insights_dir,
                sidecar_store.RegenMeta(
                    content_hash=content_hash,
                    summary_hash=summary_hash,
                    structure_hash=structure_hash,
                    last_regen_utc=last_regen_utc,
                ),
            )
        except PermissionError as exc:
            _raise_if_lock_contention(
                "save_portable_insight_state",
                area_insight_state_path(self.root, normalized),
                exc,
            )
            raise AssertionError("unreachable") from exc
        except Exception:
            log.warning("Failed to write sidecar for %s", normalized, exc_info=True)
            raise

    def persist_regen_portable_state(
        self,
        knowledge_path: str,
        *,
        content_hash: str,
        summary_hash: str | None = None,
        structure_hash: str | None = None,
        last_regen_utc: str | None = None,
        summary_text: str | None = None,
    ) -> None:
        """Persist regen-owned portable artifacts through one repository seam.

        If ``summary_text`` is provided, the summary write is rolled back when
        the authoritative insight-state sidecar cannot be persisted.
        """
        normalized = self._normalize_relative_knowledge_path(
            knowledge_path,
            operation="persist_regen_portable_state",
        )
        summary_path = area_summary_path(self.root, normalized)
        previous_summary: bytes | None = None
        summary_existed = False

        if summary_text is not None:
            summary_existed = path_exists(summary_path)
            if summary_existed:
                previous_summary = read_bytes(summary_path)
            self.write_summary(normalized, summary_text)

        try:
            self.save_portable_insight_state(
                normalized,
                content_hash=content_hash,
                summary_hash=summary_hash,
                structure_hash=structure_hash,
                last_regen_utc=last_regen_utc,
            )
        except Exception:
            if summary_text is not None:
                try:
                    if summary_existed and previous_summary is not None:
                        atomic_write_bytes(summary_path, previous_summary)
                    elif path_exists(summary_path):
                        summary_path.unlink()
                except Exception:
                    log.exception(
                        "Failed to restore summary after portable regen persistence failure for %s",
                        normalized,
                    )
            raise

    def delete_portable_insight_state(self, knowledge_path: str) -> bool:
        """Delete the durable insight-state sidecar for one knowledge area."""
        normalized = self._normalize_relative_knowledge_path(
            knowledge_path,
            operation="delete_portable_insight_state",
        )
        sidecar_path = area_insight_state_path(self.root, normalized)
        existed = path_exists(sidecar_path)
        sidecar_store.delete_regen_meta(area_insights_dir(self.root, normalized))
        return existed

    def clean_regenerable_insights(self, knowledge_path: str) -> bool:
        """Remove regenerable insight artifacts while preserving non-regenerable ones."""
        normalized = self._normalize_relative_knowledge_path(knowledge_path, operation="clean_regenerable_insights")
        return clean_insights_tree(area_insights_dir(self.root, normalized))

    def append_journal_entry(
        self,
        knowledge_path: str,
        journal_text: str,
        *,
        timestamp: datetime | None = None,
    ) -> Path:
        """Append to the current journal file without rewriting prior entries."""
        normalized = self._normalize_relative_knowledge_path(knowledge_path, operation="append_journal_entry")
        self.heal_legacy_journal_layout(normalized)
        now = timestamp or datetime.now()
        journal_dir = area_journal_dir(self.root, normalized) / now.strftime("%Y-%m")
        journal_dir.mkdir(parents=True, exist_ok=True)
        journal_path = journal_dir / f"{now.strftime('%Y-%m-%d')}.md"
        timestamped = f"## {now.strftime('%H:%M')}\n\n{journal_text}"

        if path_exists(journal_path):
            existing = read_text(journal_path, encoding="utf-8")
            atomic_write_bytes(journal_path, (existing + "\n\n" + timestamped).encode("utf-8"))
        else:
            atomic_write_bytes(journal_path, timestamped.encode("utf-8"))
        return journal_path

    def heal_legacy_journal_layout(self, knowledge_path: str) -> bool:
        """Heal one area's legacy insights/journal subtree into .brain-sync/journal/."""
        normalized = self._normalize_relative_knowledge_path(knowledge_path, operation="heal_legacy_journal_layout")
        legacy_dir = area_insights_dir(self.root, normalized) / JOURNAL_DIRNAME
        if not path_is_dir(legacy_dir):
            return False

        target_root = area_journal_dir(self.root, normalized)

        for legacy_path in rglob_paths(legacy_dir, "*.md"):
            if not path_is_file(legacy_path):
                continue

            relative_path = legacy_path.relative_to(legacy_dir)
            target_path = target_root / relative_path
            target_path.parent.mkdir(parents=True, exist_ok=True)

            legacy_text = read_text(legacy_path, encoding="utf-8")
            target_exists = path_exists(target_path)
            if target_exists and not path_is_file(target_path):
                raise BrainRepositoryInvariantError(
                    f"heal_legacy_journal_layout: target '{target_path}' exists but is not a file"
                )

            merged_text = (
                _merge_journal_day_text(read_text(target_path, encoding="utf-8"), legacy_text)
                if target_exists
                else legacy_text.strip("\n")
            )

            if not target_exists or read_text(target_path, encoding="utf-8") != merged_text:
                atomic_write_bytes(target_path, merged_text.encode("utf-8"))

        shutil.rmtree(str(win_long_path(legacy_dir)))
        return True

    def remove_source_owned_files(self, target_path: str, canonical_id: str) -> bool:
        """Delete only the portable files owned by a synced source."""
        self._normalize_relative_knowledge_path(target_path, operation="remove_source_owned_files")
        deleted = False
        manifest = read_source_manifest(self.root, canonical_id)
        seen_files: set[Path] = set()

        if manifest is not None:
            resolved = self.resolve_source_file(manifest)
            if resolved.path is not None:
                owned_file = self._require_file_under_knowledge_root(
                    resolved.path,
                    operation="remove_source_owned_files",
                )
                owned_file.unlink()
                seen_files.add(owned_file)
                deleted = True

        for candidate in rglob_paths(self._knowledge_root, "*.md"):
            if candidate in seen_files or not path_is_file(candidate):
                continue
            if extract_source_id(candidate) != canonical_id:
                continue
            candidate.unlink()
            deleted = True

        if self.remove_source_managed_artifacts(target_path, canonical_id):
            deleted = True

        return deleted

    def remove_source_managed_artifacts(self, target_path: str, canonical_id: str) -> bool:
        """Delete only source-owned managed artifacts, preserving user-facing markdown."""
        normalized = self._normalize_relative_knowledge_path(
            target_path,
            operation="remove_source_managed_artifacts",
        )
        target_dir = self._knowledge_root / Path(normalized) if normalized else self._knowledge_root
        if path_exists(target_dir) and not path_is_dir(target_dir):
            raise BrainRepositoryInvariantError(
                f"remove_source_managed_artifacts: target path '{normalized}' does not resolve to a directory"
            )

        deleted = False
        if self.remove_source_attachment_dirs(canonical_id, target_path=target_path):
            deleted = True

        if path_is_dir(target_dir):
            legacy_ctx = target_dir / "_sync-context"
            if path_is_dir(legacy_ctx):
                shutil.rmtree(str(win_long_path(legacy_ctx)))
                deleted = True

        return deleted

    def _find_file_by_identity(self, canonical_id: str) -> Path | None:
        if not path_is_dir(self._knowledge_root):
            return None
        for candidate in rglob_paths(self._knowledge_root, "*.md"):
            if extract_source_id(candidate) == canonical_id:
                return candidate
        return None

    def _normalize_relative_knowledge_path(self, knowledge_path: str, *, operation: str) -> str:
        normalized = normalize_path(knowledge_path)
        if not normalized:
            return ""

        path_obj = Path(normalized)
        if path_obj.is_absolute() or any(part == ".." for part in path_obj.parts):
            raise BrainRepositoryInvariantError(
                f"{operation}: knowledge path '{knowledge_path}' must stay within the knowledge tree"
            )
        return normalized

    def _normalize_relative_portable_path(self, portable_path: str, *, operation: str) -> str:
        normalized = normalize_path(portable_path)
        path_obj = Path(normalized)
        if not normalized or path_obj.is_absolute() or any(part == ".." for part in path_obj.parts):
            raise BrainRepositoryInvariantError(
                f"{operation}: portable path '{portable_path}' must stay within the managed tree"
            )
        return normalized

    def _require_under_knowledge_root(self, path: Path, *, operation: str) -> Path:
        try:
            rel = path.relative_to(self._knowledge_root)
        except ValueError as exc:
            raise BrainRepositoryInvariantError(
                f"{operation}: path '{path}' is outside knowledge root '{self._knowledge_root}'"
            ) from exc
        if any(part == ".." for part in rel.parts):
            raise BrainRepositoryInvariantError(
                f"{operation}: path '{path}' escapes knowledge root '{self._knowledge_root}'"
            )
        return rel

    def _require_dir_under_knowledge_root(self, directory: Path, *, operation: str) -> Path:
        self._require_under_knowledge_root(directory, operation=operation)
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def _require_file_under_knowledge_root(self, file_path: Path, *, operation: str) -> Path:
        self._require_under_knowledge_root(file_path, operation=operation)
        if not path_is_file(file_path):
            raise BrainRepositoryInvariantError(
                f"{operation}: expected an existing file under knowledge root, got '{file_path}'"
            )
        return file_path


def _slug(text: str) -> str:
    return slugify(text)


def _split_journal_day(text: str) -> tuple[str, tuple[str, ...]]:
    normalized = text.strip("\n")
    if not normalized:
        return "", ()

    matches = list(_JOURNAL_HEADING_RE.finditer(normalized))
    if not matches:
        return normalized, ()

    preamble = normalized[: matches[0].start()].strip("\n")
    blocks: list[str] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized)
        block = normalized[start:end].strip("\n")
        if block:
            blocks.append(block)
    return preamble, tuple(blocks)


def _split_journal_preamble_sections(text: str) -> tuple[str, ...]:
    normalized = text.strip("\n")
    if not normalized:
        return ()
    return tuple(section.strip("\n") for section in re.split(r"\n{2,}", normalized) if section.strip("\n"))


def _merge_unique_sections(*groups: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    merged: list[str] = []
    for group in groups:
        for section in group:
            if section in seen:
                continue
            merged.append(section)
            seen.add(section)
    return tuple(merged)


def _journal_block_sort_key(block: str) -> tuple[str, str]:
    heading = block.splitlines()[0].strip()
    return heading.removeprefix("## "), block


def _merge_journal_day_text(target_text: str, legacy_text: str) -> str:
    target_preamble, target_blocks_tuple = _split_journal_day(target_text)
    legacy_preamble, legacy_blocks = _split_journal_day(legacy_text)
    preamble_sections = _merge_unique_sections(
        _split_journal_preamble_sections(legacy_preamble),
        _split_journal_preamble_sections(target_preamble),
    )
    merged_blocks = sorted(
        _merge_unique_sections(legacy_blocks, target_blocks_tuple),
        key=_journal_block_sort_key,
    )

    parts = [part for part in ("\n\n".join(preamble_sections), "\n\n".join(merged_blocks)) if part]
    return "\n\n".join(parts)
