from brain_sync.state import (
    DocumentState,
    OutputBinding,
    Relationship,
    SourceState,
    SyncState,
    count_relationships_for_doc,
    load_all_bindings,
    load_bindings_for_source,
    load_document,
    load_relationships_for_primary,
    load_state,
    prune_bindings,
    prune_db,
    prune_state,
    remove_document_if_orphaned,
    remove_relationship,
    save_bindings,
    save_document,
    save_relationship,
    save_state,
    source_key,
    source_key_for_entry,
    update_relationship_path,
)


class TestSourceKeyForEntry:
    def test_confluence_url(self):
        url = "https://test.atlassian.net/wiki/spaces/X/pages/12345/TestPage"
        result = source_key_for_entry(url)
        assert result == "confluence:12345"

    def test_google_doc_url(self):
        url = "https://docs.google.com/document/d/abc123/edit"
        result = source_key_for_entry(url)
        assert result == "gdoc:abc123"


class TestLegacySourceKey:
    def test_format(self):
        assert source_key("/a/manifest.yaml", "https://example.com") == "/a/manifest.yaml::https://example.com"


class TestStatePersistence:
    def test_save_and_load_round_trip(self, tmp_path):
        state = SyncState()
        state.sources["confluence:123"] = SourceState(
            canonical_id="confluence:123",
            source_url="https://example.com",
            source_type="confluence",
            last_checked_utc="2026-01-01T00:00:00+00:00",
            last_changed_utc="2026-01-01T00:00:00+00:00",
            current_interval_secs=3600,
            content_hash="abc123",
            metadata_fingerprint="42",
        )
        save_state(tmp_path, state)
        loaded = load_state(tmp_path)
        assert "confluence:123" in loaded.sources
        s = loaded.sources["confluence:123"]
        assert s.source_url == "https://example.com"
        assert s.content_hash == "abc123"
        assert s.metadata_fingerprint == "42"
        assert s.current_interval_secs == 3600

    def test_load_missing_db_returns_fresh(self, tmp_path):
        state = load_state(tmp_path)
        assert state.sources == {}
        assert state.version == 4

    def test_multiple_save_load_cycles(self, tmp_path):
        state = SyncState()
        state.sources["confluence:1"] = SourceState(
            canonical_id="confluence:1",
            source_url="u1",
            source_type="confluence",
        )
        save_state(tmp_path, state)

        state.sources["confluence:2"] = SourceState(
            canonical_id="confluence:2",
            source_url="u2",
            source_type="confluence",
        )
        save_state(tmp_path, state)

        loaded = load_state(tmp_path)
        assert "confluence:1" in loaded.sources
        assert "confluence:2" in loaded.sources

    def test_sqlite_file_created(self, tmp_path):
        state = SyncState()
        state.sources["confluence:1"] = SourceState(
            canonical_id="confluence:1",
            source_url="u",
            source_type="confluence",
        )
        save_state(tmp_path, state)
        assert (tmp_path / ".sync-state.sqlite").exists()


class TestPruneState:
    def test_removes_stale_keys(self):
        state = SyncState()
        state.sources["confluence:1"] = SourceState(
            canonical_id="confluence:1",
            source_url="u1",
            source_type="confluence",
        )
        state.sources["confluence:2"] = SourceState(
            canonical_id="confluence:2",
            source_url="u2",
            source_type="confluence",
        )
        prune_state(state, active_keys={"confluence:1"})
        assert "confluence:1" in state.sources
        assert "confluence:2" not in state.sources


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
        state.sources["confluence:1"] = SourceState(
            canonical_id="confluence:1",
            source_url="u",
            source_type="confluence",
            next_check_utc="2026-03-08T00:00:00+00:00",
            interval_seconds=3600,
        )
        save_state(tmp_path, state)
        loaded = load_state(tmp_path)
        s = loaded.sources["confluence:1"]
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
        doc.title = "New Title"
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
        state.sources["confluence:1"] = SourceState(
            canonical_id="confluence:1",
            source_url="u1",
            source_type="confluence",
        )
        state.sources["confluence:2"] = SourceState(
            canonical_id="confluence:2",
            source_url="u2",
            source_type="confluence",
        )
        save_state(tmp_path, state)

        prune_db(tmp_path, active_keys={"confluence:1"})

        loaded = load_state(tmp_path)
        assert "confluence:1" in loaded.sources
        assert "confluence:2" not in loaded.sources


