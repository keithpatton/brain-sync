from brain_sync.state import (
    DocumentState,
    Relationship,
    SourceState,
    SyncState,
    count_relationships_for_doc,
    load_document,
    load_relationships_for_primary,
    load_state,
    prune_db,
    prune_state,
    remove_document_if_orphaned,
    remove_relationship,
    save_document,
    save_relationship,
    save_state,
    source_key,
    update_relationship_path,
)


class TestSourceKey:
    def test_format(self):
        assert source_key("/a/manifest.yaml", "https://example.com") == "/a/manifest.yaml::https://example.com"


class TestStatePersistence:
    def test_save_and_load_round_trip(self, tmp_path):
        state = SyncState()
        state.sources["k1"] = SourceState(
            manifest_path="/a/m.yaml",
            source_url="https://example.com",
            target_file="out.md",
            source_type="confluence",
            last_checked_utc="2026-01-01T00:00:00+00:00",
            last_changed_utc="2026-01-01T00:00:00+00:00",
            current_interval_secs=3600,
            content_hash="abc123",
            metadata_fingerprint="42",
        )
        save_state(tmp_path, state)
        loaded = load_state(tmp_path)
        assert "k1" in loaded.sources
        s = loaded.sources["k1"]
        assert s.source_url == "https://example.com"
        assert s.content_hash == "abc123"
        assert s.metadata_fingerprint == "42"
        assert s.current_interval_secs == 3600

    def test_load_missing_db_returns_fresh(self, tmp_path):
        state = load_state(tmp_path)
        assert state.sources == {}
        assert state.version == 2

    def test_multiple_save_load_cycles(self, tmp_path):
        state = SyncState()
        state.sources["a"] = SourceState(
            manifest_path="m", source_url="u1", target_file="f1", source_type="confluence"
        )
        save_state(tmp_path, state)

        state.sources["b"] = SourceState(
            manifest_path="m", source_url="u2", target_file="f2", source_type="confluence"
        )
        save_state(tmp_path, state)

        loaded = load_state(tmp_path)
        assert "a" in loaded.sources
        assert "b" in loaded.sources

    def test_sqlite_file_created(self, tmp_path):
        state = SyncState()
        state.sources["k1"] = SourceState(
            manifest_path="m", source_url="u", target_file="f", source_type="confluence"
        )
        save_state(tmp_path, state)
        assert (tmp_path / ".sync-state.sqlite").exists()


class TestPruneState:
    def test_removes_stale_keys(self):
        state = SyncState()
        state.sources["keep"] = SourceState(
            manifest_path="m", source_url="u1", target_file="f1", source_type="confluence"
        )
        state.sources["remove"] = SourceState(
            manifest_path="m", source_url="u2", target_file="f2", source_type="confluence"
        )
        prune_state(state, active_keys={"keep"})
        assert "keep" in state.sources
        assert "remove" not in state.sources


class TestSchemaV2Migration:
    def test_new_db_has_documents_table(self, tmp_path):
        save_state(tmp_path, SyncState())  # triggers schema creation
        doc = DocumentState(
            canonical_id="confluence:123",
            source_type="confluence",
            url="https://x.atlassian.net/wiki/spaces/S/pages/123",
        )
        save_document(tmp_path, doc)
        loaded = load_document(tmp_path, "confluence:123")
        assert loaded is not None
        assert loaded.url == doc.url

    def test_next_check_utc_persisted(self, tmp_path):
        state = SyncState()
        state.sources["k1"] = SourceState(
            manifest_path="m", source_url="u", target_file="f",
            source_type="confluence",
            next_check_utc="2026-03-08T00:00:00+00:00",
            interval_seconds=3600,
        )
        save_state(tmp_path, state)
        loaded = load_state(tmp_path)
        s = loaded.sources["k1"]
        assert s.next_check_utc == "2026-03-08T00:00:00+00:00"
        assert s.interval_seconds == 3600


