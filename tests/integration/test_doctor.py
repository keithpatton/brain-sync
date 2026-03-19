"""Integration tests for doctor against the Brain Format 1.1 contract."""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from brain_sync.application.doctor import Severity, deregister_missing, doctor, rebuild_db
from brain_sync.application.insights import InsightState, save_insight_state
from brain_sync.application.source_state import load_state
from brain_sync.application.sources import add_source
from brain_sync.brain.layout import area_attachments_root, area_insights_dir, area_journal_dir, area_summary_path
from brain_sync.brain.managed_markdown import prepend_managed_header
from brain_sync.brain.manifest import read_all_source_manifests, read_source_manifest, write_source_manifest
from brain_sync.brain.sidecar import SIDECAR_FILENAME, RegenMeta, read_regen_meta, write_regen_meta
from brain_sync.runtime.repository import (
    _connect,
    load_child_discovery_request,
    load_sync_progress,
    save_child_discovery_request,
)

pytestmark = pytest.mark.integration

TEST_URL = "https://acme.atlassian.net/wiki/spaces/ENG/pages/12345/Test-Page"


@pytest.fixture
def brain(tmp_path: Path) -> Path:
    root = tmp_path / "brain"
    root.mkdir()
    from brain_sync.application.init import init_brain

    init_brain(root)
    return root


def _write_knowledge(root: Path, rel: str, content: str) -> Path:
    path = root / "knowledge" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _write_insight_summary(root: Path, kpath: str, content: str = "# Summary\nContent.") -> Path:
    path = area_summary_path(root, kpath)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _add_synced_source(root: Path, cid: str = "confluence:12345", target: str = "project") -> None:
    add_source(root=root, url=TEST_URL, target_path=target)
    content = prepend_managed_header(cid, "# Test Page\nContent here.")
    _write_knowledge(root, f"{target}/c12345-test-page.md", content)
    manifest = read_source_manifest(root, cid)
    assert manifest is not None
    manifest.knowledge_state = "materialized"
    manifest.knowledge_path = f"{target}/c12345-test-page.md"
    manifest.content_hash = "sha256:abc"
    manifest.remote_fingerprint = "rev-1"
    manifest.materialized_utc = "2026-03-19T08:00:00+00:00"
    write_source_manifest(root, manifest)


class TestDoctorFixDrift:
    def test_moved_file_fix(self, brain: Path) -> None:
        _add_synced_source(brain)

        src = brain / "knowledge" / "project" / "c12345-test-page.md"
        dst = brain / "knowledge" / "other"
        dst.mkdir(parents=True)
        shutil.move(str(src), str(dst / "c12345-test-page.md"))

        result = doctor(brain)
        drift = [f for f in result.findings if f.severity == Severity.DRIFT and f.check == "manifest_file_match"]
        assert drift

        fixed = doctor(brain, fix=True)
        assert any(f.fix_applied for f in fixed.findings if f.check == "manifest_file_match")

    def test_strip_header_fix(self, brain: Path) -> None:
        _add_synced_source(brain)

        file_path = brain / "knowledge" / "project" / "c12345-test-page.md"
        file_path.write_text("# Test Page\nContent without header.", encoding="utf-8")

        result = doctor(brain)
        assert any(f.severity == Severity.DRIFT and f.check == "identity_headers" for f in result.findings)

        fixed = doctor(brain, fix=True)
        assert any(f.fix_applied and f.check == "identity_headers" for f in fixed.findings)
        content = file_path.read_text(encoding="utf-8")
        assert "brain_sync_canonical_id: confluence:12345" in content


class TestDoctorRebuildDb:
    def test_rebuild_preserves_portable_source_truth(self, brain: Path) -> None:
        _add_synced_source(brain)
        manifest_before = read_source_manifest(brain, "confluence:12345")
        assert manifest_before is not None

        state = load_state(brain)
        state.sources["confluence:12345"].next_check_utc = "2026-03-19T11:00:00+00:00"
        from brain_sync.application.source_state import save_state

        save_state(brain, state)

        result = rebuild_db(brain)
        assert result.corruption_count == 0

        manifest_after = read_source_manifest(brain, "confluence:12345")
        assert manifest_after is not None
        assert manifest_after.knowledge_path == manifest_before.knowledge_path
        assert manifest_after.knowledge_state == "materialized"
        assert manifest_after.remote_fingerprint == manifest_before.remote_fingerprint

    def test_rebuild_does_not_rewrite_unchanged_portable_insight_state(self, brain: Path) -> None:
        (brain / "knowledge" / "project").mkdir(parents=True, exist_ok=True)
        save_insight_state(
            brain,
            InsightState(
                knowledge_path="project",
                content_hash="abc123",
                summary_hash="def456",
                structure_hash="ghi789",
                last_regen_utc="2026-03-10T00:00:00",
            ),
        )

        with patch(
            "brain_sync.brain.sidecar.write_regen_meta",
            side_effect=AssertionError("rebuild-db should not rewrite portable insight-state"),
        ):
            rebuild_db(brain)

    def test_rebuild_resets_runtime_db_to_supported_tables(self, brain: Path) -> None:
        conn = _connect(brain)
        try:
            conn.execute("CREATE TABLE scratch (id INTEGER PRIMARY KEY, note TEXT)")
            conn.execute("INSERT INTO scratch (note) VALUES ('stale')")
            conn.commit()
        finally:
            conn.close()

        rebuild_db(brain)

        conn = _connect(brain)
        try:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            assert "scratch" not in tables
            assert {"meta", "sync_polling", "regen_locks", "token_events"} <= tables
        finally:
            conn.close()

    def test_cross_machine_runtime_rebuild_keeps_shared_manifest_truth(self, brain: Path) -> None:
        _add_synced_source(brain)
        rebuild_db(brain)
        progress = load_sync_progress(brain)
        assert "confluence:12345" not in progress or progress["confluence:12345"].next_check_utc is None
        manifest = read_source_manifest(brain, "confluence:12345")
        assert manifest is not None
        assert manifest.knowledge_state == "materialized"


