"""Portable brain-state authority helpers.

This module owns correctness-critical semantics for the portable brain plane:
managed filesystem paths, source rediscovery, durable manifest updates,
attachment-directory locations, and journal-safe cleanup behavior.

It intentionally does not own runtime DB or daemon/config state. Those remain
in the runtime plane (currently ``state.py`` and related modules).
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from brain_sync.fileops import (
    atomic_write_bytes,
    canonical_prefix,
    clean_insights_tree,
    iterdir_paths,
    path_exists,
    path_is_dir,
    path_is_file,
    read_text,
    rediscover_local_path,
    rglob_paths,
    win_long_path,
)
from brain_sync.fs_utils import normalize_path
from brain_sync.layout import (
    ATTACHMENTS_DIRNAME,
    MANAGED_DIRNAME,
    area_insights_dir,
    knowledge_root,
)
from brain_sync.manifest import (
    SourceManifest,
    read_all_source_manifests,
    read_source_manifest,
    write_source_manifest,
)


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
    materialized_path: str


class BrainRepositoryInvariantError(RuntimeError):
    """Raised when a strict repository mutation receives invalid input."""


class BrainRepository:
    """Root-bound helper for portable brain semantics."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._knowledge_root = knowledge_root(root)

    @property
    def knowledge_root(self) -> Path:
        return self._knowledge_root

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

        if manifest.materialized_path:
            direct = self._knowledge_root / manifest.materialized_path
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

        if manifest.status == "active" and not manifest.materialized_path:
            return SourceResolution(canonical_id=canonical_id, path=None, resolution="unmaterialized")

        return SourceResolution(canonical_id=canonical_id, path=None, resolution="missing")

    def sync_manifest_to_found_path(self, canonical_id: str, found_path: Path) -> tuple[str, str]:
        """Update a source manifest to match a resolved filesystem path."""
        operation = "sync_manifest_to_found_path"
        manifest = read_source_manifest(self.root, canonical_id)
        if manifest is None:
            raise BrainRepositoryInvariantError(f"{operation}: manifest not found for {canonical_id}")

        found_file = self._require_file_under_knowledge_root(found_path, operation=operation)
        materialized_path = normalize_path(found_file.relative_to(self._knowledge_root))
        target_path = normalize_path(found_file.parent.relative_to(self._knowledge_root))
        changed = False

        if manifest.materialized_path != materialized_path:
            manifest.materialized_path = materialized_path
            changed = True
        if manifest.target_path != target_path:
            manifest.target_path = target_path
            changed = True

        if changed:
            write_source_manifest(self.root, manifest)

        return materialized_path, target_path

    def record_materialized_file(self, canonical_id: str, file_path: Path) -> tuple[str, str]:
        """Persist manifest reality after a successful materialization write."""
        return self.sync_manifest_to_found_path(canonical_id, file_path)

    def rewrite_managed_identity(
        self,
        file_path: Path,
        *,
        canonical_id: str,
        source_type: str | None = None,
        source_url: str | None = None,
    ) -> None:
        """Rewrite managed identity using the same semantics as the pipeline."""
        from brain_sync.pipeline import prepend_managed_header

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
            old_mp = manifest.materialized_path
            old_tp = manifest.target_path

            if old_mp and (old_mp == src_rel or old_mp.startswith(src_rel + "/")):
                manifest.materialized_path = dest_rel + old_mp[len(src_rel) :]
            if old_tp == src_rel or old_tp.startswith(src_rel + "/"):
                manifest.target_path = dest_rel + old_tp[len(src_rel) :]

            if manifest.materialized_path != old_mp or manifest.target_path != old_tp:
                write_source_manifest(self.root, manifest)
                updates.append(
                    ManifestMove(
                        canonical_id=manifest.canonical_id,
                        old_target_path=old_tp,
                        new_target_path=manifest.target_path,
                        materialized_path=manifest.materialized_path,
                    )
                )
        return updates

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
        now = timestamp or datetime.now()
        journal_dir = area_insights_dir(self.root, normalized) / "journal" / now.strftime("%Y-%m")
        journal_dir.mkdir(parents=True, exist_ok=True)
        journal_path = journal_dir / f"{now.strftime('%Y-%m-%d')}.md"
        timestamped = f"## {now.strftime('%H:%M')}\n\n{journal_text}"

        if path_exists(journal_path):
            existing = read_text(journal_path, encoding="utf-8")
            atomic_write_bytes(journal_path, (existing + "\n\n" + timestamped).encode("utf-8"))
        else:
            atomic_write_bytes(journal_path, timestamped.encode("utf-8"))
        return journal_path

    def remove_source_owned_files(self, target_path: str, canonical_id: str) -> bool:
        """Delete only the portable files owned by a synced source in one area."""
        normalized = self._normalize_relative_knowledge_path(target_path, operation="remove_source_owned_files")
        target_dir = self._knowledge_root / Path(normalized) if normalized else self._knowledge_root
        if not path_exists(target_dir):
            return False
        if not path_is_dir(target_dir):
            raise BrainRepositoryInvariantError(
                f"remove_source_owned_files: target path '{normalized}' does not resolve to a directory"
            )

        deleted = False
        prefix = canonical_prefix(canonical_id)
        for candidate in iterdir_paths(target_dir):
            if path_is_file(candidate) and candidate.name.startswith(prefix):
                candidate.unlink()
                deleted = True

        if remove_source_attachment_dir(target_dir, canonical_id):
            deleted = True

        legacy_ctx = target_dir / "_sync-context"
        if path_is_dir(legacy_ctx):
            shutil.rmtree(str(win_long_path(legacy_ctx)))
            deleted = True

        for dirpath in sorted(rglob_paths(target_dir, "*"), reverse=True):
            if path_is_dir(dirpath) and not iterdir_paths(dirpath):
                dirpath.rmdir()
        if path_exists(target_dir) and not iterdir_paths(target_dir):
            target_dir.rmdir()

        return deleted

    def _find_file_by_identity(self, canonical_id: str) -> Path | None:
        from brain_sync.pipeline import extract_source_id

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

    def _require_file_under_knowledge_root(self, file_path: Path, *, operation: str) -> Path:
        self._require_under_knowledge_root(file_path, operation=operation)
        if not path_is_file(file_path):
            raise BrainRepositoryInvariantError(
                f"{operation}: expected an existing file under knowledge root, got '{file_path}'"
            )
        return file_path


def _slug(text: str) -> str:
    from brain_sync.sources import slugify

    return slugify(text)
