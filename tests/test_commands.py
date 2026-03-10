"""Tests for the commands/ library API."""

from __future__ import annotations

import json

import pytest

from brain_sync.commands import (
    AddResult,
    BrainNotFoundError,
    MoveResult,
    RemoveResult,
    SourceAlreadyExistsError,
    SourceInfo,
    SourceNotFoundError,
    UpdateResult,
    add_source,
    init_brain,
    list_sources,
    move_source,
    remove_source,
    resolve_root,
    update_skill,
    update_source,
)
from brain_sync.commands.context import _require_root
from brain_sync.state import _connect

pytestmark = pytest.mark.unit


@pytest.fixture
def brain(tmp_path):
    """Create a minimal brain structure with SQLite initialized."""
    root = tmp_path / "brain"
    root.mkdir()
    (root / "knowledge").mkdir()
    (root / "insights").mkdir()
    conn = _connect(root)
    conn.close()
    return root


CONFLUENCE_URL = "https://example.atlassian.net/wiki/spaces/TEAM/pages/12345/Test-Page"
CONFLUENCE_CID = "confluence:12345"

CONFLUENCE_URL_2 = "https://example.atlassian.net/wiki/spaces/TEAM/pages/67890/Other-Page"
CONFLUENCE_CID_2 = "confluence:67890"


class TestResolveRoot:
    def test_reads_from_config(self, tmp_path, monkeypatch):
        brain_root = tmp_path / "my-brain"
        brain_root.mkdir()

        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_file = config_dir / "config.json"
        config_file.write_text(
            json.dumps({"brains": [str(brain_root)]}),
            encoding="utf-8",
        )
        monkeypatch.setattr("brain_sync.commands.context.CONFIG_FILE", config_file)

        result = resolve_root()
        assert result == brain_root

    def test_raises_when_no_config(self, tmp_path, monkeypatch):
        config_file = tmp_path / "nonexistent" / "config.json"
        monkeypatch.setattr("brain_sync.commands.context.CONFIG_FILE", config_file)

        with pytest.raises(BrainNotFoundError):
            resolve_root()

    def test_raises_when_empty_brains(self, tmp_path, monkeypatch):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"brains": []}), encoding="utf-8")
        monkeypatch.setattr("brain_sync.commands.context.CONFIG_FILE", config_file)

        with pytest.raises(BrainNotFoundError):
            resolve_root()

    def test_explicit_root_overrides_config(self, tmp_path, monkeypatch):
        """_require_root uses explicit path when provided."""
        explicit = tmp_path / "explicit"
        explicit.mkdir()

        # Config points elsewhere
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps({"brains": [str(tmp_path / "other")]}),
            encoding="utf-8",
        )
        monkeypatch.setattr("brain_sync.commands.context.CONFIG_FILE", config_file)

        result = _require_root(explicit)
        assert result == explicit.resolve()


class TestAddSource:
    def test_registers_new_source(self, brain):
        result = add_source(root=brain, url=CONFLUENCE_URL, target_path="project")

        assert isinstance(result, AddResult)
        assert result.canonical_id == CONFLUENCE_CID
        assert result.source_url == CONFLUENCE_URL
        assert result.target_path == "project"

    def test_raises_on_duplicate(self, brain):
        add_source(root=brain, url=CONFLUENCE_URL, target_path="project")

        with pytest.raises(SourceAlreadyExistsError) as exc_info:
            add_source(root=brain, url=CONFLUENCE_URL, target_path="other")

        assert exc_info.value.canonical_id == CONFLUENCE_CID

    def test_creates_target_dir(self, brain):
        add_source(root=brain, url=CONFLUENCE_URL, target_path="deep/nested/path")

        assert (brain / "knowledge" / "deep" / "nested" / "path").is_dir()

    def test_include_flags(self, brain):
        result = add_source(
            root=brain,
            url=CONFLUENCE_URL,
            target_path="project",
            include_links=True,
            include_children=True,
            include_attachments=True,
        )
        assert result.include_links is True
        assert result.include_children is True
        assert result.include_attachments is True

    def test_root_none_uses_config(self, brain, monkeypatch):
        """add_source with root=None auto-discovers from config."""
        config_file = brain.parent / "config.json"
        config_file.write_text(
            json.dumps({"brains": [str(brain)]}),
            encoding="utf-8",
        )
        monkeypatch.setattr("brain_sync.commands.context.CONFIG_FILE", config_file)

        result = add_source(url=CONFLUENCE_URL, target_path="project")
        assert result.canonical_id == CONFLUENCE_CID