class TestDoctorMissingLifecycle:
    def test_deregisters_missing_sources(self, brain: Path) -> None:
        _add_synced_source(brain)
        attachment_dir = area_attachments_root(brain, "project") / "c12345"
        attachment_dir.mkdir(parents=True)
        (attachment_dir / "a789.png").write_bytes(b"data")
        save_child_discovery_request(brain, "confluence:12345", fetch_children=True, child_path="children")
        manifest = read_source_manifest(brain, "confluence:12345")
        assert manifest is not None
        manifest.knowledge_state = "missing"
        manifest.missing_since_utc = "2026-03-10T00:00:00+00:00"
        write_source_manifest(brain, manifest)

        result = deregister_missing(brain)
        assert any(f.canonical_id == "confluence:12345" for f in result.findings)
        assert "confluence:12345" not in read_all_source_manifests(brain)
        assert "confluence:12345" not in load_sync_progress(brain)
        assert load_child_discovery_request(brain, "confluence:12345") is None
        assert not attachment_dir.exists()


class TestDoctorOperationalChecks:
    def test_fix_orphan_attachments(self, brain: Path) -> None:
        orphan = area_attachments_root(brain, "area") / "c999"
        orphan.mkdir(parents=True)
        (orphan / "file.png").write_bytes(b"data")

        result = doctor(brain, fix=True)
        assert any(f.fix_applied and f.check == "orphan_attachments" for f in result.findings)
        assert not orphan.exists()

    def test_fix_orphan_db_source_row(self, brain: Path) -> None:
        conn = _connect(brain)
        try:
            conn.execute(
                "INSERT INTO sync_polling (canonical_id, current_interval_secs) VALUES (?, ?)",
                ("confluence:999", 1800),
            )
            conn.commit()
        finally:
            conn.close()

        result = doctor(brain, fix=True)
        assert any(f.fix_applied and f.check == "db_source_consistency" for f in result.findings)

    def test_legacy_journal_layout_reported_as_drift_and_healed(self, brain: Path) -> None:
        (brain / "knowledge" / "area").mkdir(parents=True)
        legacy = area_insights_dir(brain, "area") / "journal" / "2026-03" / "2026-03-15.md"
        legacy.parent.mkdir(parents=True)
        legacy.write_text("## 09:00\n\nLegacy entry.", encoding="utf-8")

        result = doctor(brain)
        assert any(f.check == "legacy_journal_layout" and f.severity == Severity.DRIFT for f in result.findings)

        fixed = doctor(brain, fix=True)
        assert any(f.fix_applied and f.check == "legacy_journal_layout" for f in fixed.findings)
        healed = area_journal_dir(brain, "area") / "2026-03" / "2026-03-15.md"
        assert healed.exists()

    def test_modified_knowledge_reports_would_regen(self, brain: Path) -> None:
        (brain / "knowledge" / "project").mkdir(parents=True)
        _write_knowledge(brain, "project/doc.md", "original content")
        _write_insight_summary(brain, "project")
        save_insight_state(
            brain,
            InsightState(
                knowledge_path="project",
                content_hash="old_hash",
                structure_hash="old_struct",
            ),
        )

        result = doctor(brain)
        assert any(f.severity == Severity.WOULD_TRIGGER_REGEN for f in result.findings)

    def test_sidecar_checks_still_work(self, brain: Path) -> None:
        (brain / "knowledge" / "project").mkdir(parents=True)
        _write_knowledge(brain, "project/doc.md", "content")
        _write_insight_summary(brain, "project")
        save_insight_state(brain, InsightState(knowledge_path="project", content_hash="abc", structure_hash="st1"))

        result = doctor(brain)
        assert not [f for f in result.findings if f.check == "missing_sidecars"]

        write_regen_meta(area_insights_dir(brain, "project"), RegenMeta(content_hash="WRONG", structure_hash="st1"))
        regen = doctor(brain)
        assert any(f.check == "regen_change_detection" and f.knowledge_path == "project" for f in regen.findings)

        (area_insights_dir(brain, "project") / SIDECAR_FILENAME).write_text("not json{{{", encoding="utf-8")
        corrupt = doctor(brain)
        assert any(f.check == "missing_sidecars" and f.severity == Severity.CORRUPTION for f in corrupt.findings)


class TestAdoptBaseline:
    def test_adopts_project_summary(self, brain: Path) -> None:
        project = brain / "knowledge" / "project"
        project.mkdir(parents=True)
        (project / "notes.md").write_text("# Notes\n", encoding="utf-8")
        _write_insight_summary(brain, "project")

        from brain_sync.application.doctor import adopt_baseline

        result = adopt_baseline(brain)
        adopted = next(f for f in result.findings if f.knowledge_path == "project")
        assert adopted.fix_applied is True
        meta = read_regen_meta(project / ".brain-sync" / "insights")
        assert meta is not None
        assert meta.content_hash is not None
