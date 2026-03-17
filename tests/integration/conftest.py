"""Shared fixtures for integration tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from brain_sync.application.init import init_brain
from brain_sync.llm.fake import FakeBackend


@pytest.fixture
def brain(tmp_path: Path) -> Path:
    """Create a fresh brain root for testing."""
    root = tmp_path / "brain"
    root.mkdir()
    init_brain(root)
    return root


@pytest.fixture
def fake_backend() -> FakeBackend:
    """Create a FakeBackend in stable mode."""
    return FakeBackend(mode="stable")