class TestDocumentCrud:
    def test_save_and_load(self, tmp_path):
        doc = DocumentState(
            canonical_id="confluence:456",
            source_type="confluence",
            url="https://x.atlassian.net/wiki/spaces/S/pages/456",
            title="Test Page",
            content_hash="hash1",
        )
        save_document(tmp_path, doc)
        loaded = load_document(tmp_path, "confluence:456")
        assert loaded is not None
        assert loaded.title == "Test Page"
        assert loaded.content_hash == "hash1"

    def test_upsert_updates(self, tmp_path):
        doc = DocumentState(
            canonical_id="confluence:456",
            source_type="confluence",
            url="https://x.atlassian.net/wiki/spaces/S/pages/456",
            title="Old Title",
        )
        save_document(tmp_path, doc)
        doc.title = "New Title"  # DocumentState is not frozen
        save_document(tmp_path, doc)
        loaded = load_document(tmp_path, "confluence:456")
        assert loaded.title == "New Title"

    def test_load_nonexistent(self, tmp_path):
        save_state(tmp_path, SyncState())  # ensure DB exists
        assert load_document(tmp_path, "nonexistent") is None


class TestRelationshipCrud:
    def test_save_and_load(self, tmp_path):
        save_state(tmp_path, SyncState())
        rel = Relationship(
            parent_canonical_id="confluence:100",
            canonical_id="confluence:200",
            relationship_type="link",
            local_path="_sync-context/linked/c200-page.md",
            source_type="confluence",
            first_seen_utc="2026-03-07T00:00:00+00:00",
            last_seen_utc="2026-03-07T00:00:00+00:00",
        )
        save_relationship(tmp_path, rel)
        rels = load_relationships_for_primary(tmp_path, "confluence:100")
        assert len(rels) == 1
        assert rels[0].canonical_id == "confluence:200"

    def test_remove_relationship(self, tmp_path):
        save_state(tmp_path, SyncState())
        rel = Relationship(
            parent_canonical_id="confluence:100",
            canonical_id="confluence:200",
            relationship_type="link",
            local_path="path",
            source_type="confluence",
        )
        save_relationship(tmp_path, rel)
        remove_relationship(tmp_path, "confluence:100", "confluence:200")
        rels = load_relationships_for_primary(tmp_path, "confluence:100")
        assert len(rels) == 0

    def test_count_relationships(self, tmp_path):
        save_state(tmp_path, SyncState())
        for parent_id in ["confluence:100", "confluence:101"]:
            save_relationship(tmp_path, Relationship(
                parent_canonical_id=parent_id,
                canonical_id="confluence:200",
                relationship_type="link",
                local_path="path",
                source_type="confluence",
            ))
        assert count_relationships_for_doc(tmp_path, "confluence:200") == 2

    def test_remove_document_if_orphaned(self, tmp_path):
        doc = DocumentState(
            canonical_id="confluence:200",
            source_type="confluence",
            url="https://x.atlassian.net/wiki/spaces/S/pages/200",
        )
        save_document(tmp_path, doc)
        # No relationships → should be removed
        assert remove_document_if_orphaned(tmp_path, "confluence:200") is True
        assert load_document(tmp_path, "confluence:200") is None

    def test_remove_document_not_orphaned(self, tmp_path):
        doc = DocumentState(
            canonical_id="confluence:200",
            source_type="confluence",
            url="https://x.atlassian.net/wiki/spaces/S/pages/200",
        )
        save_document(tmp_path, doc)
        save_relationship(tmp_path, Relationship(
            parent_canonical_id="confluence:100",
            canonical_id="confluence:200",
            relationship_type="link",
            local_path="path",
            source_type="confluence",
        ))
        assert remove_document_if_orphaned(tmp_path, "confluence:200") is False
        assert load_document(tmp_path, "confluence:200") is not None


class TestUpdateRelationshipPath:
    def test_updates_path(self, tmp_path):
        save_state(tmp_path, SyncState())
        save_relationship(tmp_path, Relationship(
            parent_canonical_id="confluence:100",
            canonical_id="confluence:200",
            relationship_type="link",
            local_path="old/path.md",
            source_type="confluence",
        ))
        update_relationship_path(tmp_path, "confluence:100", "confluence:200", "new/path.md")
        rels = load_relationships_for_primary(tmp_path, "confluence:100")
        assert rels[0].local_path == "new/path.md"


class TestPruneDb:
    def test_removes_stale_rows(self, tmp_path):
        state = SyncState()
        state.sources["keep"] = SourceState(
            manifest_path="m", source_url="u1", target_file="f1", source_type="confluence"
        )
        state.sources["remove"] = SourceState(
            manifest_path="m", source_url="u2", target_file="f2", source_type="confluence"
        )
        save_state(tmp_path, state)

        prune_db(tmp_path, active_keys={"keep"})

        loaded = load_state(tmp_path)
        assert "keep" in loaded.sources
        assert "remove" not in loaded.sources