class TestRemoveSource:
    def test_removes_existing(self, brain):
        add_source(root=brain, url=CONFLUENCE_URL, target_path="project")

        result = remove_source(root=brain, source=CONFLUENCE_CID)
        assert isinstance(result, RemoveResult)
        assert result.canonical_id == CONFLUENCE_CID
        assert result.files_deleted is False

        # Verify it's gone
        sources = list_sources(root=brain)
        assert len(sources) == 0

    def test_raises_on_missing(self, brain):
        with pytest.raises(SourceNotFoundError) as exc_info:
            remove_source(root=brain, source="nonexistent")
        assert exc_info.value.source == "nonexistent"

    def test_deletes_files_when_requested(self, brain):
        add_source(root=brain, url=CONFLUENCE_URL, target_path="project")
        (brain / "knowledge" / "project" / "doc.md").write_text("content", encoding="utf-8")

        result = remove_source(root=brain, source=CONFLUENCE_CID, delete_files=True)
        assert result.files_deleted is True
        assert not (brain / "knowledge" / "project").exists()

    def test_remove_by_url(self, brain):
        add_source(root=brain, url=CONFLUENCE_URL, target_path="project")

        result = remove_source(root=brain, source=CONFLUENCE_URL)
        assert result.canonical_id == CONFLUENCE_CID


class TestListSources:
    def test_returns_all(self, brain):
        add_source(root=brain, url=CONFLUENCE_URL, target_path="project-a")
        add_source(root=brain, url=CONFLUENCE_URL_2, target_path="project-b")

        sources = list_sources(root=brain)
        assert len(sources) == 2
        assert all(isinstance(s, SourceInfo) for s in sources)

    def test_filters_by_path(self, brain):
        add_source(root=brain, url=CONFLUENCE_URL, target_path="area/project-a")
        add_source(root=brain, url=CONFLUENCE_URL_2, target_path="other/project-b")

        sources = list_sources(root=brain, filter_path="area")
        assert len(sources) == 1
        assert sources[0].target_path == "area/project-a"

    def test_empty_returns_empty_list(self, brain):
        sources = list_sources(root=brain)
        assert sources == []

    def test_includes_status_fields(self, brain):
        add_source(root=brain, url=CONFLUENCE_URL, target_path="project")

        sources = list_sources(root=brain)
        s = sources[0]
        # Status fields exist (may be None for new sources)
        assert hasattr(s, "last_checked_utc")
        assert hasattr(s, "last_changed_utc")
        assert hasattr(s, "current_interval_secs")


class TestMoveSource:
    def test_moves_path_and_files(self, brain):
        add_source(root=brain, url=CONFLUENCE_URL, target_path="old-path")
        (brain / "knowledge" / "old-path" / "doc.md").write_text("content", encoding="utf-8")

        result = move_source(root=brain, source=CONFLUENCE_CID, to_path="new-path")

        assert isinstance(result, MoveResult)
        assert result.old_path == "old-path"
        assert result.new_path == "new-path"
        assert result.files_moved is True
        assert (brain / "knowledge" / "new-path" / "doc.md").exists()
        assert not (brain / "knowledge" / "old-path").exists()

    def test_raises_on_missing(self, brain):
        with pytest.raises(SourceNotFoundError):
            move_source(root=brain, source="nonexistent", to_path="somewhere")

    def test_updates_state(self, brain):
        add_source(root=brain, url=CONFLUENCE_URL, target_path="old-path")
        move_source(root=brain, source=CONFLUENCE_CID, to_path="new-path")

        sources = list_sources(root=brain)
        assert sources[0].target_path == "new-path"


