import pytest

from brain_sync.state import (
    DocumentState,
    InsightState,
    Relationship,
    SourceState,
    SyncState,
    acquire_regen_ownership,
    count_relationships_for_doc,
    delete_insight_state,
    load_document,
    load_insight_state,
    load_relationships_for_primary,
    load_state,
    prune_db,
    remove_document_if_orphaned,
    remove_relationship,
    save_document,
    save_insight_state,
    save_relationship,
    save_state,
    update_insight_path,
)

pytestmark = pytest.mark.unit


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
        assert state.version == 20

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
            source_type="confluence",
        )
        save_relationship(tmp_path, rel)
        remove_relationship(tmp_path, "confluence:100", "confluence:200")
        rels = load_relationships_for_primary(tmp_path, "confluence:100")
        assert len(rels) == 0

    def test_count_relationships(self, tmp_path):
        save_state(tmp_path, SyncState())
        for parent_id in ["confluence:100", "confluence:101"]:
            save_relationship(
                tmp_path,
                Relationship(
                    parent_canonical_id=parent_id,
                    canonical_id="confluence:200",
                    relationship_type="link",
                    source_type="confluence",
                ),
            )
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
        save_relationship(
            tmp_path,
            Relationship(
                parent_canonical_id="confluence:100",
                canonical_id="confluence:200",
                relationship_type="link",
                source_type="confluence",
            ),
        )
        assert remove_document_if_orphaned(tmp_path, "confluence:200") is False
        assert load_document(tmp_path, "confluence:200") is not None


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
                "/a/sync-manifest.yaml",
                url,
                "a.md",
                "confluence",
                "2026-01-01T00:00:00+00:00",
                None,
                1800,
                "hashA",
                None,
                None,
                None,
            ),
        )
        # Row B — newer, no hash
        conn.execute(
            "INSERT INTO sources VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "/b/sync-manifest.yaml::" + url,
                "/b/sync-manifest.yaml",
                url,
                "b.md",
                "confluence",
                "2026-02-01T00:00:00+00:00",
                None,
                1800,
                None,
                None,
                None,
                None,
            ),
        )
        conn.commit()
        conn.close()

        state = load_state(tmp_path)
        # Should have exactly one source row
        assert len(state.sources) == 1
        assert "confluence:99999" in state.sources


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
            (
                "confluence:100",
                "confluence",
                "https://x.atlassian.net/wiki/spaces/S/pages/100",
                "Page",
                None,
                None,
                None,
                None,
                None,
            ),
        )
        conn.execute(
            "INSERT INTO relationships VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "confluence:1",
                "confluence-attachment:100",
                "attachment",
                "attachments/a100.png",
                "confluence",
                None,
                None,
            ),
        )
        conn.commit()
        conn.close()

        # load_state triggers v3→v4→v5 migration
        load_state(tmp_path)

        # Verify schema version after full migration chain
        conn = sqlite3.connect(str(db_path))
        version = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
        assert version == "20"

        # Data preserved
        rels = load_relationships_for_primary(tmp_path, "confluence:1")
        assert len(rels) == 1
        assert rels[0].canonical_id == "confluence-attachment:100"

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
        import sqlite3

        import pytest

        with pytest.raises(sqlite3.IntegrityError):
            save_document(tmp_path, doc2)


