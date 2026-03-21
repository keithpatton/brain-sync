from __future__ import annotations

from pathlib import Path

import pytest

from brain_sync.brain.fileops import canonical_prefix
from brain_sync.brain.managed_markdown import prepend_managed_header
from brain_sync.brain.manifest import read_source_manifest, write_source_manifest
from tests.e2e.harness.cli import CliRunner

pytestmark = pytest.mark.system

TEST_URL = "test://doc/finalize-123"
TEST_CID = "test:finalize-123"


def _set_materialized_manifest(root: Path, knowledge_path: str) -> None:
    manifest = read_source_manifest(root, TEST_CID)
    assert manifest is not None
    manifest.knowledge_state = "materialized"
    manifest.knowledge_path = knowledge_path
    manifest.content_hash = "sha256:abc"
    manifest.remote_fingerprint = "rev-1"
    manifest.materialized_utc = "2026-03-20T00:00:00+00:00"
    write_source_manifest(root, manifest)


def _write_materialized_file(root: Path, knowledge_path: str) -> None:
    path = root / "knowledge" / knowledge_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(prepend_managed_header(TEST_CID, "# Test doc\n"), encoding="utf-8")


def _register_materialized_source(cli: CliRunner, brain_root: Path, *, create_file: bool) -> str:
    init_result = cli.run("init", str(brain_root))
    assert init_result.returncode == 0, init_result.stderr

    add_result = cli.run("add", TEST_URL, "--path", "area", "--root", str(brain_root))
    assert add_result.returncode == 0, add_result.stderr

    knowledge_path = f"area/{canonical_prefix(TEST_CID)}doc.md"
    _set_materialized_manifest(brain_root, knowledge_path)
    if create_file:
        _write_materialized_file(brain_root, knowledge_path)
    return knowledge_path


class TestFinalizeMissingCli:
    def test_list_prints_missing_state_for_registered_source(self, cli: CliRunner, brain_root: Path) -> None:
        _register_materialized_source(cli, brain_root, create_file=False)

        reconcile = cli.run("reconcile", "--root", str(brain_root))
        assert reconcile.returncode == 0, reconcile.stderr

        result = cli.run("list", "--root", str(brain_root))

        assert result.returncode == 0
        assert "State: missing" in result.stderr

    def test_finalize_missing_finalizes_missing_source_in_one_call(self, cli: CliRunner, brain_root: Path) -> None:
        _register_materialized_source(cli, brain_root, create_file=False)

        first = cli.run("reconcile", "--root", str(brain_root))
        assert first.returncode == 0, first.stderr

        result = cli.run("finalize-missing", TEST_CID, "--root", str(brain_root))

        assert result.returncode == 0
        assert "Result: finalized" in result.stderr
        assert read_source_manifest(brain_root, TEST_CID) is None

    def test_finalize_missing_after_restart_still_finalizes_in_one_call(
        self,
        cli: CliRunner,
        brain_root: Path,
    ) -> None:
        _register_materialized_source(cli, brain_root, create_file=False)

        first = cli.run("reconcile", "--root", str(brain_root))
        second = cli.run("reconcile", "--root", str(brain_root))
        assert first.returncode == 0, first.stderr
        assert second.returncode == 0, second.stderr

        result = cli.run("finalize-missing", TEST_CID, "--root", str(brain_root))

        assert result.returncode == 0
        assert "Result: finalized" in result.stderr
        assert read_source_manifest(brain_root, TEST_CID) is None

    def test_finalize_missing_returns_not_missing_when_source_reappears(self, cli: CliRunner, brain_root: Path) -> None:
        knowledge_path = _register_materialized_source(cli, brain_root, create_file=False)

        reconcile = cli.run("reconcile", "--root", str(brain_root))
        assert reconcile.returncode == 0, reconcile.stderr

        _write_materialized_file(brain_root, knowledge_path)

        result = cli.run("finalize-missing", TEST_CID, "--root", str(brain_root))

        assert result.returncode == 1
        assert "Result: not_missing" in result.stderr
        manifest = read_source_manifest(brain_root, TEST_CID)
        assert manifest is not None
        assert manifest.knowledge_state == "stale"

    def test_finalize_missing_rejects_url_targeting(self, cli: CliRunner, brain_root: Path) -> None:
        init_result = cli.run("init", str(brain_root))
        assert init_result.returncode == 0, init_result.stderr

        result = cli.run("finalize-missing", "https://example.com/page", "--root", str(brain_root))

        assert result.returncode == 1
        assert "requires a canonical ID" in result.stderr

    def test_finalize_missing_rejects_windows_path_targeting(self, cli: CliRunner, brain_root: Path) -> None:
        init_result = cli.run("init", str(brain_root))
        assert init_result.returncode == 0, init_result.stderr

        result = cli.run("finalize-missing", r"C:\temp\page", "--root", str(brain_root))

        assert result.returncode == 1
        assert "requires a canonical ID" in result.stderr

    def test_doctor_deregister_missing_is_rejected_with_migration_hint(self, cli: CliRunner, brain_root: Path) -> None:
        init_result = cli.run("init", str(brain_root))
        assert init_result.returncode == 0, init_result.stderr

        result = cli.run("doctor", "--deregister-missing", "--root", str(brain_root))

        assert result.returncode == 1
        assert "finalize-missing" in result.stderr
