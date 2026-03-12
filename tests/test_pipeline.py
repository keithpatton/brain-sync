"""Unit tests for pipeline.py skip-guard logic."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from brain_sync.pipeline import process_source
from brain_sync.sources import canonical_filename, detect_source_type, extract_id
from brain_sync.sources.base import SourceFetchResult, UpdateCheckResult, UpdateStatus
from brain_sync.state import SourceState

pytestmark = pytest.mark.unit

_GDOC_URL = "https://docs.google.com/document/d/abc123/edit"
_CANONICAL_ID = "gdoc:abc123"
_DOC_ID = "abc123"
_TITLE = "My Doc"
_FINGERPRINT = "rev-42"


@pytest.fixture
def source_state() -> SourceState:
    return SourceState(
        canonical_id=_CANONICAL_ID,
        source_url=_GDOC_URL,
        source_type="googledocs",
        metadata_fingerprint=_FINGERPRINT,
    )


@pytest.fixture
def unchanged_check() -> UpdateCheckResult:
    return UpdateCheckResult(
        status=UpdateStatus.UNCHANGED,
        fingerprint=_FINGERPRINT,
        title=_TITLE,
        adapter_state={"revisionId": _FINGERPRINT},
    )


@pytest.fixture
def fetch_result() -> SourceFetchResult:
    return SourceFetchResult(
        body_markdown="# My Doc\n\nContent.",
        title=_TITLE,
        metadata_fingerprint=_FINGERPRINT,
        comments=[],
    )


def _make_adapter(check_result: UpdateCheckResult, fetch_result: SourceFetchResult | None = None) -> MagicMock:
    adapter = MagicMock()
    adapter.capabilities.supports_version_check = True
    adapter.capabilities.supports_context_sync = False
    adapter.capabilities.supports_comments = False
    adapter.auth_provider.load_auth.return_value = MagicMock()
    adapter.check_for_update = AsyncMock(return_value=check_result)
    adapter.fetch = AsyncMock(return_value=fetch_result)
    return adapter


class TestSkipGuardWithRoot:
    async def test_skip_when_file_found_via_rediscover(
        self, source_state: SourceState, unchanged_check: UpdateCheckResult, tmp_path: Path
    ) -> None:
        """When rediscover_local_path finds the file, skip guard fires and fetch is not called."""
        discovered = tmp_path / "knowledge" / f"g{_DOC_ID}-my-doc.md"
        adapter = _make_adapter(unchanged_check)

        with (
            patch("brain_sync.pipeline.get_adapter", return_value=adapter),
            patch("brain_sync.pipeline.rediscover_local_path", return_value=discovered),
        ):
            result = await process_source(source_state, AsyncMock(), root=tmp_path)

        assert result is False
        adapter.fetch.assert_not_called()

    async def test_fetch_when_file_not_found_via_rediscover(
        self,
        source_state: SourceState,
        unchanged_check: UpdateCheckResult,
        fetch_result: SourceFetchResult,
        tmp_path: Path,
    ) -> None:
        """When rediscover_local_path returns None, skip guard is bypassed and fetch is called."""
        adapter = _make_adapter(unchanged_check, fetch_result)

        with (
            patch("brain_sync.pipeline.get_adapter", return_value=adapter),
            patch("brain_sync.pipeline.rediscover_local_path", return_value=None),
        ):
            await process_source(source_state, AsyncMock(), root=tmp_path)

        adapter.fetch.assert_called_once()

    async def test_skip_guard_does_not_fire_when_status_changed(
        self,
        source_state: SourceState,
        fetch_result: SourceFetchResult,
        tmp_path: Path,
    ) -> None:
        """When check returns CHANGED, fetch is called even if the file exists on disk."""
        changed_check = UpdateCheckResult(
            status=UpdateStatus.CHANGED,
            fingerprint="rev-43",
            title=_TITLE,
            adapter_state={"revisionId": "rev-43"},
        )
        discovered = tmp_path / "knowledge" / f"g{_DOC_ID}-my-doc.md"
        adapter = _make_adapter(changed_check, fetch_result)

        with (
            patch("brain_sync.pipeline.get_adapter", return_value=adapter),
            patch("brain_sync.pipeline.rediscover_local_path", return_value=discovered),
        ):
            changed = await process_source(source_state, AsyncMock(), root=tmp_path)

        assert changed is True
        adapter.fetch.assert_called_once()


class TestSkipGuardWithoutRoot:
    def _target_filename(self) -> str:
        stype = detect_source_type(_GDOC_URL)
        doc_id = extract_id(stype, _GDOC_URL)
        return canonical_filename(stype, doc_id, _TITLE)

    async def test_skip_when_root_none_and_file_exists(
        self,
        source_state: SourceState,
        unchanged_check: UpdateCheckResult,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """With root=None, falls back to target.exists(); skip fires when file is present."""
        monkeypatch.chdir(tmp_path)
        fname = self._target_filename()
        (tmp_path / fname).write_text("# My Doc\n")
        adapter = _make_adapter(unchanged_check)

        with patch("brain_sync.pipeline.get_adapter", return_value=adapter):
            result = await process_source(source_state, AsyncMock(), root=None)

        assert result is False
        adapter.fetch.assert_not_called()

    async def test_fetch_when_root_none_and_file_absent(
        self,
        source_state: SourceState,
        unchanged_check: UpdateCheckResult,
        fetch_result: SourceFetchResult,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """With root=None and no file on disk, skip guard is bypassed and fetch is called."""
        monkeypatch.chdir(tmp_path)
        adapter = _make_adapter(unchanged_check, fetch_result)

        with patch("brain_sync.pipeline.get_adapter", return_value=adapter):
            await process_source(source_state, AsyncMock(), root=None)

        adapter.fetch.assert_called_once()
