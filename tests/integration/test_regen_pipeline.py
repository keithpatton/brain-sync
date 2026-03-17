"""Phase 1 integration tests: regen pipeline with FakeBackend (real FS + SQLite)."""

from __future__ import annotations

from pathlib import Path

import pytest

from brain_sync.application.insights import load_insight_state
from brain_sync.brain.layout import area_summary_path
from brain_sync.llm.fake import FakeBackend
from brain_sync.regen import RegenConfig, regen_path, regen_single_folder

pytestmark = pytest.mark.integration


class TestRegenWithFakeBackend:
    """Full regen pipeline with fake backend, real FS + SQLite."""

    async def test_creates_summary(self, brain: Path):
        """Regen with fake backend creates the co-located summary."""
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "overview.md").write_text("# Overview\n\nProject overview.", encoding="utf-8")

        backend = FakeBackend(mode="stable")
        config = RegenConfig(model="fake-model", effort="low", timeout=30)

        result = await regen_single_folder(
            brain,
            "project",
            config=config,
            backend=backend,
        )

        assert result.action == "regenerated"
        summary = area_summary_path(brain, "project")
        assert summary.exists()
        content = summary.read_text(encoding="utf-8")
        assert "[fake-" in content  # deterministic fingerprint

    async def test_stable_content_no_rewrite(self, brain: Path):
        """Second regen with unchanged content should skip (content hash match)."""
        kdir = brain / "knowledge" / "stable"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc\n\nStable content.", encoding="utf-8")

        backend = FakeBackend(mode="stable")
        config = RegenConfig(model="fake-model", effort="low", timeout=30)

        # First regen — creates summary
        r1 = await regen_single_folder(brain, "stable", config=config, backend=backend)
        assert r1.action == "regenerated"

        # Second regen — content hash unchanged, should skip
        r2 = await regen_single_folder(brain, "stable", config=config, backend=backend)
        assert r2.action == "skipped_unchanged"

    async def test_regen_path_walks_up(self, brain: Path):
        """regen_path with fake backend walks up from leaf to root."""
        # Create nested structure
        leaf = brain / "knowledge" / "eng" / "backend"
        leaf.mkdir(parents=True)
        (leaf / "api.md").write_text("# API\n\nEndpoints.", encoding="utf-8")
        parent = brain / "knowledge" / "eng"
        (parent / "readme.md").write_text("# Eng\n\nEngineering.", encoding="utf-8")

        backend = FakeBackend(mode="stable")
        config = RegenConfig(model="fake-model", effort="low", timeout=30)

        count = await regen_path(
            brain,
            "eng/backend",
            config=config,
            backend=backend,
        )

        # Should have regenerated leaf + parent + root
        assert count >= 2
        assert area_summary_path(brain, "eng/backend").exists()
        assert area_summary_path(brain, "eng").exists()

    async def test_insight_state_persisted(self, brain: Path):
        """Regen should persist InsightState to SQLite."""
        kdir = brain / "knowledge" / "persisted"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc\n\nContent.", encoding="utf-8")

        backend = FakeBackend(mode="stable")
        config = RegenConfig(model="fake-model", effort="low", timeout=30)

        await regen_single_folder(brain, "persisted", config=config, backend=backend)

        istate = load_insight_state(brain, "persisted")
        assert istate is not None
        assert istate.regen_status == "idle"
        assert istate.content_hash is not None
        assert istate.summary_hash is not None

    async def test_backend_receives_prompt(self, brain: Path):
        """Fake backend captures the prompt text."""
        kdir = brain / "knowledge" / "captured"
        kdir.mkdir(parents=True)
        (kdir / "notes.md").write_text("# Notes\n\nImportant notes here.", encoding="utf-8")

        backend = FakeBackend(mode="stable")
        config = RegenConfig(model="fake-model", effort="low", timeout=30)

        await regen_single_folder(brain, "captured", config=config, backend=backend)

        assert backend.call_count == 1
        assert backend.last_prompt is not None
        # Prompt should contain the knowledge file content
        assert "Important notes here" in backend.last_prompt


class TestPromptCapture:
    """Prompt capture writes artifacts to disk."""

    async def test_capture_writes_file(self, brain: Path, tmp_path: Path, monkeypatch):
        """Prompt capture saves to disk when env var is set."""
        capture_dir = tmp_path / "prompts"
        monkeypatch.setenv("BRAIN_SYNC_CAPTURE_PROMPTS", str(capture_dir))

        kdir = brain / "knowledge" / "cap"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc\n\nCapture test.", encoding="utf-8")

        backend = FakeBackend(mode="stable")
        config = RegenConfig(model="fake-model", effort="low", timeout=30)

        await regen_single_folder(brain, "cap", config=config, backend=backend)

        assert capture_dir.exists()
        prompt_files = list(capture_dir.glob("*.prompt.txt"))
        assert len(prompt_files) >= 1
        content = prompt_files[0].read_text(encoding="utf-8")
        assert "Capture test" in content

    async def test_prompt_contains_expected_files(self, brain: Path, tmp_path: Path, monkeypatch):
        """Captured prompt includes knowledge file content."""
        capture_dir = tmp_path / "prompts"
        monkeypatch.setenv("BRAIN_SYNC_CAPTURE_PROMPTS", str(capture_dir))

        kdir = brain / "knowledge" / "multi"
        kdir.mkdir(parents=True)
        (kdir / "alpha.md").write_text("# Alpha\n\nAlpha content here.", encoding="utf-8")
        (kdir / "beta.md").write_text("# Beta\n\nBeta content here.", encoding="utf-8")

        backend = FakeBackend(mode="stable")
        config = RegenConfig(model="fake-model", effort="low", timeout=30)

        await regen_single_folder(brain, "multi", config=config, backend=backend)

        prompt_files = list(capture_dir.glob("*.prompt.txt"))
        assert len(prompt_files) >= 1
        content = prompt_files[0].read_text(encoding="utf-8")
        assert "Alpha content here" in content
        assert "Beta content here" in content
