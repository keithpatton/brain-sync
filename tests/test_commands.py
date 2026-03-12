"""Tests for the commands/ library API."""

from __future__ import annotations

import json

import pytest

from brain_sync.commands import (
    AddResult,
    BrainNotFoundError,
    MigrateResult,
    MoveResult,
    ReconcileResult,
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
)
from brain_sync.commands.context import _require_root
from brain_sync.state import (
    DocumentState,
    Relationship,
    _connect,
    load_document,
    load_relationships_for_primary,
    save_document,
    save_relationship,
)

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

CONFLUENCE_URL_3 = "https://example.atlassian.net/wiki/spaces/TEAM/pages/11111/Third-Page"
CONFLUENCE_CID_3 = "confluence:11111"

GDOC_URL = "https://docs.google.com/document/d/abc123def/edit"
GDOC_CID = "gdoc:abc123def"


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
        monkeypatch.setattr("brain_sync.config.CONFIG_FILE", config_file)

        result = resolve_root()
        assert result == brain_root

    def test_raises_when_no_config(self, tmp_path, monkeypatch):
        config_file = tmp_path / "nonexistent" / "config.json"
        monkeypatch.setattr("brain_sync.config.CONFIG_FILE", config_file)

        with pytest.raises(BrainNotFoundError):
            resolve_root()

    def test_raises_when_empty_brains(self, tmp_path, monkeypatch):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"brains": []}), encoding="utf-8")
        monkeypatch.setattr("brain_sync.config.CONFIG_FILE", config_file)

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
        monkeypatch.setattr("brain_sync.config.CONFIG_FILE", config_file)

        result = _require_root(explicit)
        assert result == explicit.resolve()


