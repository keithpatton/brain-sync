"""brain-sync doctor for the Brain Format 1.0 / supported runtime compatibility contract."""

from __future__ import annotations

import enum
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from brain_sync.application.insights import InsightState, load_all_insight_states, load_insight_state
from brain_sync.application.roots import InvalidBrainRootError, _require_root
from brain_sync.application.source_state import SyncState, save_state, seed_source_state_from_hint
from brain_sync.brain.fileops import (
    path_exists,
    path_is_dir,
    path_is_file,
    read_bytes,
    read_text,
    rglob_paths,
)
from brain_sync.brain.layout import (
    BRAIN_MANIFEST_VERSION,
    MANAGED_DIRNAME,
    SUMMARY_FILENAME,
    area_summary_path,
    brain_manifest_path,
    knowledge_root,
)
from brain_sync.brain.managed_markdown import extract_source_id
from brain_sync.brain.manifest import (
    SourceManifest,
    read_all_source_manifests,
    read_source_manifest,
)
from brain_sync.brain.repository import BrainRepository
from brain_sync.brain.sidecar import read_all_regen_meta, read_regen_meta
from brain_sync.brain.tree import normalize_path
from brain_sync.runtime.repository import (
    RegenLock,
    delete_regen_lock,
    delete_source,
    ensure_db,
    load_all_regen_locks,
    load_sync_progress,
    reset_runtime_db,
    save_regen_lock,
)

log = logging.getLogger(__name__)


class Severity(enum.Enum):
    OK = "OK"
    DRIFT = "DRIFT"
    WOULD_TRIGGER_REGEN = "WOULD_TRIGGER_REGEN"
    WOULD_TRIGGER_FETCH = "WOULD_TRIGGER_FETCH"
    CORRUPTION = "CORRUPTION"


@dataclass
class Finding:
    check: str
    severity: Severity
    message: str
    canonical_id: str | None = None
    knowledge_path: str | None = None
    fix_applied: bool = False


@dataclass
class DoctorResult:
    findings: list[Finding] = field(default_factory=list)
    fix_mode: bool = False

    @property
    def ok_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.OK)

    @property
    def drift_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.DRIFT)

    @property
    def would_trigger_regen_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.WOULD_TRIGGER_REGEN)

    @property
    def would_trigger_fetch_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.WOULD_TRIGGER_FETCH)

    @property
    def corruption_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.CORRUPTION)

    @property
    def is_healthy(self) -> bool:
        return all(f.severity == Severity.OK or f.fix_applied for f in self.findings)


def _build_identity_index(knowledge_root_path: Path) -> dict[str, Path]:
    """Single-pass scan of all .md files, returning {canonical_id: relative_path}."""
    index: dict[str, Path] = {}
    if not path_is_dir(knowledge_root_path):
        return index
    for path in rglob_paths(knowledge_root_path, "*.md"):
        cid = extract_source_id(path)
        if cid:
            index[cid] = path.relative_to(knowledge_root_path)
    return index


def _iter_summary_paths(root: Path) -> list[tuple[str, Path]]:
    result: list[tuple[str, Path]] = []
    for summary_path in rglob_paths(knowledge_root(root), SUMMARY_FILENAME):
        if summary_path.parts[-3:] != (MANAGED_DIRNAME, "insights", SUMMARY_FILENAME):
            continue
        area_dir = summary_path.parents[2]
        rel = area_dir.relative_to(knowledge_root(root))
        knowledge_path = "" if str(rel) == "." else normalize_path(rel)
        result.append((knowledge_path, summary_path))
    root_summary = area_summary_path(root, "")
    if path_is_file(root_summary):
        entry = ("", root_summary)
        if entry not in result:
            result.append(entry)
    return result


