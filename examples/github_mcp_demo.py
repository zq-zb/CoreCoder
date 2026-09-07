"""演示 CoreCoder 发现 GitHub MCP 工具，可选读取一个真实 Issue。"""

import argparse
import sys
from pathlib import Path

from corecoder.mcp_manager import MCPManager, MCPServerConfig


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", help="GitHub 仓库，格式 owner/name")
    parser.add_argument("--issue", type=int, help="要读取的 Issue 编号")
    parser.add_argument("--pr", type=int, help="要读取的 Pull Request 编号")
    parser.add_argument("--diff", action="store_true", help="同时读取 Pull Request Diff")
    parser.add_argument("--run", type=int, help="要诊断的 GitHub Actions Run ID")
    options = parser.parse_args()

    server = Path(__file__).with_name("github_mcp_server.py")
    manager = MCPManager()
    manager.add_server(MCPServerConfig("github", sys.executable, (str(server),), call_timeout=30.0))
    try:
        tools = {tool.name: tool for tool in manager.create_tools()}
        print(f"Agent 发现的 GitHub 工具：{list(tools)}")
        if options.repo and options.issue:
            print(tools["github__read_issue"].execute(
                repository=options.repo,
                issue_number=options.issue,
            ))
        elif options.repo and options.pr:
            print(tools["github__read_pull_request"].execute(
                repository=options.repo,
                pull_number=options.pr,
            ))
            if options.diff:
                print(tools["github__get_pull_request_diff"].execute(
                    repository=options.repo,
                    pull_number=options.pr,
                ))
        elif options.repo and options.run:
            print(tools["github__get_workflow_run_failure"].execute(
                repository=options.repo,
                run_id=options.run,
            ))
        else:
            print("未传入 Issue 或 PR 参数，本次只验证 MCP 工具发现。")
    finally:
        manager.close()


if __name__ == "__main__":
    main()