class TestInsightStatePathNormalization:
    """Verify that knowledge_path is always stored with forward slashes."""

    def test_save_normalizes_backslashes(self, tmp_path):
        save_insight_state(
            tmp_path,
            InsightState(
                knowledge_path="initiatives\\B4B\\Platform PRD",
                content_hash="abc",
                summary_hash="def",
            ),
        )
        loaded = load_insight_state(tmp_path, "initiatives/B4B/Platform PRD")
        assert loaded is not None
        assert loaded.knowledge_path == "initiatives/B4B/Platform PRD"

    def test_load_normalizes_query(self, tmp_path):
        save_insight_state(
            tmp_path,
            InsightState(
                knowledge_path="initiatives/B4B/Platform PRD",
                content_hash="abc",
                summary_hash="def",
            ),
        )
        # Query with backslashes should still find it
        loaded = load_insight_state(tmp_path, "initiatives\\B4B\\Platform PRD")
        assert loaded is not None

    def test_delete_normalizes_path(self, tmp_path):
        save_insight_state(
            tmp_path,
            InsightState(
                knowledge_path="teams/product",
                content_hash="abc",
                summary_hash="def",
            ),
        )
        delete_insight_state(tmp_path, "teams\\product")
        assert load_insight_state(tmp_path, "teams/product") is None

    def test_update_normalizes_paths(self, tmp_path):
        save_insight_state(
            tmp_path,
            InsightState(
                knowledge_path="old/path",
                content_hash="abc",
                summary_hash="def",
            ),
        )
        update_insight_path(tmp_path, "old\\path", "new\\path")
        assert load_insight_state(tmp_path, "old/path") is None
        assert load_insight_state(tmp_path, "new/path") is not None


class TestDataclassPathNormalization:
    """Verify _PathNormalized mixin normalizes on construction and mutation."""

    def test_insight_state_normalizes_on_construction(self):
        s = InsightState(knowledge_path="a\\b\\c")
        assert s.knowledge_path == "a/b/c"

    def test_insight_state_normalizes_on_mutation(self):
        s = InsightState(knowledge_path="a/b")
        s.knowledge_path = "x\\y\\z"
        assert s.knowledge_path == "x/y/z"

    def test_source_state_normalizes_target_path(self):
        s = SourceState(canonical_id="x", source_url="u", source_type="t", target_path="a\\b")
        assert s.target_path == "a/b"

    def test_source_state_normalizes_on_mutation(self):
        s = SourceState(canonical_id="x", source_url="u", source_type="t", target_path="a/b")
        s.target_path = "c\\d"
        assert s.target_path == "c/d"

    def test_mixed_separators(self):
        s = InsightState(knowledge_path="a\\b/c\\d")
        assert s.knowledge_path == "a/b/c/d"

    def test_already_normalized_is_noop(self):
        s = InsightState(knowledge_path="a/b/c")
        assert s.knowledge_path == "a/b/c"

    def test_idempotent(self):
        s = InsightState(knowledge_path="a\\b/c")
        s.knowledge_path = s.knowledge_path
        assert s.knowledge_path == "a/b/c"

    def test_path_object_on_construction(self):
        from pathlib import PurePosixPath, PureWindowsPath

        s = InsightState(knowledge_path=PureWindowsPath("a\\b\\c"))
        assert s.knowledge_path == "a/b/c"

        s2 = InsightState(knowledge_path=PurePosixPath("a/b/c"))
        assert s2.knowledge_path == "a/b/c"

    def test_path_object_on_mutation(self):
        from pathlib import PureWindowsPath

        s = InsightState(knowledge_path="x/y")
        s.knowledge_path = PureWindowsPath("a\\b")
        assert s.knowledge_path == "a/b"


