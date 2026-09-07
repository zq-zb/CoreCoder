"""GitHub Server 通过真实 MCP 握手暴露只读工具的集成测试。"""

import sys
from pathlib import Path

from corecoder.mcp_manager import MCPManager, MCPServerConfig

SERVER = Path(__file__).parents[1] / "examples" / "github_mcp_server.py"


def test_github_mcp_tools_are_namespaced_and_retry_safe():
    manager = MCPManager()
    manager.add_server(MCPServerConfig("github", sys.executable, (str(SERVER),)))
    try:
        tools = {tool.name: tool for tool in manager.create_tools()}
    finally:
        manager.close()

    assert set(tools) == {
        "github__read_issue",
        "github__read_pull_request",
        "github__get_pull_request_diff",
        "github__list_failed_workflow_runs",
        "github__get_workflow_run_failure",
    }
    assert all(tool.retry_safe is True for tool in tools.values())
