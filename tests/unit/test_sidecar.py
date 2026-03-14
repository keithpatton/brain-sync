"""Unit tests for sidecar.py — .regen-meta.json read/write utilities."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from brain_sync.sidecar import (
    SIDECAR_FILENAME,
    SIDECAR_VERSION,
    RegenMeta,
    UnsupportedSidecarVersion,
    delete_regen_meta,
    load_regen_hashes,
    read_all_regen_meta,
    read_regen_meta,
    write_regen_meta,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def insights_dir(tmp_path: Path) -> Path:
    d = tmp_path / "insights" / "project"
    d.mkdir(parents=True)
    return d


@pytest.fixture
def insights_root(tmp_path: Path) -> Path:
    return tmp_path / "insights"


class TestWriteReadRoundTrip:
    def test_full_fields(self, insights_dir: Path) -> None:
        meta = RegenMeta(
            content_hash="abc123",
            summary_hash="def456",
            structure_hash="ghi789",
            last_regen_utc="2026-03-14T10:00:00+00:00",
        )
        write_regen_meta(insights_dir, meta)
        loaded = read_regen_meta(insights_dir)
        assert loaded is not None
        assert loaded.version == SIDECAR_VERSION
        assert loaded.content_hash == "abc123"
        assert loaded.summary_hash == "def456"
        assert loaded.structure_hash == "ghi789"
        assert loaded.last_regen_utc == "2026-03-14T10:00:00+00:00"

    def test_partial_fields(self, insights_dir: Path) -> None:
        meta = RegenMeta(content_hash="abc123")
        write_regen_meta(insights_dir, meta)
        loaded = read_regen_meta(insights_dir)
        assert loaded is not None
        assert loaded.content_hash == "abc123"
        assert loaded.summary_hash is None
        assert loaded.structure_hash is None
        assert loaded.last_regen_utc is None


class TestReadMissing:
    def test_returns_none_for_missing(self, insights_dir: Path) -> None:
        assert read_regen_meta(insights_dir) is None


class TestReadMalformed:
    def test_returns_none_for_bad_json(self, insights_dir: Path) -> None:
        (insights_dir / SIDECAR_FILENAME).write_text("not json{{{", encoding="utf-8")
        assert read_regen_meta(insights_dir) is None

    def test_returns_none_for_missing_version(self, insights_dir: Path) -> None:
        (insights_dir / SIDECAR_FILENAME).write_text('{"content_hash": "abc"}', encoding="utf-8")
        assert read_regen_meta(insights_dir) is None

    def test_returns_none_for_invalid_version(self, insights_dir: Path) -> None:
        (insights_dir / SIDECAR_FILENAME).write_text('{"version": "bad"}', encoding="utf-8")
        assert read_regen_meta(insights_dir) is None


class TestUnsupportedVersion:
    def test_raises_for_future_version(self, insights_dir: Path) -> None:
        data = json.dumps({"version": SIDECAR_VERSION + 1})
        (insights_dir / SIDECAR_FILENAME).write_text(data, encoding="utf-8")
        with pytest.raises(UnsupportedSidecarVersion):
            read_regen_meta(insights_dir)


class TestWriteCreatesParents:
    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        deep_dir = tmp_path / "insights" / "deep" / "nested" / "path"
        write_regen_meta(deep_dir, RegenMeta(content_hash="abc"))
        assert (deep_dir / SIDECAR_FILENAME).exists()


class TestReadAllRegenMeta:
    def test_discovers_nested_sidecars(self, insights_root: Path) -> None:
        # Write sidecars at different levels
        d1 = insights_root / "eng" / "backend"
        d2 = insights_root / "eng"
        d3 = insights_root / "product"
        for d, h in [(d1, "h1"), (d2, "h2"), (d3, "h3")]:
            d.mkdir(parents=True, exist_ok=True)
            write_regen_meta(d, RegenMeta(content_hash=h))

        result = read_all_regen_meta(insights_root)
        assert len(result) == 3
        assert result["eng/backend"].content_hash == "h1"
        assert result["eng"].content_hash == "h2"
        assert result["product"].content_hash == "h3"

    def test_empty_root(self, tmp_path: Path) -> None:
        assert read_all_regen_meta(tmp_path / "nonexistent") == {}


class TestDeleteRegenMeta:
    def test_deletes_existing(self, insights_dir: Path) -> None:
        write_regen_meta(insights_dir, RegenMeta(content_hash="abc"))
        assert (insights_dir / SIDECAR_FILENAME).exists()
        delete_regen_meta(insights_dir)
        assert not (insights_dir / SIDECAR_FILENAME).exists()

    def test_noop_if_missing(self, insights_dir: Path) -> None:
        delete_regen_meta(insights_dir)  # should not raise


class TestOmitsNoneFields:
    def test_none_fields_omitted_from_json(self, insights_dir: Path) -> None:
        write_regen_meta(insights_dir, RegenMeta(content_hash="abc"))
        raw = json.loads((insights_dir / SIDECAR_FILENAME).read_text(encoding="utf-8"))
        assert "version" in raw
        assert "content_hash" in raw
        assert "summary_hash" not in raw
        assert "structure_hash" not in raw
        assert "last_regen_utc" not in raw


class TestLoadRegenHashes:
    """Unit tests for load_regen_hashes — sidecar-first, DB fallback."""

    def test_sidecar_first(self, tmp_path: Path) -> None:
        """When both sidecar and DB have values, sidecar wins."""
        from unittest.mock import patch

        root = tmp_path / "brain"
        root.mkdir()
        insights_dir = root / "insights" / "project"
        insights_dir.mkdir(parents=True)

        # Write sidecar with one set of values
        write_regen_meta(insights_dir, RegenMeta(content_hash="sidecar_hash", summary_hash="s_sum"))

        # Mock DB to return different values
        from brain_sync.state import InsightState

        db_state = InsightState(knowledge_path="project", content_hash="db_hash", summary_hash="d_sum")
        with patch("brain_sync.state.load_insight_state", return_value=db_state):
            meta = load_regen_hashes(root, "project")

        assert meta is not None
        assert meta.content_hash == "sidecar_hash"
        assert meta.summary_hash == "s_sum"

    def test_db_fallback(self, tmp_path: Path) -> None:
        """When no sidecar exists, falls back to DB."""
        from unittest.mock import patch

        root = tmp_path / "brain"
        root.mkdir()
        (root / "insights" / "project").mkdir(parents=True)
        # No sidecar written

        from brain_sync.state import InsightState

        db_state = InsightState(
            knowledge_path="project",
            content_hash="db_hash",
            summary_hash="db_sum",
            structure_hash="db_struct",
            last_regen_utc="2026-01-01T00:00:00",
        )
        with patch("brain_sync.state.load_insight_state", return_value=db_state):
            meta = load_regen_hashes(root, "project")

        assert meta is not None
        assert meta.content_hash == "db_hash"
        assert meta.summary_hash == "db_sum"
        assert meta.structure_hash == "db_struct"

    def test_neither_returns_none(self, tmp_path: Path) -> None:
        """When neither sidecar nor DB have data, returns None."""
        from unittest.mock import patch

        root = tmp_path / "brain"
        root.mkdir()
        (root / "insights" / "project").mkdir(parents=True)

        with patch("brain_sync.state.load_insight_state", return_value=None):
            meta = load_regen_hashes(root, "project")

        assert meta is None
