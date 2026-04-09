"""Real stdio transport smoke tests for the MCP server."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from brain_sync.application.init import init_brain
from brain_sync.brain.layout import area_insights_dir
from brain_sync.runtime.repository import daemon_root_id
from tests.e2e.harness.cli import CliRunner
from tests.e2e.harness.daemon import DaemonProcess
from tests.harness.isolation import build_subprocess_env, layout_from_config_dir

pytestmark = pytest.mark.mcp


def _seed_queryable_brain(root: Path, *, area_name: str = "AAA") -> None:
    init_brain(root)

    core_insights = area_insights_dir(root, "_core")
    core_insights.mkdir(parents=True, exist_ok=True)
    (core_insights / "summary.md").write_text("# Core Summary\n\nOverview of the brain.", encoding="utf-8")

    area = root / "knowledge" / "initiatives" / area_name
    area.mkdir(parents=True, exist_ok=True)
    (area / "doc.md").write_text(f"{area_name} knowledge doc.", encoding="utf-8")

    area_insights = area_insights_dir(root, f"initiatives/{area_name}")
    area_insights.mkdir(parents=True, exist_ok=True)
    (area_insights / "summary.md").write_text(f"# {area_name}\n\nPlatform {area_name} summary.", encoding="utf-8")


def _stdio_server(repo_root: Path, config_dir: Path) -> StdioServerParameters:
    env = build_subprocess_env(layout=layout_from_config_dir(config_dir), repo_root=repo_root, llm_backend=None)

    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "brain_sync.interfaces.mcp.launcher"],
        env=env,
        cwd=repo_root,
    )


@pytest.mark.regression
async def test_stdio_server_lists_tools_and_answers_query(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    config_dir = tmp_path / ".brain-sync"
    config_dir.mkdir()

    root = tmp_path / "brain"
    _seed_queryable_brain(root)
    (config_dir / "config.json").write_text(json.dumps({"brains": [str(root)]}), encoding="utf-8")

    async with stdio_client(_stdio_server(repo_root, config_dir)) as (read_stream, write_stream):
        session = ClientSession(read_stream, write_stream)
        async with session:
            init_result = await session.initialize()
            assert init_result.serverInfo.name == "brain-sync"

            tools = await session.list_tools()
            tool_names = {tool.name for tool in tools.tools}
            assert "brain_sync_query" in tool_names
            assert "brain_sync_open_area" in tool_names
            assert "brain_sync_tree" in tool_names
            assert "brain_sync_sync" in tool_names
            assert "brain_sync_setup_status" in tool_names
            assert "brain_sync_start" in tool_names

            result = await session.call_tool("brain_sync_query", {"query": "AAA"})
            tree_result = await session.call_tool("brain_sync_tree", {})

    assert result.isError is False
    assert len(result.content) == 1
    response = json.loads(result.content[0].text)
    assert response["status"] == "ok"
    assert response["matches"][0]["path"] == "initiatives/AAA"
    assert response["total_areas"] >= 1

    assert tree_result.isError is False
    assert len(tree_result.content) == 1
    tree_payload = json.loads(tree_result.content[0].text)
    assert tree_payload["status"] == "ok"
    assert tree_payload["nodes"][0]["path"] == ""
    assert any(node["path"] == "initiatives/AAA" for node in tree_payload["nodes"])


@pytest.mark.regression
async def test_stdio_launcher_bootstrap_mode_transitions_to_full_after_attach(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    config_dir = tmp_path / ".brain-sync"
    config_dir.mkdir()

    root = tmp_path / "brain"
    _seed_queryable_brain(root)

    async with stdio_client(_stdio_server(repo_root, config_dir)) as (read_stream, write_stream):
        session = ClientSession(read_stream, write_stream)
        async with session:
            init_result = await session.initialize()
            assert init_result.serverInfo.name == "brain-sync"

            tools = await session.list_tools()
            tool_names = {tool.name for tool in tools.tools}
            assert "brain_sync_setup_status" in tool_names
            assert "brain_sync_attach_root" in tool_names
            assert "brain_sync_start" in tool_names
            assert "brain_sync_query" in tool_names
            assert "brain_sync_open_area" in tool_names

            status_result = await session.call_tool("brain_sync_setup_status", {})
            start_result = await session.call_tool("brain_sync_start", {})
            query_before_attach = await session.call_tool("brain_sync_query", {"query": "AAA"})

            attach_result = await session.call_tool("brain_sync_attach_root", {"root": str(root)})
            query_result = await session.call_tool("brain_sync_query", {"query": "AAA"})

    status_payload = json.loads(status_result.content[0].text)
    assert status_payload["status"] == "ok"
    assert status_payload["setup"]["ready"] is False

    start_payload = json.loads(start_result.content[0].text)
    assert start_payload["status"] == "ok"
    assert start_payload["result"] == "setup_required"

    assert query_before_attach.isError is True
    assert any("brain_sync_attach_root" in item.text for item in query_before_attach.content if hasattr(item, "text"))

    attach_payload = json.loads(attach_result.content[0].text)
    assert attach_payload["status"] == "ok"
    assert attach_payload["root"] == str(root.resolve())
    assert attach_payload["setup"]["ready"] is True

    query_payload = json.loads(query_result.content[0].text)
    assert query_payload["status"] == "ok"
    assert query_payload["matches"][0]["path"] == "initiatives/AAA"


@pytest.mark.regression
async def test_stdio_launcher_bootstrap_mode_transitions_to_full_after_init(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    config_dir = tmp_path / ".brain-sync"
    config_dir.mkdir()

    root = tmp_path / "brain"

    async with stdio_client(_stdio_server(repo_root, config_dir)) as (read_stream, write_stream):
        session = ClientSession(read_stream, write_stream)
        async with session:
            init_result = await session.initialize()
            assert init_result.serverInfo.name == "brain-sync"

            tools = await session.list_tools()
            tool_names = {tool.name for tool in tools.tools}
            assert "brain_sync_init" in tool_names
            assert "brain_sync_query" in tool_names

            query_before_init = await session.call_tool("brain_sync_query", {"query": "AAA"})
            init_tool_result = await session.call_tool("brain_sync_init", {"root": str(root)})
            tree_result = await session.call_tool("brain_sync_tree", {})

    init_payload = json.loads(init_tool_result.content[0].text)
    assert init_payload["status"] == "ok"
    assert init_payload["root"] == str(root.resolve())
    assert init_payload["was_existing"] is False
    assert init_payload["setup"]["ready"] is True
    assert init_payload["setup"]["usable_active_root"] == str(root.resolve())

    assert query_before_init.isError is True
    assert any("brain_sync_init" in item.text for item in query_before_init.content if hasattr(item, "text"))

    tree_payload = json.loads(tree_result.content[0].text)
    assert tree_payload["status"] == "ok"
    assert tree_payload["nodes"][0]["path"] == ""


@pytest.mark.regression
async def test_stdio_launcher_exposes_daemon_admin_semantics(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    config_dir = tmp_path / ".brain-sync"
    config_dir.mkdir()

    root = tmp_path / "brain"
    _seed_queryable_brain(root)
    (config_dir / "config.json").write_text(json.dumps({"brains": [str(root)]}), encoding="utf-8")

    async with stdio_client(_stdio_server(repo_root, config_dir)) as (read_stream, write_stream):
        session = ClientSession(read_stream, write_stream)
        async with session:
            init_result = await session.initialize()
            assert init_result.serverInfo.name == "brain-sync"

            initial_status = await session.call_tool("brain_sync_status", {})
            start_result = await session.call_tool("brain_sync_start", {})
            running_status = await session.call_tool("brain_sync_status", {})
            restart_result = await session.call_tool("brain_sync_restart", {})
            stop_result = await session.call_tool("brain_sync_stop", {})
            final_status = await session.call_tool("brain_sync_status", {})

    initial_payload = json.loads(initial_status.content[0].text)
    assert initial_payload["status"] == "ok"
    assert initial_payload["setup"]["ready"] is True
    assert initial_payload["daemon"]["state"] == "not_running"

    start_payload = json.loads(start_result.content[0].text)
    assert start_payload["status"] == "ok"
    assert start_payload["result"] == "started"
    assert start_payload["daemon"]["state"] == "running"
    assert start_payload["daemon"]["controller_kind"] == "launcher-background"
    first_pid = start_payload["daemon"]["pid"]

    running_payload = json.loads(running_status.content[0].text)
    assert running_payload["status"] == "ok"
    assert running_payload["daemon"]["state"] == "running"
    assert running_payload["daemon"]["pid"] == first_pid

    restart_payload = json.loads(restart_result.content[0].text)
    assert restart_payload["status"] == "ok"
    assert restart_payload["result"] == "restarted"
    assert restart_payload["daemon"]["state"] == "running"
    assert restart_payload["daemon"]["controller_kind"] == "launcher-background"
    assert restart_payload["daemon"]["pid"] != first_pid

    stop_payload = json.loads(stop_result.content[0].text)
    assert stop_payload["status"] == "ok"
    assert stop_payload["result"] == "stopped"
    assert stop_payload["daemon"]["state"] == "not_running"
    assert stop_payload["daemon"]["snapshot_status"] == "stopped"

    final_payload = json.loads(final_status.content[0].text)
    assert final_payload["status"] == "ok"
    assert final_payload["daemon"]["state"] == "not_running"
    assert final_payload["daemon"]["snapshot_status"] == "stopped"


@pytest.mark.regression
async def test_stdio_launcher_adopts_terminal_foreground_daemon_for_full_tool_use(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    config_dir = tmp_path / ".brain-sync"
    config_dir.mkdir()

    root = tmp_path / "brain"
    _seed_queryable_brain(root)
    (config_dir / "config.json").write_text(json.dumps({"brains": [str(root)]}), encoding="utf-8")

    daemon = DaemonProcess(brain_root=root, config_dir=config_dir)
    daemon.start()
    daemon.wait_for_ready()

    try:
        async with stdio_client(_stdio_server(repo_root, config_dir)) as (read_stream, write_stream):
            session = ClientSession(read_stream, write_stream)
            async with session:
                init_result = await session.initialize()
                assert init_result.serverInfo.name == "brain-sync"

                status_result = await session.call_tool("brain_sync_status", {})
                start_result = await session.call_tool("brain_sync_start", {})
                query_result = await session.call_tool("brain_sync_query", {"query": "AAA"})
    finally:
        daemon.shutdown()

    status_payload = json.loads(status_result.content[0].text)
    assert status_payload["status"] == "ok"
    assert status_payload["daemon"]["state"] == "running"
    assert status_payload["daemon"]["controller_kind"] == "terminal-foreground"
    assert status_payload["daemon"]["pid"] == daemon.pid

    start_payload = json.loads(start_result.content[0].text)
    assert start_payload["status"] == "ok"
    assert start_payload["result"] == "already_running"
    assert start_payload["adopted"] is True
    assert start_payload["daemon"]["controller_kind"] == "terminal-foreground"
    assert start_payload["daemon"]["pid"] == daemon.pid

    query_payload = json.loads(query_result.content[0].text)
    assert query_payload["status"] == "ok"
    assert query_payload["matches"][0]["path"] == "initiatives/AAA"


@pytest.mark.regression
async def test_stdio_launcher_external_attach_root_fails_closed_after_session_started_old_root_daemon(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    config_dir = tmp_path / ".brain-sync"
    config_dir.mkdir()

    root_a = tmp_path / "brain-a"
    root_b = tmp_path / "brain-b"
    _seed_queryable_brain(root_a, area_name="AAA")
    _seed_queryable_brain(root_b, area_name="BBB")
    (config_dir / "config.json").write_text(json.dumps({"brains": [str(root_a)]}), encoding="utf-8")
    cli = CliRunner(config_dir=config_dir)

    try:
        async with stdio_client(_stdio_server(repo_root, config_dir)) as (read_stream, write_stream):
            session = ClientSession(read_stream, write_stream)
            async with session:
                init_result = await session.initialize()
                assert init_result.serverInfo.name == "brain-sync"

                query_a_result = await session.call_tool("brain_sync_query", {"query": "AAA"})

                attach_result = cli.run("attach-root", str(root_b))
                assert attach_result.returncode == 0, attach_result.stderr

                status_result = await session.call_tool("brain_sync_status", {})
                query_b_result = await session.call_tool("brain_sync_query", {"query": "BBB"})
    finally:
        cli.run("attach-root", str(root_a))
        cli.run("stop")

    query_a_payload = json.loads(query_a_result.content[0].text)
    assert query_a_payload["status"] == "ok"
    assert query_a_payload["matches"][0]["path"] == "initiatives/AAA"

    status_payload = json.loads(status_result.content[0].text)
    assert status_payload["status"] == "ok"
    assert status_payload["setup"]["usable_active_root"] == str(root_b.resolve())
    assert status_payload["daemon"]["active_root"] == str(root_b.resolve())
    assert status_payload["daemon"]["daemon_root"] == daemon_root_id(root_a.resolve())
    assert status_payload["daemon"]["state"] == "stale"
    assert status_payload["daemon"]["reason"] == "root_mismatch"

    assert query_b_result.isError is True
    assert any("healthy daemon" in item.text for item in query_b_result.content if hasattr(item, "text"))


@pytest.mark.regression
async def test_stdio_launcher_external_attach_root_keeps_query_and_daemon_on_same_root(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    config_dir = tmp_path / ".brain-sync"
    config_dir.mkdir()

    root_a = tmp_path / "brain-a"
    root_b = tmp_path / "brain-b"
    _seed_queryable_brain(root_a, area_name="AAA")
    _seed_queryable_brain(root_b, area_name="BBB")
    (config_dir / "config.json").write_text(json.dumps({"brains": [str(root_a)]}), encoding="utf-8")
    cli = CliRunner(config_dir=config_dir)

    try:
        async with stdio_client(_stdio_server(repo_root, config_dir)) as (read_stream, write_stream):
            session = ClientSession(read_stream, write_stream)
            async with session:
                init_result = await session.initialize()
                assert init_result.serverInfo.name == "brain-sync"

                attach_result = cli.run("attach-root", str(root_b))
                assert attach_result.returncode == 0, attach_result.stderr

                query_result = await session.call_tool("brain_sync_query", {"query": "BBB"})
                status_result = await session.call_tool("brain_sync_status", {})
                stop_result = await session.call_tool("brain_sync_stop", {})
    finally:
        cli.run("attach-root", str(root_b))
        cli.run("stop")

    query_payload = json.loads(query_result.content[0].text)
    assert query_payload["status"] == "ok"
    assert query_payload["matches"][0]["path"] == "initiatives/BBB"

    status_payload = json.loads(status_result.content[0].text)
    assert status_payload["status"] == "ok"
    assert status_payload["setup"]["usable_active_root"] == str(root_b.resolve())
    assert status_payload["daemon"]["active_root"] == str(root_b.resolve())
    assert status_payload["daemon"]["controller_kind"] == "launcher-background"
    assert status_payload["daemon"]["state"] == "running"

    stop_payload = json.loads(stop_result.content[0].text)
    assert stop_payload["status"] == "ok"
    assert stop_payload["result"] == "stopped"
    assert stop_payload["daemon"]["active_root"] == str(root_b.resolve())


@pytest.mark.regression
async def test_stdio_launcher_external_attach_root_fails_closed_when_old_root_daemon_remains_live(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    config_dir = tmp_path / ".brain-sync"
    config_dir.mkdir()

    root_a = tmp_path / "brain-a"
    root_b = tmp_path / "brain-b"
    _seed_queryable_brain(root_a, area_name="AAA")
    _seed_queryable_brain(root_b, area_name="BBB")
    (config_dir / "config.json").write_text(json.dumps({"brains": [str(root_a)]}), encoding="utf-8")
    cli = CliRunner(config_dir=config_dir)

    assert cli.run("start").returncode == 0

    try:
        async with stdio_client(_stdio_server(repo_root, config_dir)) as (read_stream, write_stream):
            session = ClientSession(read_stream, write_stream)
            async with session:
                init_result = await session.initialize()
                assert init_result.serverInfo.name == "brain-sync"

                attach_result = cli.run("attach-root", str(root_b))
                assert attach_result.returncode == 0, attach_result.stderr

                query_result = await session.call_tool("brain_sync_query", {"query": "BBB"})
                status_result = await session.call_tool("brain_sync_status", {})
                stop_result = await session.call_tool("brain_sync_stop", {})
    finally:
        cli.run("attach-root", str(root_a))
        cli.run("stop")

    assert query_result.isError is True
    assert any("healthy daemon" in item.text for item in query_result.content if hasattr(item, "text"))

    status_payload = json.loads(status_result.content[0].text)
    assert status_payload["status"] == "ok"
    assert status_payload["setup"]["usable_active_root"] == str(root_b.resolve())
    assert status_payload["daemon"]["active_root"] == str(root_b.resolve())
    assert status_payload["daemon"]["daemon_root"] == daemon_root_id(root_a.resolve())
    assert status_payload["daemon"]["state"] == "stale"
    assert status_payload["daemon"]["reason"] == "root_mismatch"

    stop_payload = json.loads(stop_result.content[0].text)
    assert stop_payload["status"] == "ok"
    assert stop_payload["result"] == "not_running"
    assert stop_payload["daemon"]["state"] == "stale"
    assert stop_payload["daemon"]["reason"] == "root_mismatch"
