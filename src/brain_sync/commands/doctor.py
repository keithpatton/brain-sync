"""brain-sync doctor — consistency checker and recovery lever.

Covers both the manifest-authoritative source model and the DB-authoritative
regen model.  Each ``check_*`` function returns ``list[Finding]`` and is
independently testable.
"""

from __future__ import annotations

import enum
import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from brain_sync.commands.context import _require_root
from brain_sync.fileops import (
    INSIGHT_ARTIFACT_DIRS,
    atomic_write_bytes,
    canonical_prefix,
    clean_insights_tree,
    rediscover_local_path,
)
from brain_sync.fs_utils import normalize_path
from brain_sync.manifest import (
    MANIFEST_VERSION_FILE,
    SourceManifest,
    delete_source_manifest,
    read_all_source_manifests,
    update_manifest_materialized_path,
    write_source_manifest,
)
from brain_sync.pipeline import extract_source_id, prepend_managed_header
from brain_sync.sidecar import (
    read_all_regen_meta,
    read_regen_meta,
)
from brain_sync.state import (
    InsightState,
    _connect,
    _load_db_sync_progress,
    _seed_from_hint,
    delete_insight_state,
    delete_source,
    load_all_insight_states,
    save_insight_state,
    save_state,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_identity_index(knowledge_root: Path) -> dict[str, Path]:
    """Single-pass scan of all .md files, returning {canonical_id: Path}.

    Path values are relative to knowledge_root.
    """
    index: dict[str, Path] = {}
    if not knowledge_root.is_dir():
        return index
    for path in knowledge_root.rglob("*.md"):
        if not path.is_file():
            continue
        cid = extract_source_id(path)
        if cid:
            index[cid] = path.relative_to(knowledge_root)
    return index


# ---------------------------------------------------------------------------
# Step 1: Source manifest checks
# ---------------------------------------------------------------------------


def check_version_json(root: Path) -> list[Finding]:
    """Verify .brain-sync/version.json exists and is valid."""
    version_path = root / MANIFEST_VERSION_FILE
    if not version_path.exists():
        return [Finding(check="version_json", severity=Severity.CORRUPTION, message="Missing .brain-sync/version.json")]
    try:
        data = json.loads(version_path.read_bytes())
    except (json.JSONDecodeError, OSError) as e:
        return [Finding(check="version_json", severity=Severity.CORRUPTION, message=f"Invalid version.json: {e}")]
    if "manifest_version" not in data:
        return [
            Finding(
                check="version_json",
                severity=Severity.CORRUPTION,
                message="version.json missing 'manifest_version' field",
            )
        ]
    return [Finding(check="version_json", severity=Severity.OK, message="version.json OK")]


def check_manifest_file_match(
    root: Path,
    manifests: dict[str, SourceManifest],
    knowledge_root: Path,
    identity_index: dict[str, Path],
) -> list[Finding]:
    """For each active manifest, verify the file exists at the expected path."""
    findings: list[Finding] = []
    for cid, m in manifests.items():
        if m.status != "active":
            continue
        if not m.materialized_path:
            findings.append(
                Finding(
                    check="manifest_file_match",
                    severity=Severity.OK,
                    message="Unmaterialized source (new/unsynced)",
                    canonical_id=cid,
                )
            )
            continue

        expected = knowledge_root / m.materialized_path
        if expected.is_file():
            findings.append(
                Finding(
                    check="manifest_file_match",
                    severity=Severity.OK,
                    message="File at expected path",
                    canonical_id=cid,
                )
            )
            continue

        # Try identity index (tier-2)
        if cid in identity_index:
            found_rel = normalize_path(identity_index[cid])
            findings.append(
                Finding(
                    check="manifest_file_match",
                    severity=Severity.DRIFT,
                    message=f"File moved: expected '{m.materialized_path}', found '{found_rel}'",
                    canonical_id=cid,
                )
            )
            continue

        # Try rediscover (tier-3)
        found = rediscover_local_path(knowledge_root, cid)
        if found is not None:
            found_rel = normalize_path(found)
            findings.append(
                Finding(
                    check="manifest_file_match",
                    severity=Severity.DRIFT,
                    message=f"File moved: expected '{m.materialized_path}', found '{found_rel}'",
                    canonical_id=cid,
                )
            )
            continue

        findings.append(
            Finding(
                check="manifest_file_match",
                severity=Severity.WOULD_TRIGGER_FETCH,
                message=f"File not found: '{m.materialized_path}'",
                canonical_id=cid,
            )
        )
    return findings


def check_identity_headers(
    root: Path,
    manifests: dict[str, SourceManifest],
    knowledge_root: Path,
    identity_index: dict[str, Path],
) -> list[Finding]:
    """For each manifest with a found file on disk, verify the identity header."""
    findings: list[Finding] = []
    for cid, m in manifests.items():
        if m.status != "active" or not m.materialized_path:
            continue

        # Find the file — use materialized_path first, then identity index
        file_path = knowledge_root / m.materialized_path
        if not file_path.is_file():
            if cid in identity_index:
                file_path = knowledge_root / identity_index[cid]
            else:
                continue  # file not found, handled by manifest_file_match check

        found_cid = extract_source_id(file_path)
        if found_cid == cid:
            findings.append(
                Finding(
                    check="identity_headers",
                    severity=Severity.OK,
                    message="Identity header matches",
                    canonical_id=cid,
                )
            )
        elif found_cid is None:
            findings.append(
                Finding(
                    check="identity_headers",
                    severity=Severity.DRIFT,
                    message="Missing identity header",
                    canonical_id=cid,
                )
            )
        else:
            findings.append(
                Finding(
                    check="identity_headers",
                    severity=Severity.DRIFT,
                    message=f"Wrong identity header: expected '{cid}', found '{found_cid}'",
                    canonical_id=cid,
                )
            )
    return findings


def check_orphan_attachments(
    root: Path,
    manifests: dict[str, SourceManifest],
    knowledge_root: Path,
) -> list[Finding]:
    """Check for _attachments/ dirs with no matching manifest."""
    findings: list[Finding] = []
    expected_prefixes: set[str] = set()
    for m in manifests.values():
        prefix = canonical_prefix(m.canonical_id).rstrip("-")
        expected_prefixes.add(prefix)

    # Walk knowledge/ for _attachments/*/ directories
    for att_dir in knowledge_root.rglob("_attachments"):
        if not att_dir.is_dir():
            continue
        for child in att_dir.iterdir():
            if not child.is_dir():
                continue
            if child.name not in expected_prefixes:
                rel = normalize_path(child.relative_to(knowledge_root))
                findings.append(
                    Finding(
                        check="orphan_attachments",
                        severity=Severity.DRIFT,
                        message=f"Orphan attachment dir: {rel}",
                        knowledge_path=rel,
                    )
                )
    return findings


def check_unregistered_synced_files(
    root: Path,
    manifests: dict[str, SourceManifest],
    identity_index: dict[str, Path],
) -> list[Finding]:
    """Files with identity headers but no matching manifest."""
    findings: list[Finding] = []
    for cid, rel_path in identity_index.items():
        if cid not in manifests:
            findings.append(
                Finding(
                    check="unregistered_synced_files",
                    severity=Severity.DRIFT,
                    message=f"File has identity header for '{cid}' but no manifest exists",
                    canonical_id=cid,
                    knowledge_path=normalize_path(rel_path),
                )
            )
    return findings


def check_db_source_consistency(
    root: Path,
    manifests: dict[str, SourceManifest],
) -> list[Finding]:
    """Check DB source rows against manifests."""
    findings: list[Finding] = []
    db_sources = _load_db_sync_progress(root)
    for cid in db_sources:
        if cid not in manifests:
            findings.append(
                Finding(
                    check="db_source_consistency",
                    severity=Severity.DRIFT,
                    message="DB row has no matching manifest",
                    canonical_id=cid,
                )
            )
    return findings


def check_path_normalization(
    root: Path,
    manifests: dict[str, SourceManifest],
) -> list[Finding]:
    """Check manifest paths for backslashes."""
    findings: list[Finding] = []
    for cid, m in manifests.items():
        for field_name, value in [("materialized_path", m.materialized_path), ("target_path", m.target_path)]:
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


# ---------------------------------------------------------------------------
# Step 2: Regen/insight consistency checks
# ---------------------------------------------------------------------------


def check_orphan_insights(root: Path) -> list[Finding]:
    """Walk insights/ recursively for dirs with no matching knowledge/ counterpart."""
    findings: list[Finding] = []
    insights_root = root / "insights"
    knowledge_root = root / "knowledge"
    if not insights_root.is_dir():
        return findings

    # Collect all orphan insight dirs, skipping children of already-orphaned parents
    orphan_prefixes: list[str] = []

    def _walk(directory: Path, prefix: str) -> None:
        for child in sorted(directory.iterdir()):
            if (
                not child.is_dir()
                or child.name.startswith("_")
                or child.name.startswith(".")
                or child.name in INSIGHT_ARTIFACT_DIRS
            ):
                continue
            rel = f"{prefix}/{child.name}" if prefix else child.name

            # Skip if a parent is already orphaned (will be cleaned as part of parent)
            if any(rel.startswith(op + "/") for op in orphan_prefixes):
                continue

            kdir = knowledge_root / rel
            if not kdir.is_dir():
                orphan_prefixes.append(rel)
                findings.append(
                    Finding(
                        check="orphan_insights",
                        severity=Severity.DRIFT,
                        message=f"Orphan insights dir: insights/{rel}/",
                        knowledge_path=rel,
                    )
                )
            else:
                # Not orphaned — recurse to check children
                _walk(child, rel)

    _walk(insights_root, "")
    return findings


def check_orphan_insight_state_rows(root: Path) -> list[Finding]:
    """Regen state (regen_locks/sidecars) where the knowledge dir doesn't exist."""
    findings: list[Finding] = []
    states = load_all_insight_states(root)
    knowledge_root = root / "knowledge"
    for istate in states:
        kp = istate.knowledge_path
        kdir = knowledge_root / kp if kp else knowledge_root
        if not kdir.is_dir():
            findings.append(
                Finding(
                    check="orphan_insight_state_rows",
                    severity=Severity.DRIFT,
                    message=f"Regen state for non-existent dir: '{kp}'",
                    knowledge_path=kp,
                )
            )
    return findings


def check_summaries_without_db_rows(root: Path) -> list[Finding]:
    """summary.md files with no matching regen state (regen_locks/sidecars)."""
    findings: list[Finding] = []
    insights_root = root / "insights"
    if not insights_root.is_dir():
        return findings

    # Collect all regen state paths
    states = load_all_insight_states(root)
    state_paths = {s.knowledge_path for s in states}

    for summary_path in insights_root.rglob("summary.md"):
        rel = summary_path.parent.relative_to(insights_root)
        kp = normalize_path(rel)
        if kp.startswith("_"):
            continue
        if kp not in state_paths:
            findings.append(
                Finding(
                    check="summaries_without_db_rows",
                    severity=Severity.WOULD_TRIGGER_REGEN,
                    message=f"Summary exists but no regen state: '{kp}'",
                    knowledge_path=kp,
                )
            )
    return findings


def check_stale_summaries(root: Path) -> list[Finding]:
    """summary.md for deleted knowledge dirs."""
    findings: list[Finding] = []
    insights_root = root / "insights"
    knowledge_root = root / "knowledge"
    if not insights_root.is_dir():
        return findings

    for summary_path in insights_root.rglob("summary.md"):
        rel = summary_path.parent.relative_to(insights_root)
        kp = normalize_path(rel)
        if kp.startswith("_"):
            continue
        kdir = knowledge_root / kp if kp else knowledge_root
        if not kdir.is_dir():
            findings.append(
                Finding(
                    check="stale_summaries",
                    severity=Severity.DRIFT,
                    message=f"Summary for deleted knowledge dir: '{kp}'",
                    knowledge_path=kp,
                )
            )
    return findings


def check_regen_change_detection(root: Path) -> list[Finding]:
    """Use classify_folder_change() to detect what regen work would happen."""
    from brain_sync.regen import classify_folder_change

    findings: list[Finding] = []
    states = load_all_insight_states(root)
    for istate in states:
        kp = istate.knowledge_path
        kdir = (root / "knowledge" / kp) if kp else (root / "knowledge")
        if not kdir.is_dir():
            continue  # handled by orphan_insight_state_rows
        change, _, _ = classify_folder_change(root, kp)
        if change.change_type != "none":
            if change.structural:
                # Structure-only change — informational
                findings.append(
                    Finding(
                        check="regen_change_detection",
                        severity=Severity.WOULD_TRIGGER_REGEN,
                        message=f"Structure-only change detected in '{kp}'",
                        knowledge_path=kp,
                    )
                )
            else:
                findings.append(
                    Finding(
                        check="regen_change_detection",
                        severity=Severity.WOULD_TRIGGER_REGEN,
                        message=f"Content change detected in '{kp}'",
                        knowledge_path=kp,
                    )
                )
    return findings


def check_db_path_normalization(root: Path) -> list[Finding]:
    """Check regen_locks paths for bad values."""
    findings: list[Finding] = []

    states = load_all_insight_states(root)
    for istate in states:
        kp = istate.knowledge_path
        if kp and ("\\" in kp or kp.startswith("/") or ".." in kp.split("/")):
            findings.append(
                Finding(
                    check="db_path_normalization",
                    severity=Severity.DRIFT,
                    message=f"Bad regen_locks path: '{kp}'",
                    knowledge_path=kp,
                )
            )
    return findings


# ---------------------------------------------------------------------------
# Step 3: Sidecar checks
# ---------------------------------------------------------------------------


def check_missing_sidecars(root: Path) -> list[Finding]:
    """For every insights/**/summary.md, verify a sibling .regen-meta.json exists and is valid."""
    findings: list[Finding] = []
    insights_root = root / "insights"
    if not insights_root.is_dir():
        return findings

    for summary_path in insights_root.rglob("summary.md"):
        rel = summary_path.parent.relative_to(insights_root)
        kp = normalize_path(rel)
        if kp.startswith("_"):
            continue

        meta = read_regen_meta(summary_path.parent)
        if meta is None:
            # Distinguish between missing and malformed
            sidecar_path = summary_path.parent / ".regen-meta.json"
            if sidecar_path.exists():
                findings.append(
                    Finding(
                        check="missing_sidecars",
                        severity=Severity.CORRUPTION,
                        message=f"Malformed sidecar for '{kp}'",
                        knowledge_path=kp,
                    )
                )
            else:
                findings.append(
                    Finding(
                        check="missing_sidecars",
                        severity=Severity.WOULD_TRIGGER_REGEN,
                        message=f"Missing sidecar for '{kp}' (needs regen)",
                        knowledge_path=kp,
                    )
                )
    return findings


def check_sidecar_integrity(root: Path) -> list[Finding]:
    """Verify all sidecars have a corresponding regen_locks row."""
    from brain_sync.state import _connect

    findings: list[Finding] = []
    insights_root = root / "insights"
    sidecars = read_all_regen_meta(insights_root)

    # Read regen_locks paths directly (not via load_all_insight_states which merges sidecars)
    conn = _connect(root)
    try:
        lock_paths = {r[0] for r in conn.execute("SELECT knowledge_path FROM regen_locks").fetchall()}
    finally:
        conn.close()

    for kp in sidecars:
        if kp not in lock_paths:
            findings.append(
                Finding(
                    check="sidecar_integrity",
                    severity=Severity.DRIFT,
                    message=f"Sidecar exists but no regen state for '{kp}'",
                    knowledge_path=kp,
                )
            )
    return findings


# ---------------------------------------------------------------------------
# Step 4: Main functions
# ---------------------------------------------------------------------------


def doctor(root: Path | None = None, *, fix: bool = False) -> DoctorResult:
    """Run all consistency checks. If fix=True, repair DRIFT findings."""
    root = _require_root(root)
    knowledge_root = root / "knowledge"

    manifests = read_all_source_manifests(root)
    identity_index = _build_identity_index(knowledge_root)

    all_findings: list[Finding] = []

    # Source checks
    all_findings.extend(check_version_json(root))
    all_findings.extend(check_manifest_file_match(root, manifests, knowledge_root, identity_index))
    all_findings.extend(check_identity_headers(root, manifests, knowledge_root, identity_index))
    all_findings.extend(check_orphan_attachments(root, manifests, knowledge_root))
    all_findings.extend(check_unregistered_synced_files(root, manifests, identity_index))
    all_findings.extend(check_db_source_consistency(root, manifests))
    all_findings.extend(check_path_normalization(root, manifests))

    # Regen checks
    all_findings.extend(check_orphan_insights(root))
    all_findings.extend(check_orphan_insight_state_rows(root))
    all_findings.extend(check_summaries_without_db_rows(root))
    all_findings.extend(check_stale_summaries(root))
    all_findings.extend(check_regen_change_detection(root))
    all_findings.extend(check_db_path_normalization(root))

    # Sidecar checks
    all_findings.extend(check_missing_sidecars(root))
    all_findings.extend(check_sidecar_integrity(root))

    if fix:
        _apply_fixes(root, all_findings, manifests, knowledge_root, identity_index)

    return DoctorResult(findings=all_findings, fix_mode=fix)


def _apply_fixes(
    root: Path,
    findings: list[Finding],
    manifests: dict[str, SourceManifest],
    knowledge_root: Path,
    identity_index: dict[str, Path],
) -> None:
    """Apply repairs for DRIFT and fixable CORRUPTION findings."""
    for f in findings:
        if f.severity not in (Severity.DRIFT, Severity.CORRUPTION):
            continue

        try:
            if f.check == "manifest_file_match" and f.canonical_id:
                # Update stale materialized_path
                cid = f.canonical_id
                new_path = identity_index.get(cid)
                if new_path is None:
                    found = rediscover_local_path(knowledge_root, cid)
                    if found is not None:
                        new_path = found  # already relative to knowledge_root
                if new_path is not None:
                    update_manifest_materialized_path(root, cid, normalize_path(new_path))
                    f.fix_applied = True
                    log.info("Fixed stale materialized_path for %s", cid)

            elif f.check == "identity_headers" and f.canonical_id:
                cid = f.canonical_id
                m = manifests.get(cid)
                if m and "Missing" in f.message:
                    # Find the file
                    file_path = knowledge_root / m.materialized_path if m.materialized_path else None
                    if file_path and not file_path.is_file() and cid in identity_index:
                        file_path = knowledge_root / identity_index[cid]
                    if file_path and file_path.is_file():
                        content = file_path.read_text(encoding="utf-8")
                        content = prepend_managed_header(cid, content)
                        file_path.write_text(content, encoding="utf-8")
                        f.fix_applied = True
                        log.info("Restored identity header for %s", cid)

            elif f.check == "orphan_attachments" and f.knowledge_path:
                orphan_dir = knowledge_root / f.knowledge_path
                if orphan_dir.is_dir():
                    shutil.rmtree(orphan_dir)
                    f.fix_applied = True
                    log.info("Removed orphan attachment dir: %s", f.knowledge_path)

            elif f.check == "db_source_consistency" and f.canonical_id:
                delete_source(root, f.canonical_id)
                f.fix_applied = True
                log.info("Pruned orphan DB source row: %s", f.canonical_id)

            elif f.check == "path_normalization" and f.canonical_id:
                m = manifests.get(f.canonical_id)
                if m:
                    if "\\" in m.materialized_path:
                        m.materialized_path = normalize_path(m.materialized_path)
                    if "\\" in m.target_path:
                        m.target_path = normalize_path(m.target_path)
                    write_source_manifest(root, m)
                    f.fix_applied = True
                    log.info("Normalized paths in manifest for %s", f.canonical_id)

            elif f.check == "orphan_insights" and f.knowledge_path:
                orphan_dir = root / "insights" / f.knowledge_path
                if orphan_dir.is_dir():
                    clean_insights_tree(orphan_dir)
                delete_insight_state(root, f.knowledge_path)
                f.fix_applied = True
                log.info("Removed orphan insights dir: insights/%s/", f.knowledge_path)

            elif f.check == "orphan_insight_state_rows" and f.knowledge_path is not None:
                delete_insight_state(root, f.knowledge_path)
                f.fix_applied = True
                log.info("Pruned orphan regen state: %s", f.knowledge_path)

            elif f.check == "stale_summaries" and f.knowledge_path:
                stale_dir = root / "insights" / f.knowledge_path
                if stale_dir.is_dir():
                    clean_insights_tree(stale_dir)
                f.fix_applied = True
                log.info("Removed stale insights dir: insights/%s/", f.knowledge_path)

            elif f.check == "db_path_normalization" and f.knowledge_path:
                # Fix regen_locks path
                from brain_sync.state import load_insight_state

                istate = load_insight_state(root, f.knowledge_path)
                if istate:
                    istate.knowledge_path = normalize_path(istate.knowledge_path)
                    save_insight_state(root, istate)
                    f.fix_applied = True
                    log.info("Normalized regen_locks path: %s", f.knowledge_path)

            elif f.check == "version_json":
                version_path = root / MANIFEST_VERSION_FILE
                version_path.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_bytes(version_path, json.dumps({"manifest_version": 1}).encode("utf-8"))
                f.fix_applied = True
                log.info("Restored %s", MANIFEST_VERSION_FILE)

        except Exception:
            log.exception("Failed to fix %s finding for %s", f.check, f.canonical_id or f.knowledge_path)


def rebuild_db(root: Path | None = None) -> DoctorResult:
    """Rebuild source sync progress from manifests, preserving regen state."""
    from brain_sync.state import SyncState, _db_path

    root = _require_root(root)

    # 1. Export regen state (hashes from sidecars, lifecycle from regen_locks)
    exported_states = load_all_insight_states(root)
    log.info("Exported %d regen states for preservation", len(exported_states))

    # 2. Delete DB files
    db = _db_path(root)
    for suffix in ("", "-wal", "-shm"):
        p = db.parent / (db.name + suffix)
        if p.exists():
            p.unlink()
            log.info("Deleted %s", p.name)

    # 3. Create fresh DB
    conn = _connect(root)
    conn.close()
    log.info("Created fresh DB with current schema")

    # 4. Restore regen state with lifecycle reset
    for istate in exported_states:
        restored = InsightState(
            knowledge_path=istate.knowledge_path,
            content_hash=istate.content_hash,
            summary_hash=istate.summary_hash,
            structure_hash=istate.structure_hash,
            last_regen_utc=istate.last_regen_utc,
            regen_status="idle",
            owner_id=None,
            regen_started_utc=None,
            error_reason=None,
        )
        save_insight_state(root, restored)
    log.info("Restored %d regen states (lifecycle reset to idle)", len(exported_states))

    # 5. Seed source sync progress from manifests
    manifests = read_all_source_manifests(root)
    state = SyncState()
    for cid, m in manifests.items():
        if m.status != "active":
            continue
        target_path = normalize_path(m.target_path) if m.target_path else ""
        ss = _seed_from_hint(root, m, target_path)
        state.sources[cid] = ss

    if state.sources:
        save_state(root, state)
    log.info("Seeded %d source rows from manifests", len(state.sources))

    log.warning(
        "Cache/telemetry tables (documents, relationships, token_events, daemon_status) "
        "were dropped. Discovery caches will be cold. Telemetry history is gone."
    )

    # 6. Run check-only doctor and return
    return doctor(root, fix=False)


def deregister_missing(root: Path | None = None) -> DoctorResult:
    """Finalize all missing-status sources immediately."""
    root = _require_root(root)
    manifests = read_all_source_manifests(root)
    findings: list[Finding] = []

    for cid, m in manifests.items():
        if m.status != "missing":
            continue
        delete_source_manifest(root, cid)
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
        log.info("Deregistered missing source: %s", cid)

    if not findings:
        findings.append(
            Finding(
                check="deregister_missing",
                severity=Severity.OK,
                message="No missing sources to deregister",
            )
        )

    return DoctorResult(findings=findings, fix_mode=True)


def adopt_baseline(root: Path | None = None) -> DoctorResult:
    """Record current summaries as regen baseline (migration from pre-sidecar versions).

    Walks knowledge/ bottom-up (leaves first) so parent content hashes incorporate
    child summary text correctly. For each folder with an existing summary.md,
    computes hashes using the same functions as classify_folder_change() and writes
    a sidecar + DB row.
    """
    import hashlib

    from brain_sync.fs_utils import find_all_content_paths, get_child_dirs, is_readable_file
    from brain_sync.regen import collect_child_summaries, compute_content_hash, compute_structure_hash

    root = _require_root(root)
    knowledge_root = root / "knowledge"
    insights_root = root / "insights"
    findings: list[Finding] = []

    # Discover eligible paths bottom-up (leaves first), then root ""
    content_paths = find_all_content_paths(knowledge_root)
    content_paths.append("")

    # Also discover insight paths with summaries that aren't in content_paths
    # (handles orphan detection for summaries with no matching knowledge dir)
    content_path_set = set(content_paths)
    if insights_root.is_dir():
        for summary in insights_root.rglob("summary.md"):
            rel = summary.parent.relative_to(insights_root)
            kp = normalize_path(rel)
            if kp.startswith("_"):
                continue
            if kp not in content_path_set:
                content_paths.append(kp)
                content_path_set.add(kp)

    # Load existing regen_locks paths for skip detection
    conn = _connect(root)
    try:
        lock_paths = {r[0] for r in conn.execute("SELECT knowledge_path FROM regen_locks").fetchall()}
    finally:
        conn.close()

    for kp in content_paths:
        knowledge_dir = knowledge_root / kp if kp else knowledge_root
        insights_dir = insights_root / kp if kp else insights_root
        summary_path = insights_dir / "summary.md"

        # Skip if no summary exists
        if not summary_path.exists():
            continue

        # Warn on orphan insight (summary exists but knowledge dir missing)
        if not knowledge_dir.is_dir():
            findings.append(
                Finding(
                    check="adopt_baseline",
                    severity=Severity.DRIFT,
                    message=f"Orphan insight (no knowledge dir): '{kp}'",
                    knowledge_path=kp,
                )
            )
            continue

        # Check existing sidecar state
        existing_meta = read_regen_meta(insights_dir)
        if existing_meta is not None and existing_meta.content_hash is not None:
            # Valid sidecar exists
            if kp in lock_paths:
                # Fully baselined — skip
                findings.append(
                    Finding(
                        check="adopt_baseline",
                        severity=Severity.OK,
                        message=f"Already baselined: '{kp}'",
                        knowledge_path=kp,
                    )
                )
                continue
            else:
                # Sidecar exists but no DB row — ensure lifecycle row
                summary_text = summary_path.read_text(encoding="utf-8")
                summary_hash = hashlib.sha256(summary_text.encode("utf-8")).hexdigest()
                save_insight_state(
                    root,
                    InsightState(
                        knowledge_path=kp,
                        content_hash=existing_meta.content_hash,
                        summary_hash=summary_hash,
                        structure_hash=existing_meta.structure_hash,
                        last_regen_utc=None,
                        regen_status="idle",
                    ),
                )
                findings.append(
                    Finding(
                        check="adopt_baseline",
                        severity=Severity.OK,
                        message=f"Ensured lifecycle row for existing sidecar: '{kp}'",
                        knowledge_path=kp,
                        fix_applied=True,
                    )
                )
                continue

        # Compute hashes using the same functions as regen
        child_dirs = get_child_dirs(knowledge_dir)
        has_direct_files = any(is_readable_file(p) for p in knowledge_dir.iterdir())
        child_summaries = collect_child_summaries(root, kp, child_dirs)
        content_hash = compute_content_hash(child_summaries, knowledge_dir, has_direct_files)
        structure_hash = compute_structure_hash(child_dirs, knowledge_dir, has_direct_files)
        summary_text = summary_path.read_text(encoding="utf-8")
        summary_hash = hashlib.sha256(summary_text.encode("utf-8")).hexdigest()

        # Write via save_insight_state (writes sidecar + DB row)
        save_insight_state(
            root,
            InsightState(
                knowledge_path=kp,
                content_hash=content_hash,
                summary_hash=summary_hash,
                structure_hash=structure_hash,
                last_regen_utc=None,
                regen_status="idle",
            ),
        )
        findings.append(
            Finding(
                check="adopt_baseline",
                severity=Severity.OK,
                message=f"Adopted baseline for '{kp}'",
                knowledge_path=kp,
                fix_applied=True,
            )
        )
        log.info("Adopted baseline for '%s'", kp or "(root)")

    if not findings:
        findings.append(
            Finding(
                check="adopt_baseline",
                severity=Severity.OK,
                message="No summaries found to adopt",
            )
        )

    return DoctorResult(findings=findings, fix_mode=True)
