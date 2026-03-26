from __future__ import annotations

from pathlib import Path

import pytest

from brain_sync.application.init import init_brain
from brain_sync.application.structure import tree_brain, tree_result_to_payload
from brain_sync.brain.layout import area_insights_dir, area_journal_dir
from brain_sync.brain.managed_markdown import prepend_managed_header
from brain_sync.brain.manifest import SourceManifest, write_source_manifest
from brain_sync.brain.sidecar import RegenMeta, write_regen_meta

pytestmark = pytest.mark.unit


def _seed_structural_tree(root: Path) -> None:
    init_brain(root)

    (root / "knowledge" / "_core" / "about.md").write_text("core context", encoding="utf-8")

    alpha_dir = root / "knowledge" / "initiatives" / "alpha"
    alpha_dir.mkdir(parents=True, exist_ok=True)
    (alpha_dir / "notes.md").write_text("manual note", encoding="utf-8")
    (alpha_dir / "c123-alpha.md").write_text(
        prepend_managed_header(
            "confluence:123",
            "# Synced alpha\n",
            source_type="confluence",
            source_url="https://acme.atlassian.net/wiki/spaces/TEAM/pages/123/Alpha",
        ),
        encoding="utf-8",
    )

    (root / "knowledge" / "initiatives" / "empty").mkdir(parents=True, exist_ok=True)

    platform_dir = root / "knowledge" / "teams" / "platform"
    platform_dir.mkdir(parents=True, exist_ok=True)
    (platform_dir / "plan.md").write_text("platform plan", encoding="utf-8")

    alpha_insights = area_insights_dir(root, "initiatives/alpha")
    alpha_insights.mkdir(parents=True, exist_ok=True)
    (alpha_insights / "summary.md").write_text("# Alpha summary", encoding="utf-8")
    (alpha_insights / "decisions.md").write_text("# Alpha decisions", encoding="utf-8")
    write_regen_meta(
        alpha_insights,
        RegenMeta(
            content_hash="content-alpha",
            summary_hash="summary-alpha",
            structure_hash="structure-alpha",
            last_regen_utc="2026-03-26T19:02:00+00:00",
        ),
    )

    alpha_journal = area_journal_dir(root, "initiatives/alpha") / "2026-03"
    alpha_journal.mkdir(parents=True, exist_ok=True)
    (alpha_journal / "2026-03-10.md").write_text("entry one", encoding="utf-8")
    (alpha_journal / "2026-03-12.md").write_text("entry two", encoding="utf-8")
    (area_journal_dir(root, "initiatives/alpha") / "notes.md").write_text("misc entry", encoding="utf-8")

    platform_journal = area_journal_dir(root, "teams/platform")
    platform_journal.mkdir(parents=True, exist_ok=True)
    (platform_journal / "notes.md").write_text("platform note", encoding="utf-8")

    write_source_manifest(
        root,
        SourceManifest(
            canonical_id="confluence:123",
            source_url="https://acme.atlassian.net/wiki/spaces/TEAM/pages/123/Alpha",
            source_type="confluence",
            sync_attachments=False,
            knowledge_path="initiatives/alpha/c123-alpha.md",
            knowledge_state="materialized",
            content_hash="sha256:123",
            remote_fingerprint="rev-123",
            materialized_utc="2026-03-26T00:00:00+00:00",
        ),
    )
    write_source_manifest(
        root,
        SourceManifest(
            canonical_id="confluence:124",
            source_url="https://acme.atlassian.net/wiki/spaces/TEAM/pages/124/Alpha-Stale",
            source_type="confluence",
            sync_attachments=False,
            knowledge_path="initiatives/alpha/c124-alpha-stale.md",
            knowledge_state="stale",
            content_hash="sha256:124",
            remote_fingerprint="rev-124",
            materialized_utc="2026-03-25T00:00:00+00:00",
        ),
    )
    write_source_manifest(
        root,
        SourceManifest(
            canonical_id="confluence:125",
            source_url="https://acme.atlassian.net/wiki/spaces/TEAM/pages/125/Alpha-Missing",
            source_type="confluence",
            sync_attachments=False,
            knowledge_path="initiatives/alpha/c125-alpha-missing.md",
            knowledge_state="missing",
        ),
    )
    write_source_manifest(
        root,
        SourceManifest(
            canonical_id="confluence:200",
            source_url="https://acme.atlassian.net/wiki/spaces/TEAM/pages/200/Platform-Awaiting",
            source_type="confluence",
            sync_attachments=False,
            knowledge_path="teams/platform/c200-platform-awaiting.md",
            knowledge_state="awaiting",
        ),
    )


def test_tree_brain_returns_expected_sparse_payload(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    _seed_structural_tree(root)

    payload = tree_result_to_payload(tree_brain(root))

    assert payload == {
        "nodes": [
            {"path": "", "depth": 0, "child_folder_count": 3},
            {"path": "_core", "depth": 1, "manual_file_count": 1},
            {"path": "initiatives", "depth": 1, "child_folder_count": 1},
            {
                "path": "initiatives/alpha",
                "depth": 2,
                "manual_file_count": 1,
                "synced_files": {
                    "materialized": 1,
                    "stale": 1,
                    "missing": 1,
                },
                "insights": {
                    "summary_present": True,
                    "artifact_count": 2,
                    "last_regen_utc": "2026-03-26T19:02:00+00:00",
                },
                "journals": {
                    "entry_count": 3,
                    "first_entry_date": "2026-03-10",
                    "last_entry_date": "2026-03-12",
                },
            },
            {"path": "teams", "depth": 1, "child_folder_count": 1},
            {
                "path": "teams/platform",
                "depth": 2,
                "manual_file_count": 1,
                "synced_files": {"awaiting": 1},
                "journals": {"entry_count": 1},
            },
        ],
        "total_nodes": 6,
        "max_depth": 2,
    }


def test_tree_brain_omits_default_fields_and_empty_core_when_not_semantic(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    init_brain(root)

    payload = tree_result_to_payload(tree_brain(root))

    assert payload == {
        "nodes": [
            {"path": "", "depth": 0},
        ],
        "total_nodes": 1,
        "max_depth": 0,
    }