class TestBindingsCrud:
    def test_save_and_load_bindings(self, tmp_path):
        save_state(tmp_path, SyncState())  # ensure DB
        bindings = [
            OutputBinding(
                canonical_id="confluence:100",
                manifest_path="/a/sync-manifest.yaml",
                target_file="page.md",
                include_links=True,
            ),
            OutputBinding(
                canonical_id="confluence:100",
                manifest_path="/b/sync-manifest.yaml",
                target_file="page.md",
            ),
        ]
        save_bindings(tmp_path, bindings)

        loaded = load_bindings_for_source(tmp_path, "confluence:100")
        assert len(loaded) == 2
        assert loaded[0].include_links is True
        assert loaded[1].include_links is False

    def test_load_all_bindings(self, tmp_path):
        save_state(tmp_path, SyncState())
        bindings = [
            OutputBinding(canonical_id="confluence:100", manifest_path="/a/m.yaml", target_file="a.md"),
            OutputBinding(canonical_id="confluence:200", manifest_path="/b/m.yaml", target_file="b.md"),
        ]
        save_bindings(tmp_path, bindings)

        all_b = load_all_bindings(tmp_path)
        assert "confluence:100" in all_b
        assert "confluence:200" in all_b
        assert len(all_b["confluence:100"]) == 1
        assert len(all_b["confluence:200"]) == 1

    def test_prune_bindings(self, tmp_path):
        save_state(tmp_path, SyncState())
        bindings = [
            OutputBinding(canonical_id="confluence:100", manifest_path="/a/m.yaml", target_file="a.md"),
            OutputBinding(canonical_id="confluence:200", manifest_path="/b/m.yaml", target_file="b.md"),
        ]
        save_bindings(tmp_path, bindings)

        prune_bindings(tmp_path, active_canonical_ids={"confluence:100"})

        loaded = load_all_bindings(tmp_path)
        assert "confluence:100" in loaded
        assert "confluence:200" not in loaded

    def test_save_replaces_all(self, tmp_path):
        save_state(tmp_path, SyncState())
        save_bindings(tmp_path, [
            OutputBinding(canonical_id="confluence:100", manifest_path="/a/m.yaml", target_file="a.md"),
        ])
        # Save new set — old bindings should be gone
        save_bindings(tmp_path, [
            OutputBinding(canonical_id="confluence:200", manifest_path="/b/m.yaml", target_file="b.md"),
        ])

        all_b = load_all_bindings(tmp_path)
        assert "confluence:100" not in all_b
        assert "confluence:200" in all_b


