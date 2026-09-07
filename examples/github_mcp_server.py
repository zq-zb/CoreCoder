"""为 CoreCoder 提供 GitHub Issue 和 Actions 诊断的只读 MCP Server。"""

import json
from collections.abc import Callable
from typing import Any

from mcp.server import MCPServer
from mcp.types import CallToolResult, TextContent, ToolAnnotations

from corecoder.github_service import GitHubService, GitHubServiceError

mcp = MCPServer("corecoder-github-readonly")
service = GitHubService()
READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=True,
)


def _execute(operation: Callable[[], dict[str, Any]]) -> CallToolResult:
    """统一返回文本和结构化数据，并保留可重试标记。"""

    try:
        data = operation()
    except (GitHubServiceError, ValueError) as error:
        structured = {
            "error": str(error),
            "retryable": isinstance(error, GitHubServiceError) and error.retryable,
        }
        return CallToolResult(
            content=[TextContent(type="text", text=str(error))],
            structured_content=structured,
            is_error=True,
        )
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(data, ensure_ascii=False, indent=2))],
        structured_content=data,
    )


@mcp.tool(annotations=READ_ONLY)
def read_issue(repository: str, issue_number: int) -> CallToolResult:
    """读取 GitHub Issue 的需求、标签、作者和链接；repository 使用 owner/name。"""

    return _execute(lambda: service.read_issue(repository, issue_number))


@mcp.tool(annotations=READ_ONLY)
def read_pull_request(repository: str, pull_number: int) -> CallToolResult:
    """读取 GitHub Pull Request 摘要、分支、改动规模和链接。"""

    return _execute(lambda: service.read_pull_request(repository, pull_number))


@mcp.tool(annotations=READ_ONLY)
def get_pull_request_diff(repository: str, pull_number: int) -> CallToolResult:
    """读取 GitHub Pull Request 的 unified diff，输出过大时自动截断。"""

    return _execute(lambda: service.get_pull_request_diff(repository, pull_number))


@mcp.tool(annotations=READ_ONLY)
def list_failed_workflow_runs(repository: str, limit: int = 5) -> CallToolResult:
    """列出仓库最近失败的 GitHub Actions Workflow Run。"""

    return _execute(lambda: service.list_failed_workflow_runs(repository, limit))


@mcp.tool(annotations=READ_ONLY)
def get_workflow_run_failure(repository: str, run_id: int) -> CallToolResult:
    """读取某次失败 Workflow Run 的 Job、失败 Step 和失败日志。"""

    return _execute(lambda: service.get_workflow_run_failure(repository, run_id))


if __name__ == "__main__":
    mcp.run()
