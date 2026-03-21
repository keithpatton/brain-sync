"""Unit tests for the application command layer.

This layer still accepts `target_path` as a compatibility/input term. When new
tests need to validate durable portable-brain semantics, prefer asserting the
resulting `knowledge_path` rather than extending `target_path` terminology.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from brain_sync.application import (
    AddResult,
    BrainNotFoundError,
    InvalidBrainRootError,
    MigrateResult,
    MoveResult,
    RemoveResult,
    SourceAlreadyExistsError,
    SourceInfo,
    UpdateResult,
    add_source,
    check_source_exists,
    init_brain,
    list_sources,
    migrate_sources,
    move_source,
    reconcile_sources,
    remove_source,
    resolve_active_root,
    resolve_root,
    update_skill,
    update_source,
    validate_brain_root,
)
from brain_sync.application.roots import _require_root
from brain_sync.brain.managed_markdown import prepend_managed_header
from brain_sync.brain.manifest import mark_manifest_missing, read_source_manifest
from brain_sync.runtime.repository import _connect

pytestmark = pytest.mark.unit

CONFLUENCE_URL = "https://example.atlassian.net/wiki/spaces/TEAM/pages/12345/Test-Page"
CONFLUENCE_CID = "confluence:12345"
CONFLUENCE_URL_2 = "https://example.atlassian.net/wiki/spaces/TEAM/pages/67890/Other-Page"
CONFLUENCE_CID_2 = "confluence:67890"


def _write_brain_manifest(root: Path) -> None:
    (root / ".brain-sync" / "sources").mkdir(parents=True, exist_ok=True)
    (root / ".brain-sync" / "brain.json").write_text('{"version": 1}\n', encoding="utf-8")


@pytest.fixture
def brain(tmp_path: Path) -> Path:
    root = tmp_path / "brain"
    root.mkdir()
    (root / "knowledge").mkdir()
    _write_brain_manifest(root)
    conn = _connect(root)
    conn.close()
    return root


class TestResolveRoot:
    def test_reads_active_root_from_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        brain_root = tmp_path / "my-brain"
        brain_root.mkdir()
        (brain_root / "knowledge").mkdir()
        _write_brain_manifest(brain_root)

        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"brains": [str(brain_root)]}), encoding="utf-8")
        monkeypatch.setattr("brain_sync.runtime.config.CONFIG_FILE", config_file)

        assert resolve_active_root() == brain_root

    def test_reads_from_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        brain_root = tmp_path / "my-brain"
        brain_root.mkdir()
        (brain_root / "knowledge").mkdir()
        _write_brain_manifest(brain_root)

        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"brains": [str(brain_root)]}), encoding="utf-8")
        monkeypatch.setattr("brain_sync.runtime.config.CONFIG_FILE", config_file)

        assert resolve_root() == brain_root

    def test_raises_when_no_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("brain_sync.runtime.config.CONFIG_FILE", tmp_path / "missing" / "config.json")
        with pytest.raises(BrainNotFoundError):
            resolve_active_root()

    def test_explicit_root_overrides_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        explicit = tmp_path / "explicit"
        explicit.mkdir()
        (explicit / "knowledge").mkdir()
        _write_brain_manifest(explicit)

        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"brains": [str(tmp_path / "other")]}), encoding="utf-8")
        monkeypatch.setattr("brain_sync.runtime.config.CONFIG_FILE", config_file)

        assert _require_root(explicit) == explicit.resolve()


class TestValidateBrainRoot:
    def test_valid_root_passes(self, brain: Path) -> None:
        validate_brain_root(brain)

    def test_missing_brain_manifest_raises(self, tmp_path: Path) -> None:
        root = tmp_path / "brain"
        root.mkdir()
        (root / "knowledge").mkdir()
        with pytest.raises(InvalidBrainRootError):
            validate_brain_root(root)


class TestAddAndExists:
    def test_registers_new_source_as_awaiting(self, brain: Path) -> None:
        result = add_source(root=brain, url=CONFLUENCE_URL, target_path="project", sync_attachments=True)

        assert isinstance(result, AddResult)
        assert result.canonical_id == CONFLUENCE_CID
        assert result.sync_attachments is True
        assert (brain / "knowledge" / "project").is_dir()

        manifest = read_source_manifest(brain, CONFLUENCE_CID)
        assert manifest is not None
        assert manifest.target_path == "project"
        assert manifest.knowledge_state == "awaiting"
        assert manifest.knowledge_path == "project/c12345.md"
        assert manifest.sync_attachments is True

    def test_duplicate_raises(self, brain: Path) -> None:
        add_source(root=brain, url=CONFLUENCE_URL, target_path="project")
        with pytest.raises(SourceAlreadyExistsError):
            add_source(root=brain, url=CONFLUENCE_URL, target_path="project")

    def test_check_source_exists(self, brain: Path) -> None:
        add_source(root=brain, url=CONFLUENCE_URL, target_path="project")
        assert check_source_exists(brain, CONFLUENCE_URL) is not None

    def test_duplicate_missing_source_still_raises(self, brain: Path) -> None:
        add_source(root=brain, url=CONFLUENCE_URL, target_path="project")
        mark_manifest_missing(brain, CONFLUENCE_CID, "2026-03-19T10:00:00+00:00")

        with pytest.raises(SourceAlreadyExistsError):
            add_source(root=brain, url=CONFLUENCE_URL, target_path="project")


class TestListAndUpdate:
    def test_list_sources_returns_infos(self, brain: Path) -> None:
        add_source(root=brain, url=CONFLUENCE_URL, target_path="a")
        add_source(root=brain, url=CONFLUENCE_URL_2, target_path="b")

        sources = list_sources(root=brain)

        assert len(sources) == 2
        assert all(isinstance(source, SourceInfo) for source in sources)
        assert {source.canonical_id for source in sources} == {CONFLUENCE_CID, CONFLUENCE_CID_2}

    def test_update_source_updates_manifest_backed_flags(self, brain: Path) -> None:
        add_source(root=brain, url=CONFLUENCE_URL, target_path="project")

        result = update_source(root=brain, source=CONFLUENCE_URL, fetch_children=True, sync_attachments=True)

        assert isinstance(result, UpdateResult)
        assert result.fetch_children is True
        assert result.sync_attachments is True

        manifest = read_source_manifest(brain, CONFLUENCE_CID)
        assert manifest is not None
        assert manifest.sync_attachments is True


class TestMoveAndRemove:
    def test_move_source_marks_materialized_source_stale(self, brain: Path) -> None:
        add_source(root=brain, url=CONFLUENCE_URL, target_path="old")
        materialized = brain / "knowledge" / "old" / "c12345-doc.md"
        materialized.parent.mkdir(parents=True, exist_ok=True)
        materialized.write_text(prepend_managed_header(CONFLUENCE_CID, "# Doc"), encoding="utf-8")
        manifest = read_source_manifest(brain, CONFLUENCE_CID)
        assert manifest is not None
        manifest.knowledge_state = "materialized"
        manifest.knowledge_path = "old/c12345-doc.md"
        manifest.content_hash = "sha256:abc"
        manifest.remote_fingerprint = "rev-1"
        manifest.materialized_utc = "2026-03-19T08:00:00+00:00"
        from brain_sync.brain.manifest import write_source_manifest

        write_source_manifest(brain, manifest)

        result = move_source(root=brain, source=CONFLUENCE_CID, to_path="new")

        assert isinstance(result, MoveResult)
        assert result.new_path == "new"
        assert (brain / "knowledge" / "new" / "c12345-doc.md").exists()

        moved_manifest = read_source_manifest(brain, CONFLUENCE_CID)
        assert moved_manifest is not None
        assert moved_manifest.knowledge_path == "new/c12345-doc.md"
        assert moved_manifest.knowledge_state == "stale"

    def test_remove_source_deletes_manifest_and_files_when_requested(self, brain: Path) -> None:
        add_source(root=brain, url=CONFLUENCE_URL, target_path="project", sync_attachments=True)
        target_dir = brain / "knowledge" / "project"
        (target_dir / "c12345-doc.md").write_text(
            prepend_managed_header(CONFLUENCE_CID, "content", source_type="confluence", source_url=CONFLUENCE_URL),
            encoding="utf-8",
        )
        att_dir = target_dir / ".brain-sync" / "attachments" / "c12345"
        att_dir.mkdir(parents=True)
        (att_dir / "a789.png").write_bytes(b"png")

        result = remove_source(root=brain, source=CONFLUENCE_CID, delete_files=True)

        assert isinstance(result, RemoveResult)
        assert result.files_deleted is True
        assert read_source_manifest(brain, CONFLUENCE_CID) is None
        assert not (target_dir / "c12345-doc.md").exists()
        assert not att_dir.exists()

    def test_remove_missing_source_returns_not_found_result(self, brain: Path) -> None:
        result = remove_source(root=brain, source=CONFLUENCE_CID)

        assert result.result_state == "not_found"
        assert result.source == CONFLUENCE_CID

    def test_move_missing_source_returns_not_found_result(self, brain: Path) -> None:
        result = move_source(root=brain, source=CONFLUENCE_CID, to_path="new-area")

        assert result.result_state == "not_found"
        assert result.source == CONFLUENCE_CID
        assert result.new_path == "new-area"

    def test_remove_source_without_delete_files_still_removes_synced_markdown_and_attachments(
        self,
        brain: Path,
    ) -> None:
        add_source(root=brain, url=CONFLUENCE_URL, target_path="project", sync_attachments=True)
        target_dir = brain / "knowledge" / "project"
        doc_path = target_dir / "c12345-doc.md"
        doc_path.write_text(
            prepend_managed_header(CONFLUENCE_CID, "content", source_type="confluence", source_url=CONFLUENCE_URL),
            encoding="utf-8",
        )
        att_dir = target_dir / ".brain-sync" / "attachments" / "c12345"
        att_dir.mkdir(parents=True)
        (att_dir / "a789.png").write_bytes(b"png")

        result = remove_source(root=brain, source=CONFLUENCE_CID, delete_files=False)

        assert isinstance(result, RemoveResult)
        assert result.files_deleted is True
        assert read_source_manifest(brain, CONFLUENCE_CID) is None
        assert not doc_path.exists()
        assert not att_dir.exists()


class TestReconcileAndMigrate:
    def test_reconcile_updates_moved_source_to_stale(self, brain: Path) -> None:
        add_source(root=brain, url=CONFLUENCE_URL, target_path="project")
        manifest = read_source_manifest(brain, CONFLUENCE_CID)
        assert manifest is not None
        manifest.knowledge_state = "materialized"
        manifest.knowledge_path = "project/c12345-doc.md"
        manifest.content_hash = "sha256:abc"
        manifest.remote_fingerprint = "rev-1"
        manifest.materialized_utc = "2026-03-19T08:00:00+00:00"
        from brain_sync.brain.manifest import write_source_manifest

        write_source_manifest(brain, manifest)
        old_file = brain / "knowledge" / "project" / "c12345-doc.md"
        old_file.parent.mkdir(parents=True, exist_ok=True)
        old_file.write_text(prepend_managed_header(CONFLUENCE_CID, "# Doc"), encoding="utf-8")
        moved_dir = brain / "knowledge" / "renamed"
        moved_dir.mkdir(parents=True)
        moved_file = moved_dir / "c12345-doc.md"
        old_file.replace(moved_file)

        result = reconcile_sources(root=brain)

        assert result.updated[0].new_path == "renamed"
        moved_manifest = read_source_manifest(brain, CONFLUENCE_CID)
        assert moved_manifest is not None
        assert moved_manifest.knowledge_path == "renamed/c12345-doc.md"
        assert moved_manifest.knowledge_state == "stale"

    def test_migrate_sources_moves_legacy_attachments(self, brain: Path) -> None:
        add_source(root=brain, url=CONFLUENCE_URL, target_path="project", sync_attachments=True)
        target_dir = brain / "knowledge" / "project"
        legacy = target_dir / "_sync-context" / "attachments"
        legacy.mkdir(parents=True)
        (legacy / "a789-diagram.png").write_bytes(b"png-data")

        result = migrate_sources(root=brain)

        assert isinstance(result, MigrateResult)
        assert result.sources_migrated == 1
        assert result.files_migrated == 1
        assert (target_dir / ".brain-sync" / "attachments" / "c12345" / "a789-diagram.png").read_bytes() == b"png-data"


class TestInitAndSkill:
    def test_init_brain_creates_supported_structure(self, tmp_path: Path) -> None:
        root = tmp_path / "new-brain"
        result = init_brain(root)

        assert result.root == root.resolve()
        assert (root / ".brain-sync" / "brain.json").exists()
        assert (root / ".brain-sync" / "sources").is_dir()
        assert (root / "knowledge").is_dir()
        assert (root / "knowledge" / "_core").is_dir()
        assert not (root / "insights").exists()
        assert not (root / ".sync-state.sqlite").exists()

    def test_update_skill_copies_skill(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        skill_dir = tmp_path / "skills" / "brain-sync"
        monkeypatch.setenv("BRAIN_SYNC_SKILL_INSTALL_DIR", str(skill_dir))

        updated = update_skill()

        assert updated[0].name == "SKILL.md"
        assert (skill_dir / "SKILL.md").exists()
