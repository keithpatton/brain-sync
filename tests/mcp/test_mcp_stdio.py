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
from tests.harness.isolation import build_subprocess_env, layout_from_config_dir

pytestmark = pytest.mark.mcp


def _seed_queryable_brain(root: Path) -> None:
    init_brain(root)

    core_insights = area_insights_dir(root, "_core")
    core_insights.mkdir(parents=True, exist_ok=True)
    (core_insights / "summary.md").write_text("# Core Summary\n\nOverview of the brain.", encoding="utf-8")

    area = root / "knowledge" / "initiatives" / "AAA"
    area.mkdir(parents=True, exist_ok=True)
    (area / "doc.md").write_text("AAA knowledge doc.", encoding="utf-8")

    area_insights = area_insights_dir(root, "initiatives/AAA")
    area_insights.mkdir(parents=True, exist_ok=True)
    (area_insights / "summary.md").write_text("# AAA\n\nPlatform AAA summary.", encoding="utf-8")


def _stdio_server(repo_root: Path, config_dir: Path) -> StdioServerParameters:
    env = build_subprocess_env(layout=layout_from_config_dir(config_dir), repo_root=repo_root, llm_backend=None)

    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "brain_sync.interfaces.mcp.server"],
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

            result = await session.call_tool("brain_sync_query", {"query": "AAA"})

    assert result.isError is False
    assert len(result.content) == 1
    response = json.loads(result.content[0].text)
    assert response["status"] == "ok"
    assert response["matches"][0]["path"] == "initiatives/AAA"
    assert response["total_areas"] >= 1