def _legacy_layout_findings(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    legacy_paths = [
        (root / "insights", "Unsupported legacy top-level insights/ directory"),
        (root / "schemas", "Unsupported legacy top-level schemas/ directory"),
        (root / ".sync-state.sqlite", "Unsupported legacy root-local runtime DB"),
        (root / ".brain-sync" / "version.json", "Unsupported legacy .brain-sync/version.json"),
    ]
    for path, message in legacy_paths:
        if path_exists(path):
            findings.append(Finding(check="unsupported_legacy_layout", severity=Severity.CORRUPTION, message=message))
    return findings


def _resolve_doctor_root(root: Path | None) -> Path:
    if root is None:
        return _require_root(None)
    resolved = root.resolve()
    if not path_is_dir(knowledge_root(resolved)):
        raise InvalidBrainRootError(
            f"Brain root '{resolved}' is invalid.\n"
            f"Expected structure:\n"
            f"  {resolved}/knowledge/\n"
            f"The configured root appears to point to the wrong directory."
        )
    return resolved


def check_version_json(root: Path) -> list[Finding]:
    """Verify .brain-sync/brain.json exists and matches the supported version."""
    manifest_path = brain_manifest_path(root)
    if not path_exists(manifest_path):
        return [Finding(check="brain_manifest", severity=Severity.CORRUPTION, message="Missing .brain-sync/brain.json")]
    try:
        data = json.loads(read_bytes(manifest_path))
    except (json.JSONDecodeError, OSError) as exc:
        return [Finding(check="brain_manifest", severity=Severity.CORRUPTION, message=f"Invalid brain.json: {exc}")]
    if data != {"version": BRAIN_MANIFEST_VERSION}:
        return [
            Finding(
                check="brain_manifest",
                severity=Severity.CORRUPTION,
                message=f'brain.json must equal {{"version": {BRAIN_MANIFEST_VERSION}}}',
            )
        ]
    return [Finding(check="brain_manifest", severity=Severity.OK, message="brain.json OK")]


def check_manifest_file_match(
    root: Path,
    manifests: dict[str, SourceManifest],
    knowledge_root_path: Path,
    identity_index: dict[str, Path],
) -> list[Finding]:
    repository = BrainRepository(root)
    findings: list[Finding] = []
    for cid, manifest in manifests.items():
        if manifest.status != "active":
            continue
        resolution = repository.resolve_source_file(manifest, identity_index=identity_index)
        found = resolution.path
        if resolution.resolution == "unmaterialized":
            findings.append(
                Finding(
                    check="manifest_file_match",
                    severity=Severity.OK,
                    message="Unmaterialized source (new or unsynced)",
                    canonical_id=cid,
                )
            )
            continue

        if resolution.resolution == "direct":
            findings.append(
                Finding(
                    check="manifest_file_match",
                    severity=Severity.OK,
                    message="File at expected path",
                    canonical_id=cid,
                )
            )
            continue

        if found is not None:
            findings.append(
                Finding(
                    check="manifest_file_match",
                    severity=Severity.DRIFT,
                    message=(
                        f"File moved: expected '{manifest.materialized_path}', "
                        f"found '{normalize_path(found.relative_to(knowledge_root_path))}'"
                    ),
                    canonical_id=cid,
                )
            )
            continue

        findings.append(
            Finding(
                check="manifest_file_match",
                severity=Severity.WOULD_TRIGGER_FETCH,
                message=f"File not found: '{manifest.materialized_path}'",
                canonical_id=cid,
            )
        )
    return findings


def check_identity_headers(
    root: Path,
    manifests: dict[str, SourceManifest],
    knowledge_root_path: Path,
    identity_index: dict[str, Path],
) -> list[Finding]:
    repository = BrainRepository(root)
    findings: list[Finding] = []
    for cid, manifest in manifests.items():
        if manifest.status != "active" or not manifest.materialized_path:
            continue
        file_path = repository.resolve_source_file(manifest, identity_index=identity_index).path
        if file_path is None or not path_is_file(file_path):
            continue

        found_cid = extract_source_id(file_path)
        if found_cid == cid:
            findings.append(
                Finding(check="identity_headers", severity=Severity.OK, message="Identity matches", canonical_id=cid)
            )
        elif found_cid is None:
            findings.append(
                Finding(
                    check="identity_headers",
                    severity=Severity.DRIFT,
                    message="Missing managed identity frontmatter",
                    canonical_id=cid,
                )
            )
        else:
            findings.append(
                Finding(
                    check="identity_headers",
                    severity=Severity.DRIFT,
                    message=f"Wrong identity: expected '{cid}', found '{found_cid}'",
                    canonical_id=cid,
                )
            )
    return findings


def check_orphan_attachments(
    root: Path, manifests: dict[str, SourceManifest], knowledge_root_path: Path
) -> list[Finding]:
    repository = BrainRepository(root)
    findings: list[Finding] = []
    for orphan in repository.iter_orphan_attachment_dirs(manifests):
        findings.append(
            Finding(
                check="orphan_attachments",
                severity=Severity.DRIFT,
                message=f"Orphan attachment dir: {normalize_path(orphan.relative_to(knowledge_root_path))}",
                knowledge_path=normalize_path(orphan.relative_to(knowledge_root_path)),
            )
        )
    return findings


def check_unregistered_synced_files(
    root: Path,
    manifests: dict[str, SourceManifest],
    identity_index: dict[str, Path],
) -> list[Finding]:
    findings: list[Finding] = []
    for cid, rel_path in identity_index.items():
        if cid not in manifests:
            findings.append(
                Finding(
                    check="unregistered_synced_files",
                    severity=Severity.DRIFT,
                    message=f"File has managed identity for '{cid}' but no manifest exists",
                    canonical_id=cid,
                    knowledge_path=normalize_path(rel_path),
                )
            )
    return findings


def check_db_source_consistency(root: Path, manifests: dict[str, SourceManifest]) -> list[Finding]:
    findings: list[Finding] = []
    for cid in load_sync_progress(root):
        if cid not in manifests:
            findings.append(
                Finding(
                    check="db_source_consistency",
                    severity=Severity.DRIFT,
                    message="Runtime DB row has no matching manifest",
                    canonical_id=cid,
                )
            )
    return findings


def check_path_normalization(root: Path, manifests: dict[str, SourceManifest]) -> list[Finding]:
    findings: list[Finding] = []
    for cid, manifest in manifests.items():
        for field_name, value in (
            ("materialized_path", manifest.materialized_path),
            ("target_path", manifest.target_path),
        ):
            if value and "\\" in value:
                findings.append(
                    Finding(
                        check="path_normalization",
                        severity=Severity.DRIFT,
                        message=f"Backslash in manifest {field_name}: '{value}'",
                        canonical_id=cid,
                    )
                )
    return findings


def check_legacy_journal_layout(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for journal_dir in rglob_paths(knowledge_root(root), "journal"):
        if not path_is_dir(journal_dir):
            continue
        if journal_dir.parent.name != "insights" or journal_dir.parent.parent.name != MANAGED_DIRNAME:
            continue

        area_dir = journal_dir.parents[2]
        rel = area_dir.relative_to(knowledge_root(root))
        knowledge_path = "" if str(rel) == "." else normalize_path(rel)
        display_path = knowledge_path or "(root)"
        findings.append(
            Finding(
                check="legacy_journal_layout",
                severity=Severity.DRIFT,
                message=f"Legacy journal subtree is repairable drift for '{display_path}'",
                knowledge_path=knowledge_path,
            )
        )
    return findings


def check_orphan_insights(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    legacy_root = root / "insights"
    if path_exists(legacy_root):
        findings.append(
            Finding(
                check="unsupported_legacy_layout",
                severity=Severity.CORRUPTION,
                message="Unsupported legacy top-level insights/ directory",
            )
        )
    return findings


def check_orphan_insight_state_rows(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for state in load_all_insight_states(root):
        area_path = knowledge_root(root) / state.knowledge_path if state.knowledge_path else knowledge_root(root)
        if not path_is_dir(area_path):
            findings.append(
                Finding(
                    check="orphan_insight_state_rows",
                    severity=Severity.DRIFT,
                    message=f"Regen state for non-existent area: '{state.knowledge_path}'",
                    knowledge_path=state.knowledge_path,
                )
            )
    return findings


def check_summaries_without_db_rows(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    state_paths = {state.knowledge_path for state in load_all_insight_states(root)}
    for knowledge_path, _ in _iter_summary_paths(root):
        if knowledge_path not in state_paths:
            findings.append(
                Finding(
                    check="summaries_without_db_rows",
                    severity=Severity.WOULD_TRIGGER_REGEN,
                    message=f"Summary exists but no regen state: '{knowledge_path}'",
                    knowledge_path=knowledge_path,
                )
            )
    return findings


def check_stale_summaries(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for knowledge_path, summary_path in _iter_summary_paths(root):
        area_dir = summary_path.parents[2]
        if not path_is_dir(area_dir):
            findings.append(
                Finding(
                    check="stale_summaries",
                    severity=Severity.DRIFT,
                    message=f"Summary exists outside a valid area: '{knowledge_path}'",
                    knowledge_path=knowledge_path,
                )
            )
    return findings


def check_regen_change_detection(root: Path) -> list[Finding]:
    from brain_sync.application.regen import classify_folder_change

    findings: list[Finding] = []
    for state in load_all_insight_states(root):
        area_path = knowledge_root(root) / state.knowledge_path if state.knowledge_path else knowledge_root(root)
        if not path_is_dir(area_path):
            continue
        change, _, _ = classify_folder_change(root, state.knowledge_path)
        if change.change_type == "none":
            continue
        message = "Structure-only change detected" if change.structural else "Content change detected"
        findings.append(
            Finding(
                check="regen_change_detection",
                severity=Severity.WOULD_TRIGGER_REGEN,
                message=f"{message} in '{state.knowledge_path}'",
                knowledge_path=state.knowledge_path,
            )
        )
    return findings


def check_db_path_normalization(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for state in load_all_insight_states(root):
        knowledge_path = state.knowledge_path
        if knowledge_path and (
            "\\" in knowledge_path or knowledge_path.startswith("/") or ".." in knowledge_path.split("/")
        ):
            findings.append(
                Finding(
                    check="db_path_normalization",
                    severity=Severity.DRIFT,
                    message=f"Bad regen_locks path: '{knowledge_path}'",
                    knowledge_path=knowledge_path,
                )
            )
    return findings


def check_missing_sidecars(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for knowledge_path, summary_path in _iter_summary_paths(root):
        meta = read_regen_meta(summary_path.parent)
        if meta is not None:
            continue
        sidecar_path = summary_path.parent / "insight-state.json"
        severity = Severity.CORRUPTION if path_exists(sidecar_path) else Severity.WOULD_TRIGGER_REGEN
        message = (
            f"Malformed insight-state for '{knowledge_path}'"
            if path_exists(sidecar_path)
            else f"Missing insight-state for '{knowledge_path}'"
        )
        findings.append(
            Finding(check="missing_sidecars", severity=severity, message=message, knowledge_path=knowledge_path)
        )
    return findings


def check_sidecar_integrity(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    sidecars = read_all_regen_meta(knowledge_root(root))
    lock_paths = {lock.knowledge_path for lock in load_all_regen_locks(root)}
    for knowledge_path in sidecars:
        if knowledge_path not in lock_paths:
            findings.append(
                Finding(
                    check="sidecar_integrity",
                    severity=Severity.DRIFT,
                    message=f"Insight-state exists but no regen state for '{knowledge_path}'",
                    knowledge_path=knowledge_path,
                )
            )
    return findings


def _save_portable_and_runtime_insight_state(root: Path, repository: BrainRepository, state: InsightState) -> None:
    """Persist portable hashes through the repository and lifecycle through runtime state."""
    if state.content_hash is not None:
        repository.save_portable_insight_state(
            state.knowledge_path,
            content_hash=state.content_hash,
            summary_hash=state.summary_hash,
            structure_hash=state.structure_hash,
            last_regen_utc=state.last_regen_utc,
        )
    save_regen_lock(
        root,
        RegenLock(
            knowledge_path=state.knowledge_path,
            regen_status=state.regen_status,
            regen_started_utc=state.regen_started_utc,
            owner_id=state.owner_id,
            error_reason=state.error_reason,
        ),
    )


def doctor(root: Path | None = None, *, fix: bool = False) -> DoctorResult:
    root = _resolve_doctor_root(root)
    legacy_findings = _legacy_layout_findings(root)
    if legacy_findings:
        return DoctorResult(findings=legacy_findings, fix_mode=fix)

    knowledge_root_path = knowledge_root(root)
    manifests = read_all_source_manifests(root)
    identity_index = _build_identity_index(knowledge_root_path)

    findings: list[Finding] = []
    findings.extend(check_version_json(root))
    findings.extend(check_manifest_file_match(root, manifests, knowledge_root_path, identity_index))
    findings.extend(check_identity_headers(root, manifests, knowledge_root_path, identity_index))
    findings.extend(check_orphan_attachments(root, manifests, knowledge_root_path))
    findings.extend(check_unregistered_synced_files(root, manifests, identity_index))
    findings.extend(check_db_source_consistency(root, manifests))
    findings.extend(check_path_normalization(root, manifests))
    findings.extend(check_legacy_journal_layout(root))
    findings.extend(check_orphan_insight_state_rows(root))
    findings.extend(check_summaries_without_db_rows(root))
    findings.extend(check_stale_summaries(root))
    findings.extend(check_regen_change_detection(root))
    findings.extend(check_db_path_normalization(root))
    findings.extend(check_missing_sidecars(root))
    findings.extend(check_sidecar_integrity(root))

    if fix:
        _apply_fixes(root, findings, manifests, knowledge_root_path, identity_index)

    return DoctorResult(findings=findings, fix_mode=fix)


def _apply_fixes(
    root: Path,
    findings: list[Finding],
    manifests: dict[str, SourceManifest],
    knowledge_root_path: Path,
    identity_index: dict[str, Path],
) -> None:
    repository = BrainRepository(root)
    for finding in findings:
        if finding.severity not in {Severity.DRIFT, Severity.CORRUPTION}:
            continue
        try:
            if finding.check == "brain_manifest":
                repository.write_brain_manifest()
                finding.fix_applied = True

            elif finding.check == "manifest_file_match" and finding.canonical_id:
                manifest = manifests.get(finding.canonical_id)
                if manifest is None:
                    continue
                resolved = repository.resolve_source_file(manifest, identity_index=identity_index)
                if resolved.path is not None:
                    repository.sync_manifest_to_found_path(finding.canonical_id, resolved.path)
                    finding.fix_applied = True

            elif finding.check == "identity_headers" and finding.canonical_id:
                manifest = manifests.get(finding.canonical_id)
                if manifest is None:
                    continue
                file_path = repository.resolve_source_file(manifest, identity_index=identity_index).path
                if file_path is not None:
                    repository.rewrite_managed_identity(
                        file_path,
                        canonical_id=finding.canonical_id,
                        source_type=manifest.source_type,
                        source_url=manifest.source_url,
                    )
                    finding.fix_applied = True

            elif finding.check == "orphan_attachments" and finding.knowledge_path:
                orphan_dir = knowledge_root_path / finding.knowledge_path
                if repository.remove_attachment_dir(orphan_dir):
                    finding.fix_applied = True

            elif finding.check == "db_source_consistency" and finding.canonical_id:
                delete_source(root, finding.canonical_id)
                finding.fix_applied = True

            elif finding.check == "path_normalization" and finding.canonical_id:
                manifest = read_source_manifest(root, finding.canonical_id)
                if manifest is None:
                    continue
                manifest.materialized_path = normalize_path(manifest.materialized_path)
                manifest.target_path = normalize_path(manifest.target_path)
                repository.save_source_manifest(manifest)
                finding.fix_applied = True

            elif finding.check == "legacy_journal_layout" and finding.knowledge_path is not None:
                if repository.heal_legacy_journal_layout(finding.knowledge_path):
                    finding.fix_applied = True

            elif finding.check == "orphan_insight_state_rows" and finding.knowledge_path is not None:
                repository.delete_portable_insight_state(finding.knowledge_path)
                delete_regen_lock(root, finding.knowledge_path)
                finding.fix_applied = True

            elif finding.check == "db_path_normalization" and finding.knowledge_path:
                state = load_insight_state(root, finding.knowledge_path)
                if state is None:
                    continue
                state.knowledge_path = normalize_path(state.knowledge_path)
                _save_portable_and_runtime_insight_state(root, repository, state)
                finding.fix_applied = True
        except Exception:
            log.exception("Failed to fix %s for %s", finding.check, finding.canonical_id or finding.knowledge_path)


def rebuild_db(root: Path | None = None) -> DoctorResult:
    root = _resolve_doctor_root(root)
    if _legacy_layout_findings(root):
        return DoctorResult(findings=_legacy_layout_findings(root), fix_mode=True)

    exported_states = load_all_insight_states(root)
    reset_runtime_db(root)
    ensure_db(root)

    for state in exported_states:
        save_regen_lock(
            root,
            RegenLock(
                knowledge_path=state.knowledge_path,
                regen_status="idle",
            ),
        )

    manifests = read_all_source_manifests(root)
    state = SyncState()
    for cid, manifest in manifests.items():
        if manifest.status == "active":
            target_path = normalize_path(manifest.target_path) if manifest.target_path else ""
            state.sources[cid] = seed_source_state_from_hint(root, manifest, target_path)
    if state.sources:
        save_state(root, state)
    return doctor(root, fix=False)


def deregister_missing(root: Path | None = None) -> DoctorResult:
    root = _resolve_doctor_root(root)
    findings: list[Finding] = []
    for cid, manifest in read_all_source_manifests(root).items():
        if manifest.status != "missing":
            continue
        BrainRepository(root).delete_source_registration(cid)
        delete_source(root, cid)
        findings.append(
            Finding(
                check="deregister_missing",
                severity=Severity.OK,
                message=f"Deregistered missing source: {cid}",
                canonical_id=cid,
                fix_applied=True,
            )
        )
    if not findings:
        findings.append(
            Finding(check="deregister_missing", severity=Severity.OK, message="No missing sources to deregister")
        )
    return DoctorResult(findings=findings, fix_mode=True)


def adopt_baseline(root: Path | None = None) -> DoctorResult:
    import hashlib

    from brain_sync.application.regen import compute_folder_hashes

    root = _resolve_doctor_root(root)
    if _legacy_layout_findings(root):
        return DoctorResult(findings=_legacy_layout_findings(root), fix_mode=True)

    findings: list[Finding] = []
    existing_locks = {lock.knowledge_path for lock in load_all_regen_locks(root)}

    for knowledge_path, summary_path in _iter_summary_paths(root):
        area_path = summary_path.parents[2]
        if not path_is_dir(area_path):
            findings.append(
                Finding(
                    check="adopt_baseline",
                    severity=Severity.DRIFT,
                    message=f"Orphan insight area: '{knowledge_path}'",
                    knowledge_path=knowledge_path,
                )
            )
            continue

        existing_meta = read_regen_meta(summary_path.parent)
        if existing_meta is not None and knowledge_path in existing_locks:
            findings.append(
                Finding(
                    check="adopt_baseline",
                    severity=Severity.OK,
                    message=f"Already baselined: '{knowledge_path}'",
                    knowledge_path=knowledge_path,
                )
            )
            continue

        content_hash, structure_hash = compute_folder_hashes(root, knowledge_path)
        summary_hash = hashlib.sha256(read_text(summary_path, encoding="utf-8").encode("utf-8")).hexdigest()

        _save_portable_and_runtime_insight_state(
            root,
            BrainRepository(root),
            InsightState(
                knowledge_path=knowledge_path,
                content_hash=content_hash,
                summary_hash=summary_hash,
                structure_hash=structure_hash,
                regen_status="idle",
            ),
        )
        findings.append(
            Finding(
                check="adopt_baseline",
                severity=Severity.OK,
                message=f"Adopted baseline for '{knowledge_path}'",
                knowledge_path=knowledge_path,
                fix_applied=True,
            )
        )

    if not findings:
        findings.append(Finding(check="adopt_baseline", severity=Severity.OK, message="No summaries found to adopt"))
    return DoctorResult(findings=findings, fix_mode=True)