class TestUpdateSource:
    def test_update_source_flags(self, brain):
        """Update include_links from False to True, verify DB."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="project")

        result = update_source(root=brain, source=CONFLUENCE_CID, include_links=True)

        assert isinstance(result, UpdateResult)
        assert result.canonical_id == CONFLUENCE_CID
        assert result.include_links is True
        assert result.include_children is False
        assert result.include_attachments is False

        # Verify persisted in DB by reloading
        sources = list_sources(root=brain)
        assert sources[0].include_links is True
        assert sources[0].include_children is False

    def test_update_source_partial(self, brain):
        """Update only one flag, others unchanged."""
        add_source(
            root=brain,
            url=CONFLUENCE_URL,
            target_path="project",
            include_links=True,
            include_children=True,
            include_attachments=True,
        )

        result = update_source(root=brain, source=CONFLUENCE_CID, include_children=False)

        assert result.include_links is True
        assert result.include_children is False
        assert result.include_attachments is True

        # Verify persisted
        sources = list_sources(root=brain)
        assert sources[0].include_links is True
        assert sources[0].include_children is False
        assert sources[0].include_attachments is True

    def test_update_source_not_found(self, brain):
        """Raises SourceNotFoundError for unknown source."""
        with pytest.raises(SourceNotFoundError):
            update_source(root=brain, source="nonexistent", include_links=True)

    def test_update_source_by_url(self, brain):
        """Can resolve source by URL."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="project")

        result = update_source(root=brain, source=CONFLUENCE_URL, include_attachments=True)
        assert result.canonical_id == CONFLUENCE_CID
        assert result.include_attachments is True

    def test_update_source_no_changes(self, brain):
        """Calling with no flags is a no-op but succeeds."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="project", include_links=True)

        result = update_source(root=brain, source=CONFLUENCE_CID)
        assert result.include_links is True


class TestInitBrain:
    @pytest.fixture(autouse=True)
    def isolate_config(self, tmp_path, monkeypatch):
        """Prevent init_brain from touching the real ~/.brain-sync/config.json."""
        config_dir = tmp_path / "fake-config"
        config_dir.mkdir()
        config_file = config_dir / "config.json"
        monkeypatch.setattr("brain_sync.commands.init.CONFIG_DIR", config_dir)
        monkeypatch.setattr("brain_sync.commands.init.CONFIG_FILE", config_file)
        skill_dir = tmp_path / "fake-skills" / "brain-sync"
        monkeypatch.setattr("brain_sync.commands.init.SKILL_INSTALL_DIR", skill_dir)

    def test_creates_structure(self, tmp_path):
        root = tmp_path / "new-brain"
        result = init_brain(root)

        assert result.root == root.resolve()
        assert result.was_existing is False
        assert (root / "knowledge").is_dir()
        assert (root / "knowledge" / "_core").is_dir()
        assert (root / "insights").is_dir()
        assert (root / "insights" / "_core").is_dir()
        assert (root / "schemas" / "insights").is_dir()
        assert (root / "schemas" / "insights" / "summary.md").exists()
        assert (root / "schemas" / "insights" / "decisions.md").exists()
        assert (root / "schemas" / "insights" / "glossary.md").exists()
        assert (root / "schemas" / "insights" / "status.md").exists()
        assert (root / ".sync-state.sqlite").exists()

    def test_existing_directory(self, tmp_path):
        root = tmp_path / "existing"
        root.mkdir()

        result = init_brain(root)
        assert result.was_existing is True

    def test_dry_run_no_changes(self, tmp_path):
        root = tmp_path / "dry-run-brain"
        init_brain(root, dry_run=True)

        # Root should not be created in dry-run
        assert not (root / "knowledge").exists()


class TestUpdateSkill:
    def test_copies_skill_files(self, tmp_path, monkeypatch):
        skill_dir = tmp_path / "skills" / "brain-sync"
        monkeypatch.setattr("brain_sync.commands.init.SKILL_INSTALL_DIR", skill_dir)

        updated = update_skill()
        assert len(updated) == 1
        assert updated[0].name == "SKILL.md"
        assert (skill_dir / "SKILL.md").exists()
        assert not (skill_dir / "CORE_INSTRUCTIONS.md").exists()

    def test_removes_legacy_core_instructions(self, tmp_path, monkeypatch):
        skill_dir = tmp_path / "skills" / "brain-sync"
        skill_dir.mkdir(parents=True)
        legacy = skill_dir / "CORE_INSTRUCTIONS.md"
        legacy.write_text("old content")
        monkeypatch.setattr("brain_sync.commands.init.SKILL_INSTALL_DIR", skill_dir)

        update_skill()
        assert not legacy.exists()


class TestCliLibraryParity:
    """Verify CLI and Python API produce the same state changes."""

    def test_add_parity(self, brain):
        """add_source creates the same state as the old run_add."""
        result = add_source(root=brain, url=CONFLUENCE_URL, target_path="project")

        # Verify state matches what old CLI would create
        sources = list_sources(root=brain)
        assert len(sources) == 1
        assert sources[0].canonical_id == result.canonical_id
        assert sources[0].target_path == "project"
        assert (brain / "knowledge" / "project").is_dir()

    def test_remove_parity(self, brain):
        """remove_source produces same state as old run_remove."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="project")
        remove_source(root=brain, source=CONFLUENCE_CID)

        sources = list_sources(root=brain)
        assert len(sources) == 0

    def test_move_parity(self, brain):
        """move_source produces same state as old run_move."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="old")
        (brain / "knowledge" / "old" / "doc.md").write_text("content", encoding="utf-8")

        move_source(root=brain, source=CONFLUENCE_CID, to_path="new")

        sources = list_sources(root=brain)
        assert sources[0].target_path == "new"
        assert (brain / "knowledge" / "new" / "doc.md").exists()

    def test_list_parity(self, brain):
        """list_sources returns complete SourceInfo objects."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="a")
        add_source(root=brain, url=CONFLUENCE_URL_2, target_path="b")

        sources = list_sources(root=brain)
        assert len(sources) == 2
        cids = {s.canonical_id for s in sources}
        assert CONFLUENCE_CID in cids
        assert CONFLUENCE_CID_2 in cids