class TestAcquireRegenOwnership:
    """Tests for transactional regen ownership acquisition."""

    def test_acquire_fresh_path(self, tmp_path):
        """Acquiring ownership on a new path should succeed."""
        save_state(tmp_path, SyncState())  # ensure DB
        assert acquire_regen_ownership(tmp_path, "area/foo", "owner-1") is True
        loaded = load_insight_state(tmp_path, "area/foo")
        assert loaded is not None
        assert loaded.owner_id == "owner-1"
        assert loaded.regen_status == "running"

    def test_acquire_already_owned_by_same_owner(self, tmp_path):
        """Re-acquiring ownership by the same owner should succeed."""
        save_state(tmp_path, SyncState())
        assert acquire_regen_ownership(tmp_path, "area/foo", "owner-1") is True
        assert acquire_regen_ownership(tmp_path, "area/foo", "owner-1") is True

    def test_acquire_owned_by_other_fails(self, tmp_path):
        """Acquiring ownership already held by another owner should fail."""
        save_state(tmp_path, SyncState())
        assert acquire_regen_ownership(tmp_path, "area/foo", "owner-1") is True
        assert acquire_regen_ownership(tmp_path, "area/foo", "owner-2") is False

    def test_acquire_stale_ownership_reclaimed(self, tmp_path):
        """Stale ownership from a crashed process should be reclaimed."""
        from datetime import UTC, datetime, timedelta

        save_state(tmp_path, SyncState())
        # Insert a row that appears stale (started long ago)
        stale_time = (datetime.now(UTC) - timedelta(seconds=1200)).isoformat()
        save_insight_state(
            tmp_path,
            InsightState(
                knowledge_path="area/foo",
                regen_status="running",
                regen_started_utc=stale_time,
                owner_id="crashed-owner",
            ),
        )
        # New owner should be able to reclaim it (stale_threshold_secs=600)
        assert acquire_regen_ownership(tmp_path, "area/foo", "owner-2", stale_threshold_secs=600.0) is True
        loaded = load_insight_state(tmp_path, "area/foo")
        assert loaded.owner_id == "owner-2"

    def test_acquire_idle_path_with_existing_state(self, tmp_path):
        """Acquiring ownership on an idle path with existing state should succeed."""
        save_state(tmp_path, SyncState())
        save_insight_state(
            tmp_path,
            InsightState(knowledge_path="area/foo", regen_status="idle"),
        )
        assert acquire_regen_ownership(tmp_path, "area/foo", "owner-1") is True


class TestPathNormalizationOnLoad:
    """Verify that load paths are normalized end-to-end."""

    def test_backslash_row_normalizes_via_load_all(self, tmp_path):
        """Raw SQL insert with backslashes is found by load_all and normalized."""
        from brain_sync.state import _connect, load_all_insight_states

        conn = _connect(tmp_path)
        conn.execute(
            "INSERT INTO insight_state (knowledge_path, regen_status) VALUES (?, 'idle')",
            ("initiatives\\B4B\\Platform PRD",),
        )
        conn.commit()
        conn.close()

        # load_all doesn't filter by path, so it returns the row.
        # The _PathNormalized mixin normalizes on construction.
        all_states = load_all_insight_states(tmp_path)
        matching = [s for s in all_states if s.knowledge_path == "initiatives/B4B/Platform PRD"]
        assert len(matching) == 1

    def test_save_with_backslashes_loads_with_forward_slashes(self, tmp_path):
        """Insert with backslashes via save API, load with forward slashes."""
        save_insight_state(
            tmp_path,
            InsightState(knowledge_path="a\\b\\c", regen_status="idle"),
        )
        loaded = load_insight_state(tmp_path, "a/b/c")
        assert loaded is not None
        assert loaded.knowledge_path == "a/b/c"