class TestCheckSourceExists:
    def test_found(self, brain):
        add_source(root=brain, url=CONFLUENCE_URL, target_path="project")
        err = check_source_exists(brain, CONFLUENCE_URL)
        assert err is not None
        assert isinstance(err, SourceAlreadyExistsError)
        assert err.canonical_id == CONFLUENCE_CID

    def test_not_found(self, brain):
        result = check_source_exists(brain, CONFLUENCE_URL)
        assert result is None


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
            include_children=True,
            include_attachments=True,
        )
        assert result.include_children is True
        assert result.include_attachments is True

    def test_root_none_uses_config(self, brain, monkeypatch):
        """add_source with root=None auto-discovers from config."""
        config_file = brain.parent / "config.json"
        config_file.write_text(
            json.dumps({"brains": [str(brain)]}),
            encoding="utf-8",
        )
        monkeypatch.setattr("brain_sync.config.CONFIG_FILE", config_file)

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

    def test_deletes_only_source_file(self, brain):
        """delete_files removes only the source's canonical file, not siblings."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="project")
        target_dir = brain / "knowledge" / "project"
        (target_dir / "c12345-test-page.md").write_text("synced content", encoding="utf-8")
        (target_dir / "unrelated-doc.md").write_text("keep me", encoding="utf-8")

        result = remove_source(root=brain, source=CONFLUENCE_CID, delete_files=True)
        assert result.files_deleted is True
        assert not (target_dir / "c12345-test-page.md").exists()
        # Unrelated file must survive
        assert (target_dir / "unrelated-doc.md").exists()
        assert (target_dir / "unrelated-doc.md").read_text(encoding="utf-8") == "keep me"

    def test_deletes_relationship_files(self, brain):
        """delete_files cleans up _sync-context relationship files."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="project")
        target_dir = brain / "knowledge" / "project"
        (target_dir / "c12345-test-page.md").write_text("content", encoding="utf-8")
        ctx_dir = target_dir / "_sync-context" / "children"
        ctx_dir.mkdir(parents=True)
        (ctx_dir / "c99999-child-page.md").write_text("child", encoding="utf-8")

        save_relationship(
            brain,
            Relationship(
                parent_canonical_id=CONFLUENCE_CID,
                canonical_id="confluence:99999",
                relationship_type="child",
                local_path="_sync-context/children/c99999-child-page.md",
                source_type="confluence",
            ),
        )

        result = remove_source(root=brain, source=CONFLUENCE_CID, delete_files=True)
        assert result.files_deleted is True
        assert not (ctx_dir / "c99999-child-page.md").exists()

    def test_empty_dir_cleaned_up(self, brain):
        """Target dir is removed when it becomes empty after file deletion."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="project")
        target_dir = brain / "knowledge" / "project"
        (target_dir / "c12345-test-page.md").write_text("content", encoding="utf-8")

        remove_source(root=brain, source=CONFLUENCE_CID, delete_files=True)
        assert not target_dir.exists()

    def test_partial_dir_preserved(self, brain):
        """Target dir is preserved when other files remain."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="project")
        target_dir = brain / "knowledge" / "project"
        (target_dir / "c12345-test-page.md").write_text("synced", encoding="utf-8")
        emails_dir = target_dir / "emails"
        emails_dir.mkdir()
        (emails_dir / "message.md").write_text("email content", encoding="utf-8")

        remove_source(root=brain, source=CONFLUENCE_CID, delete_files=True)
        assert target_dir.exists()
        assert (emails_dir / "message.md").exists()

    def test_missing_files_no_error(self, brain):
        """Removal succeeds even when source files are already gone."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="project")
        # Don't create any files — they may have been manually deleted

        result = remove_source(root=brain, source=CONFLUENCE_CID, delete_files=True)
        assert result.files_deleted is False

    def test_db_relationships_cleaned(self, brain):
        """Removing a source cleans up its relationship rows from the DB."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="project")
        save_relationship(
            brain,
            Relationship(
                parent_canonical_id=CONFLUENCE_CID,
                canonical_id="confluence:99999",
                relationship_type="child",
                local_path="_sync-context/children/c99999-child.md",
                source_type="confluence",
            ),
        )

        remove_source(root=brain, source=CONFLUENCE_CID)
        assert load_relationships_for_primary(brain, CONFLUENCE_CID) == []

    def test_orphaned_documents_cleaned(self, brain):
        """Document only referenced by removed source is deleted from DB."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="project")
        save_document(
            brain,
            DocumentState(
                canonical_id="confluence:99999",
                source_type="confluence",
                url="https://example.atlassian.net/wiki/spaces/TEAM/pages/99999/Child",
            ),
        )
        save_relationship(
            brain,
            Relationship(
                parent_canonical_id=CONFLUENCE_CID,
                canonical_id="confluence:99999",
                relationship_type="child",
                local_path="_sync-context/children/c99999-child.md",
                source_type="confluence",
            ),
        )

        remove_source(root=brain, source=CONFLUENCE_CID)
        assert load_document(brain, "confluence:99999") is None

    def test_shared_documents_preserved(self, brain):
        """Document referenced by another source's relationships is kept."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="project-a")
        add_source(root=brain, url=CONFLUENCE_URL_2, target_path="project-b")

        # Both sources reference the same child document
        shared_child_cid = "confluence:99999"
        save_document(
            brain,
            DocumentState(
                canonical_id=shared_child_cid,
                source_type="confluence",
                url="https://example.atlassian.net/wiki/spaces/TEAM/pages/99999/Shared",
            ),
        )
        save_relationship(
            brain,
            Relationship(
                parent_canonical_id=CONFLUENCE_CID,
                canonical_id=shared_child_cid,
                relationship_type="child",
                local_path="_sync-context/children/c99999-shared.md",
                source_type="confluence",
            ),
        )
        save_relationship(
            brain,
            Relationship(
                parent_canonical_id=CONFLUENCE_CID_2,
                canonical_id=shared_child_cid,
                relationship_type="child",
                local_path="_sync-context/children/c99999-shared.md",
                source_type="confluence",
            ),
        )

        # Remove only the first source
        remove_source(root=brain, source=CONFLUENCE_CID)

        # Shared document must still exist (referenced by second source)
        assert load_document(brain, shared_child_cid) is not None
        # Second source's relationship must be intact
        rels = load_relationships_for_primary(brain, CONFLUENCE_CID_2)
        assert len(rels) == 1
        assert rels[0].canonical_id == shared_child_cid

    def test_remove_by_url(self, brain):
        add_source(root=brain, url=CONFLUENCE_URL, target_path="project")

        result = remove_source(root=brain, source=CONFLUENCE_URL)
        assert result.canonical_id == CONFLUENCE_CID

    def test_scoped_deletion_gdoc(self, brain):
        """Scoped deletion works for Google Docs sources too."""
        add_source(root=brain, url=GDOC_URL, target_path="docs")
        target_dir = brain / "knowledge" / "docs"
        (target_dir / "gabc123def-my-doc.md").write_text("gdoc content", encoding="utf-8")
        (target_dir / "other-file.md").write_text("keep", encoding="utf-8")

        result = remove_source(root=brain, source=GDOC_CID, delete_files=True)
        assert result.files_deleted is True
        assert not (target_dir / "gabc123def-my-doc.md").exists()
        assert (target_dir / "other-file.md").exists()


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
        """Update include_children from False to True, verify DB."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="project")

        result = update_source(root=brain, source=CONFLUENCE_CID, include_children=True)

        assert isinstance(result, UpdateResult)
        assert result.canonical_id == CONFLUENCE_CID
        assert result.include_children is True
        assert result.include_attachments is False

        # Verify persisted in DB by reloading
        sources = list_sources(root=brain)
        assert sources[0].include_children is True

    def test_update_source_partial(self, brain):
        """Update only one flag, others unchanged."""
        add_source(
            root=brain,
            url=CONFLUENCE_URL,
            target_path="project",
            include_children=True,
            include_attachments=True,
        )

        result = update_source(root=brain, source=CONFLUENCE_CID, include_children=False)

        assert result.include_children is False
        assert result.include_attachments is True

        # Verify persisted
        sources = list_sources(root=brain)
        assert sources[0].include_children is False
        assert sources[0].include_attachments is True

    def test_update_source_not_found(self, brain):
        """Raises SourceNotFoundError for unknown source."""
        with pytest.raises(SourceNotFoundError):
            update_source(root=brain, source="nonexistent", include_children=True)

    def test_update_source_by_url(self, brain):
        """Can resolve source by URL."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="project")

        result = update_source(root=brain, source=CONFLUENCE_URL, include_attachments=True)
        assert result.canonical_id == CONFLUENCE_CID
        assert result.include_attachments is True

    def test_update_source_no_changes(self, brain):
        """Calling with no flags is a no-op but succeeds."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="project", include_children=True)

        result = update_source(root=brain, source=CONFLUENCE_CID)
        assert result.include_children is True


class TestReconcileSources:
    def test_no_changes_when_files_at_expected_path(self, brain):
        add_source(root=brain, url=CONFLUENCE_URL, target_path="project")
        (brain / "knowledge" / "project" / "c12345-test-page.md").write_text("content")

        result = reconcile_sources(root=brain)
        assert isinstance(result, ReconcileResult)
        assert result.updated == []
        assert result.not_found == []

    def test_updates_path_when_file_moved(self, brain):
        add_source(root=brain, url=CONFLUENCE_URL, target_path="old-path")
        # Create file at old path, then move it
        (brain / "knowledge" / "old-path" / "c12345-test-page.md").write_text("content")
        (brain / "knowledge" / "new-path").mkdir(parents=True)
        (brain / "knowledge" / "old-path" / "c12345-test-page.md").rename(
            brain / "knowledge" / "new-path" / "c12345-test-page.md"
        )

        result = reconcile_sources(root=brain)
        assert len(result.updated) == 1
        assert result.updated[0].canonical_id == CONFLUENCE_CID
        assert result.updated[0].old_path == "old-path"
        assert result.updated[0].new_path == "new-path"

        # DB should be updated
        sources = list_sources(root=brain)
        assert sources[0].target_path == "new-path"

    def test_handles_move_to_nested_path(self, brain):
        add_source(root=brain, url=CONFLUENCE_URL, target_path="flat")
        (brain / "knowledge" / "flat" / "c12345-test-page.md").write_text("content")
        (brain / "knowledge" / "confluence" / "team").mkdir(parents=True)
        (brain / "knowledge" / "flat" / "c12345-test-page.md").rename(
            brain / "knowledge" / "confluence" / "team" / "c12345-test-page.md"
        )

        result = reconcile_sources(root=brain)
        assert len(result.updated) == 1
        assert result.updated[0].new_path == "confluence/team"

    def test_not_found_when_file_missing(self, brain):
        add_source(root=brain, url=CONFLUENCE_URL, target_path="project")
        # Don't create any file — source has no file on disk

        result = reconcile_sources(root=brain)
        assert result.updated == []
        assert result.not_found == [CONFLUENCE_CID]

    def test_multiple_sources_mixed(self, brain):
        add_source(root=brain, url=CONFLUENCE_URL, target_path="old-a")
        add_source(root=brain, url=CONFLUENCE_URL_2, target_path="old-b")

        # Move first source, leave second missing
        (brain / "knowledge" / "old-a" / "c12345-test-page.md").write_text("content")
        (brain / "knowledge" / "new-a").mkdir(parents=True)
        (brain / "knowledge" / "old-a" / "c12345-test-page.md").rename(
            brain / "knowledge" / "new-a" / "c12345-test-page.md"
        )

        result = reconcile_sources(root=brain)
        assert len(result.updated) == 1
        assert result.updated[0].canonical_id == CONFLUENCE_CID
        assert CONFLUENCE_CID_2 in result.not_found

    def test_noop_when_no_sources(self, brain):
        result = reconcile_sources(root=brain)
        assert result.updated == []
        assert result.not_found == []

    def test_bare_prefix_file_found(self, brain):
        """Files without a title slug (e.g. c12345.md) are also discovered."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="old")
        (brain / "knowledge" / "moved").mkdir(parents=True)
        (brain / "knowledge" / "moved" / "c12345.md").write_text("content")

        result = reconcile_sources(root=brain)
        assert len(result.updated) == 1
        assert result.updated[0].new_path == "moved"

    def test_no_update_when_same_path(self, brain):
        """If the file is found in same dir as target_path, no update needed."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="project")
        # File is where it should be — just with a different name variant
        (brain / "knowledge" / "project" / "c12345.md").write_text("content")

        result = reconcile_sources(root=brain)
        assert result.updated == []
        assert result.not_found == []

    def test_folder_rename_multiple_sources(self, brain):
        """Renaming a folder updates all sources that shared the same target_path."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="old-team")
        add_source(root=brain, url=CONFLUENCE_URL_2, target_path="old-team")
        add_source(root=brain, url=CONFLUENCE_URL_3, target_path="old-team")

        # Create files in old-team, then rename the folder
        old_dir = brain / "knowledge" / "old-team"
        old_dir.mkdir(parents=True, exist_ok=True)
        (old_dir / "c12345-test-page.md").write_text("content a")
        (old_dir / "c67890-other-page.md").write_text("content b")
        (old_dir / "c11111-third-page.md").write_text("content c")

        new_dir = brain / "knowledge" / "new-team"
        old_dir.rename(new_dir)

        result = reconcile_sources(root=brain)
        assert len(result.updated) == 3
        updated_cids = {e.canonical_id for e in result.updated}
        assert updated_cids == {CONFLUENCE_CID, CONFLUENCE_CID_2, CONFLUENCE_CID_3}
        for entry in result.updated:
            assert entry.old_path == "old-team"
            assert entry.new_path == "new-team"

    def test_unchanged_count(self, brain):
        """unchanged count reflects sources found at expected path."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="project")
        add_source(root=brain, url=CONFLUENCE_URL_2, target_path="project")
        (brain / "knowledge" / "project" / "c12345-test-page.md").write_text("content")
        (brain / "knowledge" / "project" / "c67890-other-page.md").write_text("content")

        result = reconcile_sources(root=brain)
        assert result.unchanged == 2
        assert result.updated == []
        assert result.not_found == []

    def test_unchanged_count_with_mixed_results(self, brain):
        """unchanged count works alongside updated and not_found."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="here")
        add_source(root=brain, url=CONFLUENCE_URL_2, target_path="old")
        add_source(root=brain, url=CONFLUENCE_URL_3, target_path="gone")

        # First source at expected path (unchanged)
        (brain / "knowledge" / "here" / "c12345-test-page.md").write_text("content")
        # Second source moved (updated)
        (brain / "knowledge" / "moved").mkdir(parents=True)
        (brain / "knowledge" / "moved" / "c67890-other-page.md").write_text("content")
        # Third source missing (not_found) — no file created

        result = reconcile_sources(root=brain)
        assert result.unchanged == 1
        assert len(result.updated) == 1
        assert result.updated[0].canonical_id == CONFLUENCE_CID_2
        assert CONFLUENCE_CID_3 in result.not_found


