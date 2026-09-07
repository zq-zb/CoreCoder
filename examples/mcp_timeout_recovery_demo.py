"""演示 MCP 工具超时后的隔离、清理和手动重连。"""

import logging
import sys
import time
from pathlib import Path

from corecoder.mcp_runtime import MCPRuntime, MCPRuntimeUnhealthyError, MCPToolTimeoutError


def main() -> None:
    """让慢工具超时，再验证拒绝新调用和重连恢复。"""

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    project_root = Path(__file__).parents[1]
    slow_server = project_root / "tests" / "fixtures" / "mcp_slow_server.py"
    normal_server = Path(__file__).with_name("mcp_demo_server.py")
    runtime = MCPRuntime()

    print("1. 连接慢速测试 Server", flush=True)
    runtime.connect(sys.executable, [str(slow_server)])

    started = time.perf_counter()
    try:
        runtime.call_tool(
            "slow_echo",
            {"text": "hello", "delay": 10.0},
            timeout=0.05,
        )
    except MCPToolTimeoutError as error:
        elapsed = time.perf_counter() - started
        print(f"2. 约 {elapsed:.2f} 秒后检测到超时：{error}", flush=True)

    rejected_at = time.perf_counter()
    try:
        runtime.list_tools()
    except MCPRuntimeUnhealthyError as error:
        elapsed = time.perf_counter() - rejected_at
        print(f"3. 新请求在 {elapsed:.4f} 秒内被拒绝：{error}", flush=True)

    print("4. 优雅等待 0.05 秒；仍未结束则取消 Owner Task 并强制清理", flush=True)
    close_started = time.perf_counter()
    runtime.close(graceful_timeout=0.05, force_timeout=5.0)
    close_elapsed = time.perf_counter() - close_started
    print(f"   旧连接在 {close_elapsed:.2f} 秒内完成清理，没有等待工具完整运行 10 秒", flush=True)

    print("5. 连接正常 Server，开启新的健康周期", flush=True)
    runtime.connect(sys.executable, [str(normal_server)])
    try:
        result = runtime.call_tool("add", {"a": 20, "b": 22})
        print(f"6. 重连后 add 调用成功：{result.text}", flush=True)
    finally:
        runtime.close()
        print("7. Runtime 已关闭", flush=True)


if __name__ == "__main__":
    main()
