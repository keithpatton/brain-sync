from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest

from brain_sync.application.doctor import (
    Severity,
    _build_identity_index,
    adopt_baseline,
    check_db_path_normalization,
    check_db_source_consistency,
    check_identity_headers,
    check_manifest_file_match,
    check_missing_sidecars,
    check_orphan_attachments,
    check_orphan_insight_state_rows,
    check_orphan_insights,
    check_path_normalization,
    check_regen_change_detection,
    check_sidecar_integrity,
    check_summaries_without_db_rows,
    check_unregistered_synced_files,
    check_version_json,
    doctor,
)
from brain_sync.application.insights import InsightState, save_insight_state
from brain_sync.application.source_state import SourceState, SyncState, save_state
from brain_sync.brain.fileops import atomic_write_bytes
from brain_sync.brain.manifest import MANIFEST_VERSION, SourceManifest
from brain_sync.brain.sidecar import SIDECAR_FILENAME, RegenMeta, read_regen_meta, write_regen_meta
from brain_sync.runtime.repository import _connect
from brain_sync.sync.pipeline import prepend_managed_header

pytestmark = pytest.mark.unit


def _long_relative_path(root: Path, filename: str, *, min_length: int = 280) -> Path:
    parts: list[str] = []
    index = 0
    while len(str(root / Path(*parts) / filename)) <= min_length:
        parts.append(f"segment-{index:02d}-with-extra-length-for-windows")
        index += 1
    return Path(*parts) / filename


@pytest.fixture
def brain(tmp_path: Path) -> Path:
    root = tmp_path / "brain"
    (root / "knowledge").mkdir(parents=True)
    (root / ".brain-sync" / "sources").mkdir(parents=True)
    (root / ".brain-sync" / "brain.json").write_text('{"version": 1}\n', encoding="utf-8")
    conn = _connect(root)
    conn.close()
    return root


def _make_manifest(cid: str, **kwargs: Any) -> SourceManifest:
    knowledge_state = cast(str, kwargs.get("knowledge_state", "materialized"))
    manifest_kwargs: dict[str, Any] = {
        "version": MANIFEST_VERSION,
        "canonical_id": cid,
        "source_url": cast(
            str, kwargs.get("source_url", f"https://acme.atlassian.net/wiki/spaces/ENG/pages/{cid.split(':')[1]}")
        ),
        "source_type": cast(str, kwargs.get("source_type", "confluence")),
        "knowledge_path": cast(str, kwargs.get("knowledge_path", "area/c123-doc.md")),
        "sync_attachments": cast(bool, kwargs.get("sync_attachments", False)),
        "knowledge_state": knowledge_state,
    }
    if knowledge_state in {"materialized", "stale"}:
        manifest_kwargs.update(
            {
                "content_hash": kwargs.get("content_hash", "sha256:abc"),
                "remote_fingerprint": kwargs.get("remote_fingerprint", "rev-1"),
                "materialized_utc": kwargs.get("materialized_utc", "2026-03-19T09:00:00+00:00"),
            }
        )
    elif knowledge_state == "missing":
        manifest_kwargs.update(
            {
                "missing_since_utc": kwargs.get("missing_since_utc", "2026-03-19T10:00:00+00:00"),
                "content_hash": kwargs.get("content_hash", "sha256:abc"),
                "remote_fingerprint": kwargs.get("remote_fingerprint", "rev-1"),
                "materialized_utc": kwargs.get("materialized_utc", "2026-03-19T09:00:00+00:00"),
            }
        )
    return SourceManifest(**manifest_kwargs)


def _write_knowledge_file(root: Path, rel_path: str, canonical_id: str | None = None) -> Path:
    path = root / "knowledge" / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "# Doc\n"
    if canonical_id:
        content = prepend_managed_header(
            canonical_id, content, source_type="confluence", source_url="https://example.com"
        )
    path.write_text(content, encoding="utf-8")
    return path


def _write_summary(root: Path, knowledge_path: str, content: str = "# Summary\n") -> Path:
    if knowledge_path:
        path = root / "knowledge" / knowledge_path / ".brain-sync" / "insights" / "summary.md"
    else:
        path = root / "knowledge" / ".brain-sync" / "insights" / "summary.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


