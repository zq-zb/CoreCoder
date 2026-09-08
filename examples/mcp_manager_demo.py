"""演示多个 MCP Server 的工具命名与故障隔离。"""

import logging
import sys
from pathlib import Path

from corecoder.mcp_manager import MCPManager, MCPServerConfig
from corecoder.mcp_runtime import MCPToolTimeoutError


def main() -> None:
    """让慢 Server 超时，同时验证正常 Server 继续服务。"""

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    root = Path(__file__).parents[1]
    normal_server = Path(__file__).with_name("mcp_demo_server.py")
    slow_server = root / "tests" / "fixtures" / "mcp_slow_server.py"

    manager = MCPManager()
    manager.add_server(MCPServerConfig("math", sys.executable, (str(normal_server),)))
    manager.add_server(MCPServerConfig("slow", sys.executable, (str(slow_server),)))

    try:
        tools = manager.create_tools()
        print(f"1. Agent 可见的工具：{[tool.name for tool in tools]}", flush=True)

        try:
            manager.call_tool(
                "slow",
                "slow_echo",
                {"text": "hello", "delay": 0.2},
                timeout=0.05,
            )
        except MCPToolTimeoutError:
            print("2. slow Server 调用超时并进入 DEGRADED", flush=True)

        result = manager.call_tool("math", "add", {"a": 20, "b": 22})
        print(f"3. math Server 未受影响，add 返回：{result.text}", flush=True)

        manager.restart_server("slow")
        recovered = manager.call_tool("slow", "slow_echo", {"text": "recovered", "delay": 0})
        print(f"4. 只重启 slow Server，恢复后返回：{recovered.text}", flush=True)
    finally:
        manager.close()
        print("5. 所有 Server 已清理", flush=True)


if __name__ == "__main__":
    main()
