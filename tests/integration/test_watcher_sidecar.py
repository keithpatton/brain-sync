"""Regression test: writing .regen-meta.json to insights/ produces zero watcher events.

This is the safety backstop for Phase 4's sidecar writes. The KnowledgeWatcher
schedules its observer on knowledge/ only, so writes to insights/ must be
invisible to the watcher.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from brain_sync.brain.sidecar import RegenMeta, write_regen_meta
from brain_sync.sync.watcher import KnowledgeWatcher

pytestmark = pytest.mark.integration


class TestWatcherIgnoresSidecars:
    def test_sidecar_write_produces_zero_events(self, brain: Path) -> None:
        """Writing .regen-meta.json to insights/ must not trigger any watcher events."""
        (brain / "knowledge").mkdir(exist_ok=True)
        (brain / "insights" / "project").mkdir(parents=True, exist_ok=True)

        watcher = KnowledgeWatcher(brain)
        watcher.start()
        try:
            # Write a sidecar to insights/
            write_regen_meta(
                brain / "insights" / "project",
                RegenMeta(content_hash="abc", summary_hash="def", structure_hash="ghi"),
            )

            # Give the watcher time to process any events
            time.sleep(0.5)

            # Drain events — should be empty
            events = watcher.drain_events()
            moves = watcher.drain_moves()

            assert len(events) == 0, f"Expected zero events from sidecar write, got: {events}"
            assert len(moves) == 0, f"Expected zero moves from sidecar write, got: {moves}"
        finally:
            watcher.stop()