class TestMigrateSources:
    def test_migrates_legacy_attachments(self, brain):
        add_source(root=brain, url=CONFLUENCE_URL, target_path="project", include_attachments=True)
        target_dir = brain / "knowledge" / "project"

        # Create legacy _sync-context/attachments/ with a file
        legacy_att = target_dir / "_sync-context" / "attachments"
        legacy_att.mkdir(parents=True)
        (legacy_att / "a789-diagram.png").write_bytes(b"png-data")

        # Add relationship in DB
        save_relationship(
            brain,
            Relationship(
                parent_canonical_id=CONFLUENCE_CID,
                canonical_id="confluence-attachment:789",
                relationship_type="attachment",
                local_path="_sync-context/attachments/a789-diagram.png",
                source_type="confluence",
            ),
        )

        result = migrate_sources(root=brain)
        assert isinstance(result, MigrateResult)
        assert result.files_migrated == 1
        assert result.sources_migrated == 1

        # File at new location
        assert (target_dir / "_attachments" / "c12345" / "a789-diagram.png").read_bytes() == b"png-data"
        # Legacy dir gone
        assert not (target_dir / "_sync-context").exists()
        # DB updated
        rels = load_relationships_for_primary(brain, CONFLUENCE_CID)
        assert rels[0].local_path == "_attachments/c12345/a789-diagram.png"

    def test_noop_when_nothing_to_migrate(self, brain):
        add_source(root=brain, url=CONFLUENCE_URL, target_path="project")

        result = migrate_sources(root=brain)
        assert result.sources_migrated == 0
        assert result.files_migrated == 0
        assert result.dirs_cleaned == 0

    def test_remigrates_bare_id_attachments(self, brain):
        """Bare-ID _attachments/12345/ dirs are re-migrated to _attachments/c12345/."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="project", include_attachments=True)
        target_dir = brain / "knowledge" / "project"

        # Simulate earlier migration that used bare ID
        bare_dir = target_dir / "_attachments" / "12345"
        bare_dir.mkdir(parents=True)
        (bare_dir / "a789-diagram.png").write_bytes(b"png-data")

        save_relationship(
            brain,
            Relationship(
                parent_canonical_id=CONFLUENCE_CID,
                canonical_id="confluence-attachment:789",
                relationship_type="attachment",
                local_path="_attachments/12345/a789-diagram.png",
                source_type="confluence",
            ),
        )

        result = migrate_sources(root=brain)
        assert result.sources_migrated == 1
        assert result.files_migrated == 1

        # File at prefixed location
        assert (target_dir / "_attachments" / "c12345" / "a789-diagram.png").read_bytes() == b"png-data"
        # Bare dir gone
        assert not bare_dir.exists()
        # DB updated
        rels = load_relationships_for_primary(brain, CONFLUENCE_CID)
        assert rels[0].local_path == "_attachments/c12345/a789-diagram.png"

    def test_cleans_stale_insights_sync_context(self, brain):
        """Stale _sync-context/ in insights/ (from old regen) is cleaned up."""
        stale_dir = brain / "insights" / "area" / "_sync-context"
        stale_dir.mkdir(parents=True)
        (stale_dir / "summary.md").write_text("stale")

        result = migrate_sources(root=brain)
        assert result.dirs_cleaned >= 1
        assert not stale_dir.exists()


class TestInitBrain:
    @pytest.fixture(autouse=True)
    def isolate_config(self, tmp_path, monkeypatch):
        """Prevent init_brain from touching the real ~/.brain-sync/config.json."""
        config_dir = tmp_path / "fake-config"
        config_dir.mkdir()
        config_file = config_dir / "config.json"
        monkeypatch.setattr("brain_sync.config.CONFIG_DIR", config_dir)
        monkeypatch.setattr("brain_sync.config.CONFIG_FILE", config_file)
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
        monkeypatch.setattr("brain_sync.config.CONFIG_FILE", config_file)

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
        monkeypatch.setattr("brain_sync.config.CONFIG_FILE", config_file)

        result = add_source(url=CONFLUENCE_URL, target_path="project")
        assert result.canonical_id == CONFLUENCE_CID
        assert (brain / "knowledge" / "project").is_dir()
