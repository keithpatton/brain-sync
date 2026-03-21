from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pytest

from brain_sync.application.sources import InvalidCanonicalIdError, require_exact_source_canonical_id
from brain_sync.interfaces.cli.handlers import handle_finalize_missing
from brain_sync.sync.finalization import FinalizationResult

pytestmark = pytest.mark.unit


def _args(canonical_id: str = "test:123") -> Namespace:
    return Namespace(canonical_id=canonical_id, root=Path("C:/brain"))


@patch("brain_sync.interfaces.cli.handlers._resolve_root_or_exit", return_value=Path("C:/brain"))
@patch(
    "brain_sync.application.sources.finalize_missing",
    return_value=FinalizationResult(
        canonical_id="test:123",
        result_state="not_missing",
        finalized=False,
        knowledge_state="stale",
    ),
)
def test_handle_finalize_missing_exits_one_for_not_missing(mock_finalize, mock_root) -> None:
    with pytest.raises(SystemExit) as excinfo:
        handle_finalize_missing(_args())

    assert excinfo.value.code == 1
    mock_root.assert_called_once()
    mock_finalize.assert_called_once_with(root=Path("C:/brain"), canonical_id="test:123")


@patch("brain_sync.interfaces.cli.handlers._resolve_root_or_exit", return_value=Path("C:/brain"))
@patch(
    "brain_sync.application.sources.finalize_missing",
    return_value=FinalizationResult(
        canonical_id="test:123",
        result_state="finalized",
        finalized=True,
    ),
)
def test_handle_finalize_missing_returns_cleanly_for_finalized(mock_finalize, mock_root) -> None:
    handle_finalize_missing(_args())

    mock_root.assert_called_once()
    mock_finalize.assert_called_once_with(root=Path("C:/brain"), canonical_id="test:123")


@patch("brain_sync.interfaces.cli.handlers._resolve_root_or_exit", return_value=Path("C:/brain"))
@patch(
    "brain_sync.application.sources.finalize_missing",
    return_value=FinalizationResult(
        canonical_id="test:123",
        result_state="lease_conflict",
        finalized=False,
        message="lease held elsewhere",
    ),
)
def test_handle_finalize_missing_exits_one_for_lease_conflict(mock_finalize, mock_root) -> None:
    with pytest.raises(SystemExit) as excinfo:
        handle_finalize_missing(_args())

    assert excinfo.value.code == 1
    mock_root.assert_called_once()
    mock_finalize.assert_called_once_with(root=Path("C:/brain"), canonical_id="test:123")


@patch("brain_sync.interfaces.cli.handlers._resolve_root_or_exit", return_value=Path("C:/brain"))
@patch(
    "brain_sync.application.sources.finalize_missing",
    return_value=FinalizationResult(
        canonical_id="test:123",
        result_state="not_found",
        finalized=False,
        error="not_found",
    ),
)
def test_handle_finalize_missing_exits_one_for_not_found(mock_finalize, mock_root) -> None:
    with pytest.raises(SystemExit) as excinfo:
        handle_finalize_missing(_args())

    assert excinfo.value.code == 1
    mock_root.assert_called_once()
    mock_finalize.assert_called_once_with(root=Path("C:/brain"), canonical_id="test:123")


@patch("brain_sync.interfaces.cli.handlers._resolve_root_or_exit", return_value=Path("C:/brain"))
@patch(
    "brain_sync.application.sources.finalize_missing", side_effect=InvalidCanonicalIdError("https://example.com/page")
)
def test_handle_finalize_missing_rejects_url_targeting(mock_finalize, mock_root) -> None:
    with pytest.raises(SystemExit) as excinfo:
        handle_finalize_missing(_args("https://example.com/page"))

    assert excinfo.value.code == 1
    mock_root.assert_called_once()
    mock_finalize.assert_called_once_with(root=Path("C:/brain"), canonical_id="https://example.com/page")


@patch("brain_sync.interfaces.cli.handlers._resolve_root_or_exit", return_value=Path("C:/brain"))
@patch("brain_sync.application.sources.finalize_missing", side_effect=InvalidCanonicalIdError(r"C:\temp\page"))
def test_handle_finalize_missing_rejects_windows_path_targeting(mock_finalize, mock_root) -> None:
    with pytest.raises(SystemExit) as excinfo:
        handle_finalize_missing(_args(r"C:\temp\page"))

    assert excinfo.value.code == 1
    mock_root.assert_called_once()
    mock_finalize.assert_called_once_with(root=Path("C:/brain"), canonical_id=r"C:\temp\page")


@pytest.mark.parametrize("canonical_id", ["confluence:123", "gdoc:abc_123-XYZ", "test:fixture_123"])
def test_require_exact_source_canonical_id_accepts_supported_source_targets(canonical_id: str) -> None:
    assert require_exact_source_canonical_id(canonical_id) == canonical_id


@pytest.mark.parametrize(
    "canonical_id",
    [
        "",
        " confluence:123",
        "confluence:123 ",
        "https://example.com/page",
        "knowledge/area/doc.md",
        r"C:\temp\page",
        "confluence:123,gdoc:abc",
        "gdoc-image:abc123:kix.obj1",
        "attachment:123",
        "confluence:abc",
    ],
)
def test_require_exact_source_canonical_id_rejects_non_source_exact_targets(canonical_id: str) -> None:
    with pytest.raises(InvalidCanonicalIdError):
        require_exact_source_canonical_id(canonical_id)