class TestBrainManifest:
    def test_valid(self, brain: Path) -> None:
        findings = check_version_json(brain)
        assert findings[0].severity == Severity.OK

    def test_missing(self, brain: Path) -> None:
        (brain / ".brain-sync" / "brain.json").unlink()
        findings = check_version_json(brain)
        assert findings[0].severity == Severity.CORRUPTION

    def test_invalid(self, brain: Path) -> None:
        (brain / ".brain-sync" / "brain.json").write_text("{bad", encoding="utf-8")
        findings = check_version_json(brain)
        assert findings[0].severity == Severity.CORRUPTION


class TestManifestChecks:
    def test_manifest_file_match_detects_move(self, brain: Path) -> None:
        _write_knowledge_file(brain, "other/c123-doc.md", "confluence:123")
        manifests = {"confluence:123": _make_manifest("confluence:123", knowledge_path="area/c123-doc.md")}
        findings = check_manifest_file_match(
            brain, manifests, brain / "knowledge", _build_identity_index(brain / "knowledge")
        )
        assert findings[0].severity == Severity.DRIFT

    def test_identity_headers_detect_missing_frontmatter(self, brain: Path) -> None:
        _write_knowledge_file(brain, "area/c123-doc.md")
        manifests = {"confluence:123": _make_manifest("confluence:123")}
        findings = check_identity_headers(brain, manifests, brain / "knowledge", {})
        assert findings[0].severity == Severity.DRIFT

    def test_unregistered_synced_file_detected(self, brain: Path) -> None:
        findings = check_unregistered_synced_files(brain, {}, {"confluence:123": Path("area/c123-doc.md")})
        assert findings[0].severity == Severity.DRIFT

    def test_db_source_consistency_detects_orphan_runtime_row(self, brain: Path) -> None:
        state = SyncState()
        state.sources["confluence:999"] = SourceState(
            canonical_id="confluence:999",
            source_url="https://example.com/999",
            source_type="confluence",
            next_check_utc="2026-03-19T10:00:00+00:00",
        )
        save_state(brain, state)
        findings = check_db_source_consistency(brain, {"confluence:123": _make_manifest("confluence:123")})
        assert findings[0].severity == Severity.DRIFT

    def test_path_normalization_detects_backslashes(self, brain: Path) -> None:
        manifest = _make_manifest("confluence:123")
        manifest.knowledge_path = "area\\c123-doc.md"
        findings = check_path_normalization(
            brain,
            {"confluence:123": manifest},
        )
        assert findings[0].severity == Severity.DRIFT

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
    def test_manifest_file_match_accepts_existing_overlong_path(self, brain: Path) -> None:
        rel = _long_relative_path(brain / "knowledge", "c123-doc.md")
        atomic_write_bytes(brain / "knowledge" / rel, b"# Doc\n")

        findings = check_manifest_file_match(
            brain,
            {"confluence:123": _make_manifest("confluence:123", knowledge_path=str(rel).replace("\\", "/"))},
            brain / "knowledge",
            {},
        )

        assert findings[0].severity == Severity.OK