class TestSchemaV3Migration:
    def test_v2_to_v3_migration(self, tmp_path):
        """Simulate a v2 DB and verify migration to v3."""
        import sqlite3
        db_path = tmp_path / ".sync-state.sqlite"
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")

        # Create v1 schema
        conn.executescript("""
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE sources (
                source_key TEXT PRIMARY KEY,
                manifest_path TEXT NOT NULL,
                source_url TEXT NOT NULL,
                target_file TEXT NOT NULL,
                source_type TEXT NOT NULL,
                last_checked_utc TEXT,
                last_changed_utc TEXT,
                current_interval_secs INTEGER NOT NULL DEFAULT 3600,
                content_hash TEXT,
                metadata_fingerprint TEXT
            );
        """)
        # Upgrade to v2
        conn.executescript("""
            CREATE TABLE documents (
                canonical_id TEXT PRIMARY KEY,
                source_type TEXT NOT NULL,
                url TEXT NOT NULL,
                title TEXT,
                last_checked_utc TEXT,
                last_changed_utc TEXT,
                content_hash TEXT,
                metadata_fingerprint TEXT,
                mime_type TEXT
            );
            CREATE TABLE relationships (
                parent_canonical_id TEXT NOT NULL,
                canonical_id TEXT NOT NULL,
                relationship_type TEXT NOT NULL,
                local_path TEXT NOT NULL,
                source_type TEXT NOT NULL,
                first_seen_utc TEXT,
                last_seen_utc TEXT,
                PRIMARY KEY (parent_canonical_id, canonical_id)
            );
        """)
        conn.execute("ALTER TABLE sources ADD COLUMN next_check_utc TEXT")
        conn.execute("ALTER TABLE sources ADD COLUMN interval_seconds INTEGER")
        conn.execute("INSERT INTO meta (key, value) VALUES ('schema_version', '2')")

        # Insert v2 data
        conn.execute(
            "INSERT INTO sources VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "/proj/sync-manifest.yaml::https://test.atlassian.net/wiki/spaces/X/pages/12345/Page",
                "/proj/sync-manifest.yaml",
                "https://test.atlassian.net/wiki/spaces/X/pages/12345/Page",
                "page.md",
                "confluence",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
                1800,
                "hash123",
                "5",
                "2026-01-01T01:00:00+00:00",
                3600,
            ),
        )
        conn.commit()
        conn.close()

        # Now load_state triggers migration
        state = load_state(tmp_path)

        assert "confluence:12345" in state.sources
        ss = state.sources["confluence:12345"]
        assert ss.source_url == "https://test.atlassian.net/wiki/spaces/X/pages/12345/Page"
        assert ss.content_hash == "hash123"
        assert ss.metadata_fingerprint == "5"

        # Bindings should have been created
        bindings = load_bindings_for_source(tmp_path, "confluence:12345")
        assert len(bindings) == 1
        assert bindings[0].manifest_path == "/proj/sync-manifest.yaml"
        assert bindings[0].target_file == "page.md"

    def test_v2_to_v3_deduplication(self, tmp_path):
        """Two v2 rows for the same page resolve to one source row."""
        import sqlite3
        db_path = tmp_path / ".sync-state.sqlite"
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")

        conn.executescript("""
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE sources (
                source_key TEXT PRIMARY KEY,
                manifest_path TEXT NOT NULL,
                source_url TEXT NOT NULL,
                target_file TEXT NOT NULL,
                source_type TEXT NOT NULL,
                last_checked_utc TEXT,
                last_changed_utc TEXT,
                current_interval_secs INTEGER NOT NULL DEFAULT 3600,
                content_hash TEXT,
                metadata_fingerprint TEXT
            );
            CREATE TABLE documents (
                canonical_id TEXT PRIMARY KEY,
                source_type TEXT NOT NULL,
                url TEXT NOT NULL,
                title TEXT,
                last_checked_utc TEXT,
                last_changed_utc TEXT,
                content_hash TEXT,
                metadata_fingerprint TEXT,
                mime_type TEXT
            );
            CREATE TABLE relationships (
                parent_canonical_id TEXT NOT NULL,
                canonical_id TEXT NOT NULL,
                relationship_type TEXT NOT NULL,
                local_path TEXT NOT NULL,
                source_type TEXT NOT NULL,
                first_seen_utc TEXT,
                last_seen_utc TEXT,
                PRIMARY KEY (parent_canonical_id, canonical_id)
            );
        """)
        conn.execute("ALTER TABLE sources ADD COLUMN next_check_utc TEXT")
        conn.execute("ALTER TABLE sources ADD COLUMN interval_seconds INTEGER")
        conn.execute("INSERT INTO meta (key, value) VALUES ('schema_version', '2')")

        url = "https://test.atlassian.net/wiki/spaces/X/pages/99999/Page"

        # Row A — older, has hash
        conn.execute(
            "INSERT INTO sources VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "/a/sync-manifest.yaml::" + url,
                "/a/sync-manifest.yaml", url, "a.md", "confluence",
                "2026-01-01T00:00:00+00:00", None, 1800, "hashA", None, None, None,
            ),
        )
        # Row B — newer, no hash
        conn.execute(
            "INSERT INTO sources VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "/b/sync-manifest.yaml::" + url,
                "/b/sync-manifest.yaml", url, "b.md", "confluence",
                "2026-02-01T00:00:00+00:00", None, 1800, None, None, None, None,
            ),
        )
        conn.commit()
        conn.close()

        state = load_state(tmp_path)
        # Should have exactly one source row
        assert len(state.sources) == 1
        assert "confluence:99999" in state.sources

        # Both bindings should exist
        bindings = load_bindings_for_source(tmp_path, "confluence:99999")
        assert len(bindings) == 2
        manifest_paths = {b.manifest_path for b in bindings}
        assert "/a/sync-manifest.yaml" in manifest_paths
        assert "/b/sync-manifest.yaml" in manifest_paths


