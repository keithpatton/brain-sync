from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from brain_sync.brain.sidecar import (
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
def brain(tmp_path: Path) -> Path:
    root = tmp_path / "brain"
    (root / "knowledge").mkdir(parents=True)
    return root


@pytest.fixture
def insights_dir(brain: Path) -> Path:
    path = brain / "knowledge" / "project" / ".brain-sync" / "insights"
    path.mkdir(parents=True)
    return path


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
        write_regen_meta(insights_dir, RegenMeta(content_hash="abc123"))
        loaded = read_regen_meta(insights_dir)

        assert loaded is not None
        assert loaded.content_hash == "abc123"
        assert loaded.summary_hash is None

    def test_identical_write_is_noop(self, insights_dir: Path) -> None:
        meta = RegenMeta(
            content_hash="abc123",
            summary_hash="def456",
            structure_hash="ghi789",
            last_regen_utc="2026-03-14T10:00:00+00:00",
        )

        assert write_regen_meta(insights_dir, meta) is True
        target = insights_dir / SIDECAR_FILENAME
        before_bytes = target.read_bytes()
        before_mtime = target.stat().st_mtime_ns

        with patch(
            "brain_sync.brain.sidecar.write_bytes_if_changed",
            wraps=write_regen_meta.__globals__["write_bytes_if_changed"],
        ) as wrapped:
            assert write_regen_meta(insights_dir, meta) is False
            wrapped.assert_called_once()

        assert target.read_bytes() == before_bytes
        assert target.stat().st_mtime_ns == before_mtime


class TestReadMalformed:
    def test_missing_returns_none(self, insights_dir: Path) -> None:
        assert read_regen_meta(insights_dir) is None

    def test_bad_json_returns_none(self, insights_dir: Path) -> None:
        (insights_dir / SIDECAR_FILENAME).write_text("not json{{{", encoding="utf-8")
        assert read_regen_meta(insights_dir) is None

    def test_bad_version_returns_none(self, insights_dir: Path) -> None:
        (insights_dir / SIDECAR_FILENAME).write_text('{"version": "bad"}', encoding="utf-8")
        assert read_regen_meta(insights_dir) is None

    def test_future_version_raises(self, insights_dir: Path) -> None:
        (insights_dir / SIDECAR_FILENAME).write_text(json.dumps({"version": SIDECAR_VERSION + 1}), encoding="utf-8")
        with pytest.raises(UnsupportedSidecarVersion):
            read_regen_meta(insights_dir)


class TestReadAll:
    def test_discovers_colocated_sidecars(self, brain: Path) -> None:
        for knowledge_path, content_hash in [("eng/backend", "h1"), ("eng", "h2"), ("product", "h3"), ("", "root")]:
            if knowledge_path:
                insights_path = brain / "knowledge" / knowledge_path / ".brain-sync" / "insights"
            else:
                insights_path = brain / "knowledge" / ".brain-sync" / "insights"
            insights_path.mkdir(parents=True, exist_ok=True)
            write_regen_meta(insights_path, RegenMeta(content_hash=content_hash))

        result = read_all_regen_meta(brain / "knowledge")

        assert result["eng/backend"].content_hash == "h1"
        assert result["eng"].content_hash == "h2"
        assert result["product"].content_hash == "h3"
        assert result[""].content_hash == "root"

    def test_empty_root(self, tmp_path: Path) -> None:
        assert read_all_regen_meta(tmp_path / "missing") == {}


class TestDelete:
    def test_delete_existing(self, insights_dir: Path) -> None:
        write_regen_meta(insights_dir, RegenMeta(content_hash="abc"))
        delete_regen_meta(insights_dir)
        assert not (insights_dir / SIDECAR_FILENAME).exists()

    def test_delete_missing_noop(self, insights_dir: Path) -> None:
        delete_regen_meta(insights_dir)


class TestJsonShape:
    def test_none_fields_omitted(self, insights_dir: Path) -> None:
        write_regen_meta(insights_dir, RegenMeta(content_hash="abc"))
        raw = json.loads((insights_dir / SIDECAR_FILENAME).read_text(encoding="utf-8"))

        assert raw["version"] == SIDECAR_VERSION
        assert raw["content_hash"] == "abc"
        assert "summary_hash" not in raw
        assert "structure_hash" not in raw


class TestLoadRegenHashes:
    def test_reads_colocated_sidecar(self, brain: Path) -> None:
        insights_dir = brain / "knowledge" / "project" / ".brain-sync" / "insights"
        insights_dir.mkdir(parents=True)
        write_regen_meta(insights_dir, RegenMeta(content_hash="sidecar_hash", summary_hash="summary_hash"))

        meta = load_regen_hashes(brain, "project")

        assert meta is not None
        assert meta.content_hash == "sidecar_hash"
        assert meta.summary_hash == "summary_hash"

    def test_missing_sidecar_returns_none(self, brain: Path) -> None:
        (brain / "knowledge" / "project").mkdir(parents=True)
        assert load_regen_hashes(brain, "project") is None