class TestManagedLayoutChecks:
    def test_orphan_attachment_dir_detected(self, brain: Path) -> None:
        orphan = brain / "knowledge" / "area" / ".brain-sync" / "attachments" / "c999"
        orphan.mkdir(parents=True)
        findings = check_orphan_attachments(
            brain, {"confluence:123": _make_manifest("confluence:123")}, brain / "knowledge"
        )
        assert findings[0].severity == Severity.DRIFT

    def test_top_level_legacy_insights_are_rejected(self, brain: Path) -> None:
        (brain / "insights").mkdir()
        findings = check_orphan_insights(brain)
        assert findings[0].severity == Severity.CORRUPTION

    def test_orphan_insight_state_row_detected(self, brain: Path) -> None:
        save_insight_state(brain, InsightState(knowledge_path="deleted"))
        findings = check_orphan_insight_state_rows(brain)
        assert findings[0].severity == Severity.DRIFT

    def test_summary_without_regen_state_would_trigger_regen(self, brain: Path) -> None:
        _write_summary(brain, "project")
        findings = check_summaries_without_db_rows(brain)
        assert findings[0].severity == Severity.WOULD_TRIGGER_REGEN

    def test_missing_sidecar_detected_next_to_colocated_summary(self, brain: Path) -> None:
        _write_summary(brain, "project")
        findings = check_missing_sidecars(brain)
        assert findings[0].severity == Severity.WOULD_TRIGGER_REGEN

    def test_malformed_sidecar_is_corruption(self, brain: Path) -> None:
        summary = _write_summary(brain, "project")
        (summary.parent / SIDECAR_FILENAME).write_text("{bad", encoding="utf-8")
        findings = check_missing_sidecars(brain)
        assert findings[0].severity == Severity.CORRUPTION

    def test_sidecar_integrity_detects_missing_regen_lock(self, brain: Path) -> None:
        summary = _write_summary(brain, "project")
        write_regen_meta(summary.parent, RegenMeta(content_hash="abc"))
        findings = check_sidecar_integrity(brain)
        assert findings[0].severity == Severity.DRIFT

    def test_db_path_normalization_detects_bad_path(self, brain: Path) -> None:
        conn = _connect(brain)
        try:
            conn.execute(
                "INSERT INTO regen_locks (knowledge_path, regen_status) VALUES (?, ?)",
                ("/project/area", "idle"),
            )
            conn.commit()
        finally:
            conn.close()
        findings = check_db_path_normalization(brain)
        assert findings[0].severity == Severity.DRIFT

    def test_regen_change_detection_reports_content_change(self, brain: Path) -> None:
        from brain_sync.regen import ChangeEvent

        (brain / "knowledge" / "project").mkdir(parents=True)
        save_insight_state(brain, InsightState(knowledge_path="project"))
        with patch(
            "brain_sync.regen.engine.classify_folder_change",
            return_value=(ChangeEvent(change_type="content", structural=False), "new", "structure"),
        ):
            findings = check_regen_change_detection(brain)
        assert findings[0].severity == Severity.WOULD_TRIGGER_REGEN


class TestDoctorFixes:
    def test_fix_restores_missing_brain_json(self, brain: Path) -> None:
        (brain / ".brain-sync" / "brain.json").unlink()
        result = doctor(brain, fix=True)
        finding = next(f for f in result.findings if f.check == "brain_manifest")
        assert finding.fix_applied is True
        assert json.loads((brain / ".brain-sync" / "brain.json").read_text(encoding="utf-8")) == {"version": 1}

    def test_fix_does_not_upgrade_legacy_layout(self, brain: Path) -> None:
        (brain / "insights").mkdir()
        result = doctor(brain, fix=True)
        assert result.findings[0].check == "unsupported_legacy_layout"
        assert result.findings[0].fix_applied is False

    def test_fix_logs_repository_exception_without_crashing(self, brain: Path) -> None:
        _write_knowledge_file(brain, "area/c123-doc.md")
        manifests = {"confluence:123": _make_manifest("confluence:123")}
        from brain_sync.brain.manifest import write_source_manifest

        write_source_manifest(brain, manifests["confluence:123"])

        with patch(
            "brain_sync.application.doctor.BrainRepository.rewrite_managed_identity",
            side_effect=RuntimeError("boom"),
        ):
            result = doctor(brain, fix=True)

        finding = next(f for f in result.findings if f.check == "identity_headers")
        assert finding.fix_applied is False


class TestAdoptBaseline:
    def test_adopts_project_summary(self, brain: Path) -> None:
        project = brain / "knowledge" / "project"
        project.mkdir(parents=True)
        (project / "notes.md").write_text("# Notes\n", encoding="utf-8")
        _write_summary(brain, "project")

        result = adopt_baseline(brain)

        adopted = next(f for f in result.findings if f.knowledge_path == "project")
        assert adopted.fix_applied is True
        meta = read_regen_meta(project / ".brain-sync" / "insights")
        assert meta is not None
        assert meta.content_hash is not None