class TestSchemaV4Migration:
    def test_v3_to_v4_adds_unique_url(self, tmp_path):
        """v3 DB migrates to v4: documents get UNIQUE(url)."""
        import sqlite3
        db_path = tmp_path / ".sync-state.sqlite"
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")

        # Create v3 schema directly
        conn.executescript("""
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE sources (
                canonical_id TEXT PRIMARY KEY,
                source_url TEXT NOT NULL,
                source_type TEXT NOT NULL,
                last_checked_utc TEXT,
                last_changed_utc TEXT,
                current_interval_secs INTEGER NOT NULL DEFAULT 1800,
                content_hash TEXT,
                metadata_fingerprint TEXT,
                next_check_utc TEXT,
                interval_seconds INTEGER
            );
            CREATE TABLE documents (
                canonical_id TEXT PRIMARY KEY,
                source_type TEXT NOT NULL,
                url TEXT NOT NULL,
                title TEXT,
                last_checked_utc TEXT,
                last_changed_utc TEXT,
                content_hash TEXT,
                metadata_fingerprint TEXT,
                mime_type TEXT
            );
            CREATE TABLE relationships (
                parent_canonical_id TEXT NOT NULL,
                canonical_id TEXT NOT NULL,
                relationship_type TEXT NOT NULL,
                local_path TEXT NOT NULL,
                source_type TEXT NOT NULL,
                first_seen_utc TEXT,
                last_seen_utc TEXT,
                PRIMARY KEY (parent_canonical_id, canonical_id)
            );
            CREATE TABLE source_bindings (
                canonical_id TEXT NOT NULL,
                manifest_path TEXT NOT NULL,
                target_file TEXT NOT NULL,
                include_links INTEGER NOT NULL DEFAULT 0,
                include_children INTEGER NOT NULL DEFAULT 0,
                include_attachments INTEGER NOT NULL DEFAULT 0,
                link_depth INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (canonical_id, manifest_path)
            );
        """)
        conn.execute("INSERT INTO meta (key, value) VALUES ('schema_version', '3')")

        # Insert test data
        conn.execute(
            "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("confluence:100", "confluence",
             "https://x.atlassian.net/wiki/spaces/S/pages/100", "Page", None, None, None, None, None),
        )
        conn.execute(
            "INSERT INTO relationships VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("confluence:1", "confluence:100", "link", "linked/c100.md", "confluence", None, None),
        )
        conn.commit()
        conn.close()

        # load_state triggers v3→v4 migration
        state = load_state(tmp_path)

        # Verify schema version is 4
        conn = sqlite3.connect(str(db_path))
        version = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
        assert version == "4"

        # Data preserved
        rels = load_relationships_for_primary(tmp_path, "confluence:1")
        assert len(rels) == 1
        assert rels[0].canonical_id == "confluence:100"

        doc = load_document(tmp_path, "confluence:100")
        assert doc is not None
        assert doc.title == "Page"

        conn.close()

    def test_documents_url_unique_enforced(self, tmp_path):
        """After v4, inserting duplicate URL into documents raises."""
        save_state(tmp_path, SyncState())  # creates v4 DB

        doc1 = DocumentState(
            canonical_id="confluence:100",
            source_type="confluence",
            url="https://x.atlassian.net/wiki/spaces/S/pages/100",
        )
        save_document(tmp_path, doc1)

        # Different canonical_id, same URL — should fail
        doc2 = DocumentState(
            canonical_id="confluence:200",
            source_type="confluence",
            url="https://x.atlassian.net/wiki/spaces/S/pages/100",
        )
        import pytest
        with pytest.raises(Exception):
            save_document(tmp_path, doc2)
