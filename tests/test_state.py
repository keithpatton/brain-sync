from brain_sync.state import (
    SourceState,
    SyncState,
    load_state,
    prune_db,
    prune_state,
    save_state,
    source_key,
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
        assert state.version == 1

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
