from __future__ import annotations

import json
from pathlib import Path

import pytest

from brain_sync.commands import (
    AddResult,
    BrainNotFoundError,
    InvalidBrainRootError,
    MigrateResult,
    MoveResult,
    RemoveResult,
    SourceAlreadyExistsError,
    SourceInfo,
    SourceNotFoundError,
    UpdateResult,
    add_source,
    check_source_exists,
    init_brain,
    list_sources,
    migrate_sources,
    move_source,
    reconcile_sources,
    remove_source,
    resolve_root,
    update_skill,
    update_source,
    validate_brain_root,
)
from brain_sync.commands.context import _require_root
from brain_sync.manifest import read_source_manifest
from brain_sync.state import _connect

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
    def test_reads_from_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        brain_root = tmp_path / "my-brain"
        brain_root.mkdir()
        (brain_root / "knowledge").mkdir()
        _write_brain_manifest(brain_root)

        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"brains": [str(brain_root)]}), encoding="utf-8")
        monkeypatch.setattr("brain_sync.config.CONFIG_FILE", config_file)

        assert resolve_root() == brain_root

    def test_raises_when_no_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("brain_sync.config.CONFIG_FILE", tmp_path / "missing" / "config.json")
        with pytest.raises(BrainNotFoundError):
            resolve_root()

    def test_explicit_root_overrides_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        explicit = tmp_path / "explicit"
        explicit.mkdir()
        (explicit / "knowledge").mkdir()
        _write_brain_manifest(explicit)

        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"brains": [str(tmp_path / "other")]}), encoding="utf-8")
        monkeypatch.setattr("brain_sync.config.CONFIG_FILE", config_file)

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

    def test_resolve_root_rejects_knowledge_subfolder(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        brain_root = tmp_path / "brain"
        brain_root.mkdir()
        (brain_root / "knowledge").mkdir()
        _write_brain_manifest(brain_root)

        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"brains": [str(brain_root / "knowledge")]}), encoding="utf-8")
        monkeypatch.setattr("brain_sync.config.CONFIG_FILE", config_file)

        with pytest.raises(InvalidBrainRootError):
            resolve_root()


class TestAddAndExists:
    def test_registers_new_source(self, brain: Path) -> None:
        result = add_source(root=brain, url=CONFLUENCE_URL, target_path="project", sync_attachments=True)

        assert isinstance(result, AddResult)
        assert result.canonical_id == CONFLUENCE_CID
        assert result.sync_attachments is True
        assert (brain / "knowledge" / "project").is_dir()

        manifest = read_source_manifest(brain, CONFLUENCE_CID)
        assert manifest is not None
        assert manifest.target_path == "project"
        assert manifest.sync_attachments is True

    def test_duplicate_raises(self, brain: Path) -> None:
        add_source(root=brain, url=CONFLUENCE_URL, target_path="project")
        with pytest.raises(SourceAlreadyExistsError):
            add_source(root=brain, url=CONFLUENCE_URL, target_path="project")

    def test_check_source_exists(self, brain: Path) -> None:
        add_source(root=brain, url=CONFLUENCE_URL, target_path="project")
        assert check_source_exists(brain, CONFLUENCE_URL) is not None


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
    def test_move_source_moves_directory_and_manifest(self, brain: Path) -> None:
        add_source(root=brain, url=CONFLUENCE_URL, target_path="old")
        (brain / "knowledge" / "old" / "c12345-doc.md").write_text("content", encoding="utf-8")

        result = move_source(root=brain, source=CONFLUENCE_CID, to_path="new")

        assert isinstance(result, MoveResult)
        assert result.new_path == "new"
        assert (brain / "knowledge" / "new" / "c12345-doc.md").exists()

        manifest = read_source_manifest(brain, CONFLUENCE_CID)
        assert manifest is not None
        assert manifest.target_path == "new"

    def test_remove_source_deletes_manifest_and_files_when_requested(self, brain: Path) -> None:
        add_source(root=brain, url=CONFLUENCE_URL, target_path="project", sync_attachments=True)
        target_dir = brain / "knowledge" / "project"
        (target_dir / "c12345-doc.md").write_text("content", encoding="utf-8")
        att_dir = target_dir / ".brain-sync" / "attachments" / "c12345"
        att_dir.mkdir(parents=True)
        (att_dir / "a789.png").write_bytes(b"png")

        result = remove_source(root=brain, source=CONFLUENCE_CID, delete_files=True)

        assert isinstance(result, RemoveResult)
        assert result.files_deleted is True
        assert read_source_manifest(brain, CONFLUENCE_CID) is None
        assert not target_dir.exists()

    def test_remove_source_preserves_unowned_files_in_target_area(self, brain: Path) -> None:
        add_source(root=brain, url=CONFLUENCE_URL, target_path="project", sync_attachments=True)
        target_dir = brain / "knowledge" / "project"
        (target_dir / "c12345-doc.md").write_text("content", encoding="utf-8")
        (target_dir / "notes.md").write_text("keep me", encoding="utf-8")
        att_dir = target_dir / ".brain-sync" / "attachments" / "c12345"
        att_dir.mkdir(parents=True)
        (att_dir / "a789.png").write_bytes(b"png")

        result = remove_source(root=brain, source=CONFLUENCE_CID, delete_files=True)

        assert isinstance(result, RemoveResult)
        assert result.files_deleted is True
        assert read_source_manifest(brain, CONFLUENCE_CID) is None
        assert (target_dir / "notes.md").read_text(encoding="utf-8") == "keep me"
        assert not (target_dir / "c12345-doc.md").exists()
        assert not att_dir.exists()

    def test_remove_missing_source_raises(self, brain: Path) -> None:
        with pytest.raises(SourceNotFoundError):
            remove_source(root=brain, source=CONFLUENCE_CID)


