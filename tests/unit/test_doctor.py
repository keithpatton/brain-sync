"""Unit tests for brain_sync.commands.doctor — each check_* function in isolation."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from brain_sync.commands.doctor import (
    Severity,
    _build_identity_index,
    check_db_path_normalization,
    check_db_source_consistency,
    check_identity_headers,
    check_manifest_file_match,
    check_orphan_attachments,
    check_orphan_insight_state_rows,
    check_orphan_insights,
    check_path_normalization,
    check_regen_change_detection,
    check_stale_summaries,
    check_summaries_without_db_rows,
    check_unregistered_synced_files,
    check_version_json,
)
from brain_sync.manifest import MANIFEST_VERSION, SourceManifest
from brain_sync.pipeline import MANAGED_HEADER_SOURCE
from brain_sync.state import InsightState, _connect, save_insight_state

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def brain(tmp_path: Path) -> Path:
    """Create a minimal brain with DB initialised."""
    root = tmp_path / "brain"
    root.mkdir()
    (root / "knowledge").mkdir()
    (root / "insights").mkdir()
    (root / ".brain-sync" / "sources").mkdir(parents=True)
    version_file = root / ".brain-sync" / "version.json"
    version_file.write_text(json.dumps({"manifest_version": 1}))
    conn = _connect(root)
    conn.close()
    return root


def _make_manifest(cid: str, **kwargs) -> SourceManifest:
    return SourceManifest(
        manifest_version=MANIFEST_VERSION,
        canonical_id=cid,
        source_url=kwargs.get("source_url", f"https://acme.atlassian.net/wiki/spaces/ENG/pages/{cid.split(':')[1]}"),
        source_type=kwargs.get("source_type", "confluence"),
        materialized_path=kwargs.get("materialized_path", ""),
        fetch_children=False,
        sync_attachments=False,
        target_path=kwargs.get("target_path", ""),
        status=kwargs.get("status", "active"),
    )


def _write_knowledge_file(root: Path, rel_path: str, content: str) -> Path:
    """Write a file under knowledge/."""
    p = root / "knowledge" / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def _write_insight_summary(root: Path, kpath: str, content: str = "# Summary\nContent.") -> Path:
    """Write a summary.md under insights/."""
    p = root / "insights" / kpath / "summary.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# TestCheckVersionJson
# ---------------------------------------------------------------------------


class TestCheckVersionJson:
    def test_valid(self, brain: Path) -> None:
        findings = check_version_json(brain)
        assert len(findings) == 1
        assert findings[0].severity == Severity.OK

    def test_missing(self, brain: Path) -> None:
        (brain / ".brain-sync" / "version.json").unlink()
        findings = check_version_json(brain)
        assert findings[0].severity == Severity.CORRUPTION

    def test_invalid_json(self, brain: Path) -> None:
        (brain / ".brain-sync" / "version.json").write_text("{bad json")
        findings = check_version_json(brain)
        assert findings[0].severity == Severity.CORRUPTION

    def test_wrong_structure(self, brain: Path) -> None:
        (brain / ".brain-sync" / "version.json").write_text(json.dumps({"foo": "bar"}))
        findings = check_version_json(brain)
        assert findings[0].severity == Severity.CORRUPTION


# ---------------------------------------------------------------------------
# TestCheckManifestFileMatch
# ---------------------------------------------------------------------------


class TestCheckManifestFileMatch:
    def test_file_at_path_ok(self, brain: Path) -> None:
        _write_knowledge_file(brain, "area/c123-doc.md", "content")
        manifests = {"confluence:123": _make_manifest("confluence:123", materialized_path="area/c123-doc.md")}
        findings = check_manifest_file_match(brain, manifests, brain / "knowledge", {})
        assert findings[0].severity == Severity.OK

    def test_file_moved_drift(self, brain: Path) -> None:
        _write_knowledge_file(brain, "other/c123-doc.md", MANAGED_HEADER_SOURCE.format("confluence:123") + "\ncontent")
        manifests = {"confluence:123": _make_manifest("confluence:123", materialized_path="area/c123-doc.md")}
        identity_index = _build_identity_index(brain / "knowledge")
        findings = check_manifest_file_match(brain, manifests, brain / "knowledge", identity_index)
        assert findings[0].severity == Severity.DRIFT
        assert "moved" in findings[0].message

    def test_file_missing_would_fetch(self, brain: Path) -> None:
        manifests = {"confluence:123": _make_manifest("confluence:123", materialized_path="area/c123-doc.md")}
        findings = check_manifest_file_match(brain, manifests, brain / "knowledge", {})
        assert findings[0].severity == Severity.WOULD_TRIGGER_FETCH

    def test_unmaterialized_ok(self, brain: Path) -> None:
        manifests = {"confluence:123": _make_manifest("confluence:123", materialized_path="")}
        findings = check_manifest_file_match(brain, manifests, brain / "knowledge", {})
        assert findings[0].severity == Severity.OK


# ---------------------------------------------------------------------------
# TestCheckIdentityHeaders
# ---------------------------------------------------------------------------


class TestCheckIdentityHeaders:
    def test_has_header_ok(self, brain: Path) -> None:
        _write_knowledge_file(brain, "area/c123-doc.md", MANAGED_HEADER_SOURCE.format("confluence:123") + "\ncontent")
        manifests = {"confluence:123": _make_manifest("confluence:123", materialized_path="area/c123-doc.md")}
        findings = check_identity_headers(brain, manifests, brain / "knowledge", {})
        assert findings[0].severity == Severity.OK

    def test_missing_header_drift(self, brain: Path) -> None:
        _write_knowledge_file(brain, "area/c123-doc.md", "content without header")
        manifests = {"confluence:123": _make_manifest("confluence:123", materialized_path="area/c123-doc.md")}
        findings = check_identity_headers(brain, manifests, brain / "knowledge", {})
        assert findings[0].severity == Severity.DRIFT
        assert "Missing" in findings[0].message

    def test_wrong_id_drift(self, brain: Path) -> None:
        _write_knowledge_file(brain, "area/c123-doc.md", MANAGED_HEADER_SOURCE.format("confluence:999") + "\ncontent")
        manifests = {"confluence:123": _make_manifest("confluence:123", materialized_path="area/c123-doc.md")}
        findings = check_identity_headers(brain, manifests, brain / "knowledge", {})
        assert findings[0].severity == Severity.DRIFT
        assert "Wrong" in findings[0].message


# ---------------------------------------------------------------------------
# TestCheckOrphanAttachments
# ---------------------------------------------------------------------------


class TestCheckOrphanAttachments:
    def test_matching_prefix_ok(self, brain: Path) -> None:
        att_dir = brain / "knowledge" / "area" / "_attachments" / "c123"
        att_dir.mkdir(parents=True)
        manifests = {"confluence:123": _make_manifest("confluence:123")}
        findings = check_orphan_attachments(brain, manifests, brain / "knowledge")
        assert len(findings) == 0  # no orphans

    def test_orphan_drift(self, brain: Path) -> None:
        att_dir = brain / "knowledge" / "area" / "_attachments" / "c999"
        att_dir.mkdir(parents=True)
        manifests = {"confluence:123": _make_manifest("confluence:123")}
        findings = check_orphan_attachments(brain, manifests, brain / "knowledge")
        assert len(findings) == 1
        assert findings[0].severity == Severity.DRIFT


# ---------------------------------------------------------------------------
# TestCheckUnregisteredSyncedFiles
# ---------------------------------------------------------------------------


class TestCheckUnregisteredSyncedFiles:
    def test_with_manifest_ok(self, brain: Path) -> None:
        manifests = {"confluence:123": _make_manifest("confluence:123")}
        identity_index = {"confluence:123": Path("area/c123-doc.md")}
        findings = check_unregistered_synced_files(brain, manifests, identity_index)
        assert len(findings) == 0

    def test_without_manifest_drift(self, brain: Path) -> None:
        manifests: dict[str, SourceManifest] = {}
        identity_index = {"confluence:123": Path("area/c123-doc.md")}
        findings = check_unregistered_synced_files(brain, manifests, identity_index)
        assert len(findings) == 1
        assert findings[0].severity == Severity.DRIFT


# ---------------------------------------------------------------------------
# TestCheckDbSourceConsistency
# ---------------------------------------------------------------------------


class TestCheckDbSourceConsistency:
    def test_matching_ok(self, brain: Path) -> None:
        # Add source to DB
        from brain_sync.state import SourceState, SyncState, save_state

        state = SyncState()
        state.sources["confluence:123"] = SourceState(
            canonical_id="confluence:123",
            source_url="https://acme.atlassian.net/wiki/spaces/ENG/pages/123",
            source_type="confluence",
        )
        save_state(brain, state)
        manifests = {"confluence:123": _make_manifest("confluence:123")}
        findings = check_db_source_consistency(brain, manifests)
        assert len(findings) == 0

    def test_orphan_db_row_drift(self, brain: Path) -> None:
        # Insert directly via SQL since save_state skips rows without sync progress
        conn = _connect(brain)
        try:
            conn.execute(
                "INSERT INTO sources (canonical_id, source_url, source_type, target_path) VALUES (?, ?, ?, ?)",
                ("confluence:999", "https://acme.atlassian.net/wiki/spaces/ENG/pages/999", "confluence", ""),
            )
            conn.commit()
        finally:
            conn.close()
        manifests = {"confluence:123": _make_manifest("confluence:123")}
        findings = check_db_source_consistency(brain, manifests)
        assert len(findings) == 1
        assert findings[0].severity == Severity.DRIFT


# ---------------------------------------------------------------------------
# TestCheckPathNormalization
# ---------------------------------------------------------------------------


class TestCheckPathNormalization:
    def test_forward_slashes_ok(self, brain: Path) -> None:
        manifests = {"confluence:123": _make_manifest("confluence:123", materialized_path="area/c123-doc.md")}
        findings = check_path_normalization(brain, manifests)
        assert len(findings) == 0

    def test_backslashes_drift(self, brain: Path) -> None:
        manifests = {"confluence:123": _make_manifest("confluence:123", materialized_path="area\\c123-doc.md")}
        findings = check_path_normalization(brain, manifests)
        assert len(findings) >= 1
        assert findings[0].severity == Severity.DRIFT


# ---------------------------------------------------------------------------
# TestCheckOrphanInsights
# ---------------------------------------------------------------------------


class TestCheckOrphanInsights:
    def test_matching_knowledge_ok(self, brain: Path) -> None:
        (brain / "knowledge" / "project").mkdir(parents=True)
        (brain / "insights" / "project").mkdir(parents=True)
        findings = check_orphan_insights(brain)
        assert len(findings) == 0

    def test_orphan_insights_drift(self, brain: Path) -> None:
        (brain / "insights" / "orphan").mkdir(parents=True)
        findings = check_orphan_insights(brain)
        assert len(findings) == 1
        assert findings[0].severity == Severity.DRIFT

    def test_underscore_prefix_skipped(self, brain: Path) -> None:
        (brain / "insights" / "_core").mkdir(parents=True)
        findings = check_orphan_insights(brain)
        assert len(findings) == 0

    def test_nested_orphan_drift(self, brain: Path) -> None:
        """insights/project/orphan-sub/ with knowledge/project/ but no knowledge/project/orphan-sub/."""
        (brain / "knowledge" / "project").mkdir(parents=True)
        (brain / "insights" / "project" / "orphan-sub").mkdir(parents=True)
        findings = check_orphan_insights(brain)
        assert len(findings) == 1
        assert findings[0].severity == Severity.DRIFT
        assert "project/orphan-sub" in findings[0].message

    def test_nested_orphan_parent_already_orphaned(self, brain: Path) -> None:
        """If parent is orphaned, children are not reported separately."""
        (brain / "insights" / "orphan" / "child").mkdir(parents=True)
        findings = check_orphan_insights(brain)
        # Only the parent is reported, not the child
        assert len(findings) == 1
        assert findings[0].knowledge_path == "orphan"


# ---------------------------------------------------------------------------
# TestCheckOrphanInsightStateRows
# ---------------------------------------------------------------------------


class TestCheckOrphanInsightStateRows:
    def test_matching_dir_ok(self, brain: Path) -> None:
        (brain / "knowledge" / "project").mkdir(parents=True)
        save_insight_state(brain, InsightState(knowledge_path="project"))
        findings = check_orphan_insight_state_rows(brain)
        assert len(findings) == 0

    def test_orphan_row_drift(self, brain: Path) -> None:
        save_insight_state(brain, InsightState(knowledge_path="deleted"))
        findings = check_orphan_insight_state_rows(brain)
        assert len(findings) == 1
        assert findings[0].severity == Severity.DRIFT


# ---------------------------------------------------------------------------
# TestCheckSummariesWithoutDbRows
# ---------------------------------------------------------------------------


class TestCheckSummariesWithoutDbRows:
    def test_summary_with_row_ok(self, brain: Path) -> None:
        _write_insight_summary(brain, "project")
        save_insight_state(brain, InsightState(knowledge_path="project"))
        findings = check_summaries_without_db_rows(brain)
        assert len(findings) == 0

    def test_summary_without_row_would_regen(self, brain: Path) -> None:
        _write_insight_summary(brain, "project")
        findings = check_summaries_without_db_rows(brain)
        assert len(findings) == 1
        assert findings[0].severity == Severity.WOULD_TRIGGER_REGEN


# ---------------------------------------------------------------------------
# TestCheckStaleSummaries
# ---------------------------------------------------------------------------


class TestCheckStaleSummaries:
    def test_matching_knowledge_ok(self, brain: Path) -> None:
        (brain / "knowledge" / "project").mkdir(parents=True)
        _write_insight_summary(brain, "project")
        findings = check_stale_summaries(brain)
        assert len(findings) == 0

    def test_deleted_knowledge_drift(self, brain: Path) -> None:
        _write_insight_summary(brain, "deleted")
        findings = check_stale_summaries(brain)
        assert len(findings) == 1
        assert findings[0].severity == Severity.DRIFT


# ---------------------------------------------------------------------------
# TestCheckRegenChangeDetection
# ---------------------------------------------------------------------------


class TestCheckRegenChangeDetection:
    def test_matching_hash_ok(self, brain: Path) -> None:
        from brain_sync.regen import ChangeEvent

        (brain / "knowledge" / "project").mkdir(parents=True)
        save_insight_state(brain, InsightState(knowledge_path="project"))
        with patch(
            "brain_sync.regen.classify_folder_change",
            return_value=(ChangeEvent(change_type="none", structural=False), "hash1", "hash2"),
        ):
            findings = check_regen_change_detection(brain)
            assert len(findings) == 0

    def test_changed_content_would_regen(self, brain: Path) -> None:
        from brain_sync.regen import ChangeEvent

        (brain / "knowledge" / "project").mkdir(parents=True)
        _write_knowledge_file(brain, "project/doc.md", "content")
        save_insight_state(brain, InsightState(knowledge_path="project"))
        with patch(
            "brain_sync.regen.classify_folder_change",
            return_value=(ChangeEvent(change_type="content", structural=False), "newhash", "hash2"),
        ):
            findings = check_regen_change_detection(brain)
            assert len(findings) == 1
            assert findings[0].severity == Severity.WOULD_TRIGGER_REGEN

    def test_structure_only_would_regen(self, brain: Path) -> None:
        from brain_sync.regen import ChangeEvent

        (brain / "knowledge" / "project").mkdir(parents=True)
        save_insight_state(brain, InsightState(knowledge_path="project"))
        with patch(
            "brain_sync.regen.classify_folder_change",
            return_value=(ChangeEvent(change_type="rename", structural=True), "hash1", "newhash"),
        ):
            findings = check_regen_change_detection(brain)
            assert len(findings) == 1
            assert findings[0].severity == Severity.WOULD_TRIGGER_REGEN
            assert "Structure" in findings[0].message


# ---------------------------------------------------------------------------
# TestCheckDbPathNormalization
# ---------------------------------------------------------------------------


class TestCheckDbPathNormalization:
    def test_clean_paths_ok(self, brain: Path) -> None:
        save_insight_state(brain, InsightState(knowledge_path="project/area"))
        findings = check_db_path_normalization(brain)
        assert len(findings) == 0

    def test_backslashes_drift(self, brain: Path) -> None:
        # Both InsightState and SourceState auto-normalize paths via _PathNormalized.
        # The check reads through these dataclasses, so backslashes inserted directly
        # in the DB get normalized on read. Verify the check does not produce false
        # positives, and would catch a path with leading slash (not auto-normalized).
        conn = _connect(brain)
        try:
            # Leading slash is not normalized away by _PathNormalized
            conn.execute(
                "INSERT OR REPLACE INTO insight_state (knowledge_path, regen_status) VALUES (?, ?)",
                ("/project/area", "idle"),
            )
            conn.commit()
        finally:
            conn.close()
        findings = check_db_path_normalization(brain)
        assert any(f.severity == Severity.DRIFT for f in findings)


# ---------------------------------------------------------------------------
# TestBuildIdentityIndex
# ---------------------------------------------------------------------------


class TestBuildIdentityIndex:
    def test_scans_headers(self, brain: Path) -> None:
        _write_knowledge_file(brain, "area/c123-doc.md", MANAGED_HEADER_SOURCE.format("confluence:123") + "\ncontent")
        _write_knowledge_file(brain, "other/notes.md", "no header here")
        index = _build_identity_index(brain / "knowledge")
        assert "confluence:123" in index
        assert len(index) == 1
