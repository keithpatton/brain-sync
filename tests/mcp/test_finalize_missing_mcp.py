from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from brain_sync.application.query_index import load_area_index
from brain_sync.application.sources import InvalidCanonicalIdError
from brain_sync.interfaces.mcp.server import BrainRuntime
from brain_sync.sync.finalization import FinalizationResult

pytestmark = pytest.mark.mcp


def _make_ctx(root: Path) -> MagicMock:
    rt = BrainRuntime(
        root=root,
        area_index=load_area_index(root),
        regen_lock=asyncio.Lock(),
        lifecycle_session_id="mcp:session-1",
    )
    ctx = MagicMock()
    ctx.request_context.lifespan_context = rt
    return ctx


@pytest.fixture
def dummy_root(tmp_path: Path) -> Path:
    root = tmp_path / "brain"
    root.mkdir()
    return root


class TestBrainSyncFinalizeMissing:
    @patch(
        "brain_sync.interfaces.mcp.server.finalize_missing",
        return_value=FinalizationResult(
            canonical_id="test:123",
            result_state="pending_confirmation",
            finalized=False,
            knowledge_state="missing",
            missing_confirmation_count=2,
            eligible=False,
        ),
    )
    def test_returns_pending_confirmation_payload(self, mock_finalize, dummy_root: Path) -> None:
        from brain_sync.interfaces.mcp.server import brain_sync_finalize_missing

        ctx = _make_ctx(dummy_root)
        result = brain_sync_finalize_missing(ctx, canonical_id="test:123")

        assert result == {
            "status": "ok",
            "canonical_id": "test:123",
            "result_state": "pending_confirmation",
            "finalized": False,
            "knowledge_state": "missing",
            "missing_confirmation_count": 2,
            "eligible": False,
        }
        mock_finalize.assert_called_once_with(
            root=dummy_root,
            canonical_id="test:123",
            lifecycle_session_id="mcp:session-1",
        )

    @patch(
        "brain_sync.interfaces.mcp.server.finalize_missing",
        return_value=FinalizationResult(
            canonical_id="test:123",
            result_state="lease_conflict",
            finalized=False,
            eligible=False,
            message="lease held elsewhere",
        ),
    )
    def test_returns_lease_conflict_as_handled_result(self, mock_finalize, dummy_root: Path) -> None:
        from brain_sync.interfaces.mcp.server import brain_sync_finalize_missing

        ctx = _make_ctx(dummy_root)
        result = brain_sync_finalize_missing(ctx, canonical_id="test:123")

        assert result == {
            "status": "ok",
            "canonical_id": "test:123",
            "result_state": "lease_conflict",
            "finalized": False,
            "eligible": False,
            "message": "lease held elsewhere",
        }
        mock_finalize.assert_called_once_with(
            root=dummy_root,
            canonical_id="test:123",
            lifecycle_session_id="mcp:session-1",
        )

    @patch(
        "brain_sync.interfaces.mcp.server.finalize_missing",
        return_value=FinalizationResult(
            canonical_id="test:123",
            result_state="not_found",
            finalized=False,
            error="not_found",
        ),
    )
    def test_returns_not_found_as_error(self, mock_finalize, dummy_root: Path) -> None:
        from brain_sync.interfaces.mcp.server import brain_sync_finalize_missing

        ctx = _make_ctx(dummy_root)
        result = brain_sync_finalize_missing(ctx, canonical_id="test:123")

        assert result == {
            "status": "error",
            "error": "not_found",
            "canonical_id": "test:123",
            "result_state": "not_found",
            "finalized": False,
        }
        mock_finalize.assert_called_once_with(
            root=dummy_root,
            canonical_id="test:123",
            lifecycle_session_id="mcp:session-1",
        )

    @patch(
        "brain_sync.interfaces.mcp.server.finalize_missing",
        side_effect=InvalidCanonicalIdError("https://example.com/page"),
    )
    def test_rejects_url_targeting(self, mock_finalize, dummy_root: Path) -> None:
        from brain_sync.interfaces.mcp.server import brain_sync_finalize_missing

        ctx = _make_ctx(dummy_root)
        result = brain_sync_finalize_missing(ctx, canonical_id="https://example.com/page")

        assert result == {
            "status": "error",
            "error": "invalid_canonical_id",
            "message": "brain_sync_finalize_missing requires a canonical_id, not a URL or bulk target.",
        }
        mock_finalize.assert_called_once_with(
            root=dummy_root,
            canonical_id="https://example.com/page",
            lifecycle_session_id="mcp:session-1",
        )

    @patch(
        "brain_sync.interfaces.mcp.server.finalize_missing",
        side_effect=InvalidCanonicalIdError(r"C:\temp\page"),
    )
    def test_rejects_windows_path_targeting(self, mock_finalize, dummy_root: Path) -> None:
        from brain_sync.interfaces.mcp.server import brain_sync_finalize_missing

        ctx = _make_ctx(dummy_root)
        result = brain_sync_finalize_missing(ctx, canonical_id=r"C:\temp\page")

        assert result == {
            "status": "error",
            "error": "invalid_canonical_id",
            "message": "brain_sync_finalize_missing requires a canonical_id, not a URL or bulk target.",
        }
        mock_finalize.assert_called_once_with(
            root=dummy_root,
            canonical_id=r"C:\temp\page",
            lifecycle_session_id="mcp:session-1",
        )


class TestBrainSyncDoctorModes:
    def test_deregister_missing_returns_migration_hint(self, dummy_root: Path) -> None:
        from brain_sync.interfaces.mcp.server import brain_sync_doctor

        ctx = _make_ctx(dummy_root)
        result = brain_sync_doctor(ctx, mode="deregister_missing")

        assert result == {
            "status": "error",
            "error": "unsupported_mode",
            "message": "Use brain_sync_finalize_missing(canonical_id=...) instead.",
        }