class TestSchemaV15V16Migration:
    """Tests for token_events table (v15) and insight_state cleanup (v16)."""

    def test_fresh_db_has_token_events_table(self, tmp_path):
        """Fresh DB includes token_events with indexes."""
        from brain_sync.state import _connect

        conn = _connect(tmp_path)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "token_events" in tables

        # Check indexes exist
        indexes = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()}
        assert "idx_token_events_session" in indexes
        assert "idx_token_events_resource" in indexes
        assert "idx_token_events_resource_session" in indexes
        conn.close()

    def test_fresh_db_insight_state_no_token_columns(self, tmp_path):
        """Fresh DB insight_state has no token columns."""
        from brain_sync.state import _connect

        conn = _connect(tmp_path)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(insight_state)").fetchall()}
        assert "input_tokens" not in cols
        assert "output_tokens" not in cols
        assert "num_turns" not in cols
        assert "model" not in cols
        # These should still exist
        assert "knowledge_path" in cols
        assert "content_hash" in cols
        assert "regen_status" in cols
        assert "owner_id" in cols
        assert "error_reason" in cols
        conn.close()

    def test_v14_to_v16_migration(self, tmp_path):
        """v14 DB migrates to v16: creates token_events, rebuilds insight_state."""
        import sqlite3

        db_path = tmp_path / ".sync-state.sqlite"
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")

        # Create v14 schema with token columns in insight_state
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
                interval_seconds INTEGER,
                target_path TEXT NOT NULL DEFAULT '',
                fetch_children INTEGER NOT NULL DEFAULT 0,
                sync_attachments INTEGER NOT NULL DEFAULT 0,
                child_path TEXT
            );
            CREATE TABLE documents (
                canonical_id TEXT PRIMARY KEY,
                source_type TEXT NOT NULL,
                url TEXT NOT NULL UNIQUE,
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
            CREATE TABLE insight_state (
                knowledge_path TEXT PRIMARY KEY,
                content_hash TEXT,
                summary_hash TEXT,
                regen_started_utc TEXT,
                last_regen_utc TEXT,
                regen_status TEXT NOT NULL DEFAULT 'idle',
                input_tokens INTEGER,
                output_tokens INTEGER,
                num_turns INTEGER,
                model TEXT,
                owner_id TEXT,
                error_reason TEXT
            );
        """)
        conn.execute("INSERT INTO meta (key, value) VALUES ('schema_version', '14')")
        # Insert test data to verify preservation
        conn.execute(
            "INSERT INTO insight_state "
            "(knowledge_path, content_hash, regen_status, input_tokens, output_tokens, num_turns, model, owner_id) "
            "VALUES ('area/foo', 'hash123', 'idle', 1000, 200, 3, 'claude-sonnet', NULL)"
        )
        conn.commit()
        conn.close()

        # Trigger migration via _connect
        from brain_sync.state import _connect

        conn = _connect(tmp_path)

        # Check version
        version = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
        assert version == "20"

        # token_events table exists
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "token_events" in tables

        # insight_state no longer has token columns
        cols = {r[1] for r in conn.execute("PRAGMA table_info(insight_state)").fetchall()}
        assert "input_tokens" not in cols
        assert "output_tokens" not in cols
        assert "num_turns" not in cols
        assert "model" not in cols

        # Data preserved (non-token fields)
        row = conn.execute(
            "SELECT knowledge_path, content_hash, regen_status FROM insight_state WHERE knowledge_path = 'area/foo'"
        ).fetchone()
        assert row is not None
        assert row[0] == "area/foo"
        assert row[1] == "hash123"
        assert row[2] == "idle"

        conn.close()

    def test_insight_state_dataclass_no_token_fields(self):
        """InsightState dataclass has no token-related fields."""
        import dataclasses

        field_names = {f.name for f in dataclasses.fields(InsightState)}
        assert "input_tokens" not in field_names
        assert "output_tokens" not in field_names
        assert "num_turns" not in field_names
        assert "model" not in field_names


class TestSchemaV17Migration:
    """Tests for dropping local_path from relationships (v17)."""

    def test_v16_to_v17_migration(self, tmp_path):
        """v16 DB migrates to v17: local_path column is dropped from relationships."""
        import sqlite3

        db_path = tmp_path / ".sync-state.sqlite"
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")

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
                interval_seconds INTEGER,
                target_path TEXT NOT NULL DEFAULT '',
                fetch_children INTEGER NOT NULL DEFAULT 0,
                sync_attachments INTEGER NOT NULL DEFAULT 0,
                child_path TEXT
            );
            CREATE TABLE documents (
                canonical_id TEXT PRIMARY KEY,
                source_type TEXT NOT NULL,
                url TEXT NOT NULL UNIQUE,
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
            CREATE TABLE insight_state (
                knowledge_path TEXT PRIMARY KEY,
                content_hash TEXT,
                summary_hash TEXT,
                regen_started_utc TEXT,
                last_regen_utc TEXT,
                regen_status TEXT NOT NULL DEFAULT 'idle',
                owner_id TEXT,
                error_reason TEXT
            );
            CREATE TABLE token_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                operation_type TEXT NOT NULL,
                resource_type TEXT,
                resource_id TEXT,
                is_chunk INTEGER NOT NULL DEFAULT 0,
                model TEXT,
                input_tokens INTEGER,
                output_tokens INTEGER,
                total_tokens INTEGER,
                duration_ms INTEGER,
                num_turns INTEGER,
                success INTEGER NOT NULL,
                created_utc TEXT NOT NULL
            );
        """)
        conn.execute("INSERT INTO meta (key, value) VALUES ('schema_version', '16')")
        conn.execute(
            "INSERT INTO relationships "
            "(parent_canonical_id, canonical_id, relationship_type, local_path, source_type) "
            "VALUES ('confluence:100', 'confluence-attachment:789', 'attachment', "
            "'_attachments/c100/a789-diagram.png', 'confluence')"
        )
        conn.commit()
        conn.close()

        from brain_sync.state import _connect

        conn = _connect(tmp_path)

        # Version updated
        version = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
        assert version == "20"

        # local_path column is gone
        cols = {r[1] for r in conn.execute("PRAGMA table_info(relationships)").fetchall()}
        assert "local_path" not in cols
        assert "parent_canonical_id" in cols
        assert "canonical_id" in cols
        assert "source_type" in cols

        # Relationship data preserved (minus local_path)
        row = conn.execute(
            "SELECT parent_canonical_id, canonical_id, relationship_type, source_type FROM relationships"
        ).fetchone()
        assert row is not None
        assert row == ("confluence:100", "confluence-attachment:789", "attachment", "confluence")

        conn.close()

    def test_fresh_db_has_no_local_path(self, tmp_path):
        """Fresh DB relationships table has no local_path column."""
        from brain_sync.state import _connect

        conn = _connect(tmp_path)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(relationships)").fetchall()}
        assert "local_path" not in cols
        conn.close()

    def test_relationship_dataclass_no_local_path(self):
        """Relationship dataclass has no local_path field."""
        import dataclasses

        field_names = {f.name for f in dataclasses.fields(Relationship)}
        assert "local_path" not in field_names


