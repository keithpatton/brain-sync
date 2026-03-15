"""E2E test: git clone scenario — DB rebuild from manifests + sidecars.

Simulates cloning a brain repo by copying everything except the SQLite DB.
Verifies the daemon can start, rebuild state, and skip unnecessary work.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from brain_sync.layout import INSIGHT_STATE_FILENAME, area_summary_path
from tests.e2e.harness.brain import BrainFixture, create_brain, seed_knowledge_tree, seed_sources
from tests.e2e.harness.daemon import DaemonProcess
from tests.e2e.harness.wait import wait_for_db

pytestmark = pytest.mark.e2e


def _clone_brain(src: BrainFixture, dest_root: Path, config_dir: Path) -> BrainFixture:
    """Simulate git clone: copy the repo checkout without any runtime DB."""
    dest = dest_root / "brain"
    shutil.copytree(src.root, dest)
    # Update config to point to cloned brain
    config = {"brain_root": str(dest)}
    (config_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")
    return BrainFixture(root=dest)


class TestGitCloneScenario:
    @pytest.mark.timeout(60)
    def test_clone_restores_sources_and_skips_regen(self, tmp_path: Path):
        """After git clone (no DB), daemon rebuilds state from manifests + sidecars."""
        # --- Phase 1: Set up original brain with sources + regen ---
        orig_tmp = tmp_path / "original"
        orig_tmp.mkdir()
        orig_config_dir = orig_tmp / ".brain-sync"
        orig_config_dir.mkdir()
        config = {"brain_root": str(orig_tmp / "brain")}
        (orig_config_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")
        orig = create_brain(orig_tmp)

        # Seed knowledge tree
        seed_knowledge_tree(
            orig.root,
            {
                "knowledge/": {
                    "project/": {
                        "overview.md": "# Overview\n\nProject overview content.",
                        "design.md": "# Design\n\nDesign decisions here.",
                    },
                },
            },
        )

        # Seed sources
        seed_sources(
            orig.root,
            [
                {
                    "canonical_id": "confluence:11111",
                    "source_url": "https://acme.atlassian.net/wiki/spaces/ENG/pages/11111",
                    "target_path": "project",
                },
                {
                    "canonical_id": "confluence:22222",
                    "source_url": "https://acme.atlassian.net/wiki/spaces/ENG/pages/22222",
                    "target_path": "project",
                },
            ],
        )

        # Run regen to create sidecars + summaries
        import asyncio

        from brain_sync.llm.fake import FakeBackend
        from brain_sync.regen import RegenConfig, regen_single_folder

        backend = FakeBackend(mode="stable")
        regen_config = RegenConfig(model="fake-model", effort="low", timeout=30)
        asyncio.get_event_loop().run_until_complete(
            regen_single_folder(orig.root, "project", config=regen_config, backend=backend)
        )

        # Verify originals have sidecar + summary
        orig_sidecar = orig.insights_dir("project") / INSIGHT_STATE_FILENAME
        orig_summary = area_summary_path(orig.root, "project")
        assert orig_sidecar.exists()
        assert orig_summary.exists()
        sidecar_data_before = orig_sidecar.read_bytes()
        summary_before = orig_summary.read_text(encoding="utf-8")

        # --- Phase 2: Simulate git clone ---
        clone_tmp = tmp_path / "clone"
        clone_tmp.mkdir()
        clone_config_dir = clone_tmp / ".brain-sync"
        clone_config_dir.mkdir()
        clone_db_path = clone_config_dir / "db" / "brain-sync.sqlite"
        cloned = _clone_brain(orig, clone_tmp, clone_config_dir)

        # Verify: no DB in clone
        assert not clone_db_path.exists()
        # But manifests and sidecars survived
        assert (cloned.root / ".brain-sync" / "sources").is_dir()
        assert (cloned.insights_dir("project") / INSIGHT_STATE_FILENAME).exists()

        # --- Phase 3: Start daemon on cloned brain ---
        capture_dir = clone_tmp / "prompts"
        capture_dir.mkdir()

        daemon = DaemonProcess(
            brain_root=cloned.root,
            config_dir=clone_config_dir,
            capture_dir=capture_dir,
        )
        try:
            daemon.start()
            daemon.wait_for_ready(timeout=20)

            # Wait for DB to exist and have sync_cache rows restored from manifests
            wait_for_db(
                clone_db_path,
                "SELECT COUNT(*) FROM sync_cache",
                lambda rows: rows[0][0] >= 2,
                timeout=15,
            )

            # Verify sync_cache has both sources
            conn = sqlite3.connect(str(clone_db_path))
            rows = conn.execute("SELECT canonical_id FROM sync_cache").fetchall()
            conn.close()
            cids = {r[0] for r in rows}
            assert "confluence:11111" in cids
            assert "confluence:22222" in cids

            # Summaries still exist and unchanged
            clone_summary_path = area_summary_path(cloned.root, "project")
            assert clone_summary_path.exists()
            clone_summary = clone_summary_path.read_text(encoding="utf-8")
            assert clone_summary == summary_before

            # Sidecars intact and match pre-clone values
            clone_sidecar = (cloned.insights_dir("project") / INSIGHT_STATE_FILENAME).read_bytes()
            assert clone_sidecar == sidecar_data_before

            # No prompt captures — no regen should have happened
            prompt_files = list(capture_dir.glob("*.prompt.txt"))
            assert len(prompt_files) == 0, f"Unexpected regen prompts: {[f.name for f in prompt_files]}"

        finally:
            daemon.shutdown()