class TestReconcileAndMigrate:
    def test_reconcile_updates_moved_materialized_path(self, brain: Path) -> None:
        add_source(root=brain, url=CONFLUENCE_URL, target_path="project")
        manifest = read_source_manifest(brain, CONFLUENCE_CID)
        assert manifest is not None
        manifest.materialized_path = "project/c12345-doc.md"
        write_source = manifest
        from brain_sync.manifest import write_source_manifest

        write_source_manifest(brain, write_source)
        old_file = brain / "knowledge" / "project" / "c12345-doc.md"
        old_file.write_text("---\nbrain_sync_canonical_id: confluence:12345\n---\n", encoding="utf-8")
        moved_dir = brain / "knowledge" / "renamed"
        moved_dir.mkdir(parents=True)
        moved_file = moved_dir / "c12345-doc.md"
        old_file.replace(moved_file)

        result = reconcile_sources(root=brain)

        assert result.updated[0].new_path == "renamed"
        manifest = read_source_manifest(brain, CONFLUENCE_CID)
        assert manifest is not None
        assert manifest.materialized_path == "renamed/c12345-doc.md"
        assert manifest.target_path == "renamed"

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
    def test_init_brain_creates_v23_structure(self, tmp_path: Path) -> None:
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
        monkeypatch.setattr("brain_sync.commands.init.SKILL_INSTALL_DIR", skill_dir)

        updated = update_skill()

        assert updated[0].name == "SKILL.md"
        assert (skill_dir / "SKILL.md").exists()


class TestConfiglessSkillSmoke:
    def test_list_sources_without_explicit_root_uses_config(self, brain: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_file = brain.parent / "config.json"
        config_file.write_text(json.dumps({"brains": [str(brain)]}), encoding="utf-8")
        monkeypatch.setattr("brain_sync.config.CONFIG_FILE", config_file)

        add_source(root=brain, url=CONFLUENCE_URL, target_path="project")

        sources = list_sources()

        assert len(sources) == 1
        assert sources[0].canonical_id == CONFLUENCE_CID

    def test_add_source_without_explicit_root_uses_config(self, brain: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_file = brain.parent / "config.json"
        config_file.write_text(json.dumps({"brains": [str(brain)]}), encoding="utf-8")
        monkeypatch.setattr("brain_sync.config.CONFIG_FILE", config_file)

        result = add_source(url=CONFLUENCE_URL, target_path="project")

        assert result.canonical_id == CONFLUENCE_CID
        assert (brain / "knowledge" / "project").is_dir()