class TestV17ToV18Migration:
    """Tests for adding structure_hash to insight_state (v18)."""

    def test_v17_to_v18_migration(self, tmp_path):
        """v17 DB migrates to v18: structure_hash column is added to insight_state."""
        import sqlite3

        db_path = tmp_path / ".sync-state.sqlite"
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")

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
                interval_seconds INTEGER,
                target_path TEXT NOT NULL DEFAULT '',
                fetch_children INTEGER NOT NULL DEFAULT 0,
                sync_attachments INTEGER NOT NULL DEFAULT 0,
                child_path TEXT
            );
            CREATE TABLE documents (
                canonical_id TEXT PRIMARY KEY,
                source_type TEXT NOT NULL,
                url TEXT NOT NULL UNIQUE,
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
                source_type TEXT NOT NULL,
                first_seen_utc TEXT,
                last_seen_utc TEXT,
                PRIMARY KEY (parent_canonical_id, canonical_id)
            );
            CREATE TABLE insight_state (
                knowledge_path TEXT PRIMARY KEY,
                content_hash TEXT,
                summary_hash TEXT,
                regen_started_utc TEXT,
                last_regen_utc TEXT,
                regen_status TEXT NOT NULL DEFAULT 'idle',
                owner_id TEXT,
                error_reason TEXT
            );
            CREATE TABLE token_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                operation_type TEXT NOT NULL,
                resource_type TEXT,
                resource_id TEXT,
                is_chunk INTEGER NOT NULL DEFAULT 0,
                model TEXT,
                input_tokens INTEGER,
                output_tokens INTEGER,
                total_tokens INTEGER,
                duration_ms INTEGER,
                num_turns INTEGER,
                success INTEGER NOT NULL,
                created_utc TEXT NOT NULL
            );
        """)
        conn.execute("INSERT INTO meta (key, value) VALUES ('schema_version', '17')")
        conn.execute(
            "INSERT INTO insight_state (knowledge_path, content_hash, summary_hash, regen_status) "
            "VALUES ('test/area', 'hash123', 'sumhash', 'idle')"
        )
        conn.commit()
        conn.close()

        from brain_sync.state import _connect

        conn = _connect(tmp_path)

        # Version updated
        version = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
        assert version == "20"

        # structure_hash column exists
        cols = {r[1] for r in conn.execute("PRAGMA table_info(insight_state)").fetchall()}
        assert "structure_hash" in cols

        # Existing data preserved, structure_hash is NULL
        row = conn.execute("SELECT knowledge_path, content_hash, structure_hash FROM insight_state").fetchone()
        assert row is not None
        assert row[0] == "test/area"
        assert row[1] == "hash123"
        assert row[2] is None  # new column defaults to NULL

        conn.close()

    def test_fresh_db_has_structure_hash(self, tmp_path):
        """Fresh DB insight_state table has structure_hash column."""
        from brain_sync.state import _connect

        conn = _connect(tmp_path)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(insight_state)").fetchall()}
        assert "structure_hash" in cols
        conn.close()

    def test_save_and_load_structure_hash(self, tmp_path):
        """structure_hash round-trips through save/load."""
        from brain_sync.state import _connect

        _connect(tmp_path).close()  # initialize DB

        istate = InsightState(
            knowledge_path="test",
            content_hash="chash",
            structure_hash="shash",
        )
        save_insight_state(tmp_path, istate)
        loaded = load_insight_state(tmp_path, "test")
        assert loaded is not None
        assert loaded.structure_hash == "shash"
        assert loaded.content_hash == "chash"


class TestV19Migration:
    """Tests for v19 migration: reset structure_hash for content hash re-backfill."""

    def test_v18_to_v19_migration_nulls_structure_hash(self, tmp_path):
        """v18 DB with structure_hash set → v19 migration NULLs it."""
        import sqlite3

        db_path = tmp_path / ".sync-state.sqlite"
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")

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
                interval_seconds INTEGER,
                target_path TEXT NOT NULL DEFAULT '',
                fetch_children INTEGER NOT NULL DEFAULT 0,
                sync_attachments INTEGER NOT NULL DEFAULT 0,
                child_path TEXT
            );
            CREATE TABLE documents (
                canonical_id TEXT PRIMARY KEY,
                source_type TEXT NOT NULL,
                url TEXT NOT NULL UNIQUE,
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
                source_type TEXT NOT NULL,
                first_seen_utc TEXT,
                last_seen_utc TEXT,
                PRIMARY KEY (parent_canonical_id, canonical_id)
            );
            CREATE TABLE insight_state (
                knowledge_path TEXT PRIMARY KEY,
                content_hash TEXT,
                summary_hash TEXT,
                structure_hash TEXT,
                regen_started_utc TEXT,
                last_regen_utc TEXT,
                regen_status TEXT NOT NULL DEFAULT 'idle',
                owner_id TEXT,
                error_reason TEXT
            );
            CREATE TABLE token_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                operation_type TEXT NOT NULL,
                resource_type TEXT,
                resource_id TEXT,
                is_chunk INTEGER NOT NULL DEFAULT 0,
                model TEXT,
                input_tokens INTEGER,
                output_tokens INTEGER,
                total_tokens INTEGER,
                duration_ms INTEGER,
                num_turns INTEGER,
                success INTEGER NOT NULL,
                created_utc TEXT NOT NULL
            );
        """)
        conn.execute("INSERT INTO meta (key, value) VALUES ('schema_version', '18')")
        # Insert row WITH structure_hash set (simulates buggy v18 backfill)
        conn.execute(
            "INSERT INTO insight_state (knowledge_path, content_hash, structure_hash, regen_status) "
            "VALUES ('test/area', 'old-algo-hash', 'some-structure-hash', 'idle')"
        )
        conn.commit()
        conn.close()

        from brain_sync.state import _connect

        conn = _connect(tmp_path)

        version = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
        assert version == "20"

        # structure_hash is now NULL, content_hash preserved
        row = conn.execute("SELECT knowledge_path, content_hash, structure_hash FROM insight_state").fetchone()
        assert row is not None
        assert row[0] == "test/area"
        assert row[1] == "old-algo-hash"  # content_hash unchanged by migration
        assert row[2] is None  # structure_hash reset to NULL

        conn.close()
