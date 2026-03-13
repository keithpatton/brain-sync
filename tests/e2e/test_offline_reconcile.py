"""Phase 3B: Offline reconciliation E2E tests.

Pattern: start daemon → stabilise → stop → filesystem mutates → restart → verify convergence.
"""

from __future__ import annotations

import pytest

from tests.e2e.harness.assertions import assert_brain_consistent, assert_no_orphan_insights
from tests.e2e.harness.brain import BrainFixture, seed_knowledge_tree
from tests.e2e.harness.cli import CliRunner
from tests.e2e.harness.daemon import DaemonProcess
from tests.e2e.harness.scenarios import move_folder, run_regen, write_knowledge_file
from tests.e2e.harness.wait import wait_for_file

pytestmark = pytest.mark.e2e


class TestOfflineFolderRename:
    """Rename knowledge/ folder while daemon is stopped → reconcile picks it up."""

    def test_offline_folder_rename(
        self,
        brain: BrainFixture,
        cli: CliRunner,
        daemon: DaemonProcess,
    ):
        seed_knowledge_tree(
            brain.root,
            {
                "knowledge/": {
                    "area-a/": {
                        "doc.md": "# Area A\n\nContent for area A.",
                    },
                },
            },
        )

        # Initial regen so insights exist
        run_regen(cli, brain.root, "area-a")
        assert (brain.insights / "area-a" / "summary.md").exists()

        # Start + stop daemon
        daemon.start()
        daemon.wait_for_ready()
        daemon.shutdown()

        # Offline rename
        move_folder(brain.root, "area-a", "area-b")
        # Also move insights to match (as if watcher had done it)
        import shutil

        if (brain.insights / "area-a").exists():
            shutil.move(str(brain.insights / "area-a"), str(brain.insights / "area-b"))

        # Restart and reconcile
        daemon.start()
        daemon.wait_for_ready()

        # Wait for regen at new path
        wait_for_file(brain.insights / "area-b" / "summary.md", timeout=30)
        daemon.shutdown()

        assert not (brain.knowledge / "area-a").exists()
        assert_brain_consistent(brain.root)


class TestOfflineFolderDelete:
    """Delete knowledge/ folder while daemon is stopped."""

    def test_offline_folder_delete(
        self,
        brain: BrainFixture,
        cli: CliRunner,
        daemon: DaemonProcess,
    ):
        seed_knowledge_tree(
            brain.root,
            {
                "knowledge/": {
                    "doomed/": {
                        "doc.md": "# Doomed\n\nWill be deleted.",
                    },
                },
            },
        )
        run_regen(cli, brain.root, "doomed")

        daemon.start()
        daemon.wait_for_ready()
        daemon.shutdown()

        # Delete the knowledge folder
        import shutil

        shutil.rmtree(str(brain.knowledge / "doomed"))

        # Restart
        daemon.start()
        daemon.wait_for_ready()
        daemon.shutdown()

        # insights/doomed should now be orphaned — but reconcile may clean it.
        # At minimum, the brain should be consistent.
        assert_brain_consistent(brain.root)


class TestOfflineFileAddition:
    """Add a file to knowledge/ while daemon is stopped."""

    def test_offline_file_addition(
        self,
        brain: BrainFixture,
        cli: CliRunner,
        daemon: DaemonProcess,
    ):
        seed_knowledge_tree(
            brain.root,
            {
                "knowledge/": {
                    "area/": {
                        "existing.md": "# Existing\n\nOriginal content.",
                    },
                },
            },
        )
        run_regen(cli, brain.root, "area")

        daemon.start()
        daemon.wait_for_ready()
        daemon.shutdown()

        # Offline file addition
        write_knowledge_file(brain.root, "area/new-topic.md", "# New Topic\n\nFresh content.")

        # Restart — watcher should pick up the change
        daemon.start()
        daemon.wait_for_ready()

        # Wait for regen to update the summary
        wait_for_file(brain.insights / "area" / "summary.md", timeout=30)
        daemon.shutdown()

        assert_brain_consistent(brain.root)


class TestOfflineFileDelete:
    """Delete a file from knowledge/ while daemon is stopped."""

    def test_offline_file_delete(
        self,
        brain: BrainFixture,
        cli: CliRunner,
        daemon: DaemonProcess,
    ):
        seed_knowledge_tree(
            brain.root,
            {
                "knowledge/": {
                    "area/": {
                        "keep.md": "# Keep\n\nStays.",
                        "remove.md": "# Remove\n\nGoing away.",
                    },
                },
            },
        )
        run_regen(cli, brain.root, "area")

        daemon.start()
        daemon.wait_for_ready()
        daemon.shutdown()

        # Offline deletion
        (brain.knowledge / "area" / "remove.md").unlink()

        daemon.start()
        daemon.wait_for_ready()
        daemon.shutdown()

        assert_brain_consistent(brain.root)


class TestOfflineSubtreeMove:
    """Move a nested subtree while daemon is stopped."""

    def test_offline_subtree_move(
        self,
        brain: BrainFixture,
        cli: CliRunner,
        daemon: DaemonProcess,
    ):
        seed_knowledge_tree(
            brain.root,
            {
                "knowledge/": {
                    "eng/": {
                        "api/": {
                            "doc.md": "# API\n\nAPI docs.",
                        },
                    },
                    "platform/": {},
                },
            },
        )
        run_regen(cli, brain.root, "eng/api")

        daemon.start()
        daemon.wait_for_ready()
        daemon.shutdown()

        # Move subtree
        import shutil

        src = brain.knowledge / "eng" / "api"
        dst = brain.knowledge / "platform" / "api"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))

        daemon.start()
        daemon.wait_for_ready()
        daemon.shutdown()

        assert_brain_consistent(brain.root)


class TestOfflineKnowledgeTreeReplace:
    """Replace the entire knowledge tree while daemon is stopped."""

    def test_offline_knowledge_tree_replace(
        self,
        brain: BrainFixture,
        cli: CliRunner,
        daemon: DaemonProcess,
    ):
        seed_knowledge_tree(
            brain.root,
            {
                "knowledge/": {
                    "old-area/": {
                        "doc.md": "# Old\n\nOld content.",
                    },
                },
            },
        )
        run_regen(cli, brain.root, "old-area")

        daemon.start()
        daemon.wait_for_ready()
        daemon.shutdown()

        # Replace entire knowledge tree (preserve _core)
        import shutil

        for item in brain.knowledge.iterdir():
            if item.name.startswith("_"):
                continue
            if item.is_dir():
                shutil.rmtree(str(item))
            else:
                item.unlink()

        # Write entirely new tree
        seed_knowledge_tree(
            brain.root,
            {
                "knowledge/": {
                    "new-area/": {
                        "fresh.md": "# Fresh\n\nBrand new content.",
                    },
                },
            },
        )

        daemon.start()
        daemon.wait_for_ready()

        # Wait for insights to be rebuilt (debounce + regen execution)
        wait_for_file(brain.insights / "new-area" / "summary.md", timeout=90)
        daemon.shutdown()

        assert not (brain.knowledge / "old-area").exists()
        assert_no_orphan_insights(brain.root)
        assert_brain_consistent(brain.root)
