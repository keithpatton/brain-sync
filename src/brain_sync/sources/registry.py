"""Lazy adapter registry — no startup wiring."""

from __future__ import annotations

from brain_sync.sources import SourceType
from brain_sync.sources.base import SourceAdapter

_instances: dict[SourceType, SourceAdapter] = {}


def get_adapter(source_type: SourceType) -> SourceAdapter:
    if source_type not in _instances:
        _instances[source_type] = _get_adapter_class(source_type)()
    return _instances[source_type]


def _get_adapter_class(source_type: SourceType) -> type:
    if source_type == SourceType.CONFLUENCE:
        from brain_sync.sources.confluence import ConfluenceAdapter

        return ConfluenceAdapter
    if source_type == SourceType.GOOGLE_DOCS:
        from brain_sync.sources.googledocs import GoogleDocsAdapter

        return GoogleDocsAdapter
    if source_type == SourceType.TEST:
        from brain_sync.sources.test import TestAdapter

        return TestAdapter
    raise ValueError(f"No adapter for {source_type}")


def reset_registry() -> None:
    """For testing."""
    _instances.clear()
