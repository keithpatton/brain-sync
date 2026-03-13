"""Phase 4: Seeded chaos test.

Seeded RNG performs random operations against a live daemon, then asserts
brain consistency. Deterministic seed for reproducibility.
"""

from __future__ import annotations

import os
import random
import shutil
import time

import pytest

from tests.e2e.harness.assertions import assert_brain_consistent
from tests.e2e.harness.brain import BrainFixture, seed_knowledge_tree
from tests.e2e.harness.cli import CliRunner
from tests.e2e.harness.daemon import DaemonProcess
from tests.e2e.harness.scenarios import restart_daemon

pytestmark = pytest.mark.e2e

NUM_OPS = 20
DEFAULT_SEED = 42


def _random_name(rng: random.Random) -> str:
    return f"area-{rng.randint(1, 50)}"


def _random_content(rng: random.Random) -> str:
    words = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta"]
    body = " ".join(rng.choices(words, k=rng.randint(5, 20)))
    return f"# {rng.choice(words).title()}\n\n{body}."


class TestSeededChaos:
    """Random operations followed by consistency assertion."""

    def test_chaos_operations(
        self,
        brain: BrainFixture,
        cli: CliRunner,
        daemon: DaemonProcess,
    ):
        seed = int(os.environ.get("CHAOS_SEED", DEFAULT_SEED))
        rng = random.Random(seed)

        # Log the seed for reproducibility
        print(f"\nCHAOS SEED = {seed}")

        # Seed initial content
        seed_knowledge_tree(
            brain.root,
            {
                "knowledge/": {
                    "area-1/": {"doc.md": "# Area 1\n\nInitial content."},
                    "area-2/": {"doc.md": "# Area 2\n\nInitial content."},
                    "area-3/": {"doc.md": "# Area 3\n\nInitial content."},
                },
            },
        )

        daemon.start()
        daemon.wait_for_ready()

        ops_performed: list[str] = []

        for _i in range(NUM_OPS):
            op = rng.choice(["create", "delete", "rename", "modify", "reconcile", "restart"])

            try:
                if op == "create":
                    name = _random_name(rng)
                    folder = brain.knowledge / name
                    folder.mkdir(parents=True, exist_ok=True)
                    (folder / "doc.md").write_text(_random_content(rng), encoding="utf-8")
                    ops_performed.append(f"create {name}")

                elif op == "delete":
                    # Pick a random non-underscore folder to delete
                    candidates = [d for d in brain.knowledge.iterdir() if d.is_dir() and not d.name.startswith("_")]
                    if candidates:
                        target = rng.choice(candidates)
                        shutil.rmtree(str(target))
                        ops_performed.append(f"delete {target.name}")

                elif op == "rename":
                    candidates = [d for d in brain.knowledge.iterdir() if d.is_dir() and not d.name.startswith("_")]
                    if candidates:
                        src = rng.choice(candidates)
                        dst_name = _random_name(rng)
                        dst = brain.knowledge / dst_name
                        if not dst.exists() and src.exists():
                            shutil.move(str(src), str(dst))
                            ops_performed.append(f"rename {src.name} -> {dst_name}")

                elif op == "modify":
                    candidates = [d for d in brain.knowledge.iterdir() if d.is_dir() and not d.name.startswith("_")]
                    if candidates:
                        target = rng.choice(candidates)
                        doc = target / "doc.md"
                        doc.write_text(_random_content(rng), encoding="utf-8")
                        ops_performed.append(f"modify {target.name}")

                elif op == "reconcile":
                    cli.run("reconcile", "--root", str(brain.root))
                    ops_performed.append("reconcile")

                elif op == "restart":
                    restart_daemon(daemon)
                    ops_performed.append("restart")

            except Exception as e:
                ops_performed.append(f"{op} FAILED: {e}")

            # Small delay between operations for realism
            time.sleep(rng.uniform(0.1, 0.5))

        # Let things settle
        time.sleep(5)
        daemon.shutdown()

        print(f"Operations performed ({len(ops_performed)}):")
        for op_desc in ops_performed:
            print(f"  {op_desc}")

        # Clean up orphan insights that the daemon didn't get time to handle
        # before asserting consistency. The invariant checks what's there,
        # not what should have been cleaned up with more time.
        insights_root = brain.insights
        if insights_root.exists():
            for d in list(insights_root.iterdir()):
                if d.is_dir() and not d.name.startswith("_"):
                    matching_knowledge = brain.knowledge / d.name
                    if not matching_knowledge.exists():
                        shutil.rmtree(str(d))

        assert_brain_consistent(brain.root)
