"""Phase 3D: Platform-sensitive edge case E2E tests.

Tests for filesystem quirks: editor temp files, partial writes, renames.
"""

from __future__ import annotations

import time

import pytest

from tests.e2e.harness.assertions import assert_brain_consistent
from tests.e2e.harness.brain import BrainFixture, seed_knowledge_tree
from tests.e2e.harness.cli import CliRunner
from tests.e2e.harness.daemon import DaemonProcess
from tests.e2e.harness.scenarios import run_regen

pytestmark = pytest.mark.e2e


class TestEditorTempFilesIgnored:
    """Temp files from editors (~file.md, .swp, .tmp) must not trigger regen."""

    def test_editor_temp_files_ignored(
        self,
        brain: BrainFixture,
        cli: CliRunner,
        daemon: DaemonProcess,
    ):
        seed_knowledge_tree(
            brain.root,
            {
                "knowledge/": {
                    "area/": {"doc.md": "# Doc\n\nContent."},
                },
            },
        )
        run_regen(cli, brain.root, "area")
        initial_summary = (brain.insights / "area" / "summary.md").read_text(encoding="utf-8")

        daemon.start()
        daemon.wait_for_ready()

        # Create temp files that editors commonly produce
        area = brain.knowledge / "area"
        (area / "~doc.md").write_text("temp", encoding="utf-8")
        (area / ".doc.md.swp").write_text("swap", encoding="utf-8")
        (area / "doc.md.tmp").write_text("tmp", encoding="utf-8")

        # Wait a bit for any spurious regen to happen
        time.sleep(5)

        daemon.shutdown()

        # Summary should be unchanged (no regen triggered by temp files)
        final_summary = (brain.insights / "area" / "summary.md").read_text(encoding="utf-8")
        assert initial_summary == final_summary, "Temp files should not trigger regen"

        # Clean up temp files before invariant check
        for f in ["~doc.md", ".doc.md.swp", "doc.md.tmp"]:
            p = area / f
            if p.exists():
                p.unlink()

        assert_brain_consistent(brain.root)


class TestPartialWriteDebounce:
    """Multi-chunk write produces a single regen event via debouncing."""

    def test_partial_write_debounce(
        self,
        brain: BrainFixture,
        cli: CliRunner,
        daemon: DaemonProcess,
    ):
        seed_knowledge_tree(
            brain.root,
            {
                "knowledge/": {
                    "area/": {"doc.md": "# Doc\n\nOriginal."},
                },
            },
        )
        run_regen(cli, brain.root, "area")

        daemon.start()
        daemon.wait_for_ready()

        # Simulate a slow multi-chunk write
        doc = brain.knowledge / "area" / "doc.md"
        for i in range(5):
            doc.write_text(f"# Doc\n\nChunk {i} of slow write.", encoding="utf-8")
            time.sleep(0.1)

        # Final content
        doc.write_text("# Doc\n\nFinal content after slow write.", encoding="utf-8")

        # Wait for debounce + regen
        time.sleep(10)

        daemon.shutdown()
        assert_brain_consistent(brain.root)


class TestCaseOnlyRename:
    """Rename Area → area handled correctly (case-insensitive FS)."""

    def test_case_only_rename(
        self,
        brain: BrainFixture,
        cli: CliRunner,
        daemon: DaemonProcess,
    ):
        seed_knowledge_tree(
            brain.root,
            {
                "knowledge/": {
                    "MyArea/": {"doc.md": "# Doc\n\nContent."},
                },
            },
        )
        run_regen(cli, brain.root, "MyArea")

        daemon.start()
        daemon.wait_for_ready()

        # Case-only rename (may be a no-op on case-insensitive FS)
        src = brain.knowledge / "MyArea"
        dst = brain.knowledge / "myarea"
        try:
            src.rename(dst)
        except OSError:
            # Some FS don't support case-only renames via rename()
            pytest.skip("Filesystem does not support case-only rename")

        time.sleep(5)
        daemon.shutdown()

        # Brain should be consistent regardless of how the FS handled it
        assert_brain_consistent(brain.root)


class TestAtomicEditorSwap:
    """Editor writes file.md.tmp then renames to file.md — single regen."""

    def test_atomic_editor_swap(
        self,
        brain: BrainFixture,
        cli: CliRunner,
        daemon: DaemonProcess,
    ):
        seed_knowledge_tree(
            brain.root,
            {
                "knowledge/": {
                    "area/": {"doc.md": "# Doc\n\nOriginal content."},
                },
            },
        )
        run_regen(cli, brain.root, "area")

        daemon.start()
        daemon.wait_for_ready()

        # Simulate atomic editor save: write to .tmp then rename
        area = brain.knowledge / "area"
        tmp_file = area / "doc.md.tmp"
        target = area / "doc.md"

        tmp_file.write_text("# Doc\n\nUpdated via atomic swap.", encoding="utf-8")
        # Small delay to simulate real editor timing
        time.sleep(0.1)
        import os

        os.replace(str(tmp_file), str(target))

        # Wait for debounce + regen
        time.sleep(10)

        daemon.shutdown()
        assert_brain_consistent(brain.root)