class TestSkillSmoke:
    """Simulate skill use case: import and call with no subprocess."""

    def test_list_sources_no_subprocess(self, brain, monkeypatch):
        """The skill can call list_sources() without subprocess."""
        # Set up config to point at brain
        config_file = brain.parent / "config.json"
        config_file.write_text(
            json.dumps({"brains": [str(brain)]}),
            encoding="utf-8",
        )
        monkeypatch.setattr("brain_sync.commands.context.CONFIG_FILE", config_file)

        # Add a source first (with explicit root)
        add_source(root=brain, url=CONFLUENCE_URL, target_path="project")

        # Now call without root — simulates skill usage
        sources = list_sources()
        assert len(sources) == 1
        assert sources[0].canonical_id == CONFLUENCE_CID

    def test_add_source_no_subprocess(self, brain, monkeypatch):
        """The skill can call add_source() without subprocess."""
        config_file = brain.parent / "config.json"
        config_file.write_text(
            json.dumps({"brains": [str(brain)]}),
            encoding="utf-8",
        )
        monkeypatch.setattr("brain_sync.commands.context.CONFIG_FILE", config_file)

        result = add_source(url=CONFLUENCE_URL, target_path="project")
        assert result.canonical_id == CONFLUENCE_CID
        assert (brain / "knowledge" / "project").is_dir()
