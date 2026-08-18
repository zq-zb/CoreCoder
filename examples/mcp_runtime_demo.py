"""观察同步主线程如何把异步任务提交给 MCP Runtime。"""

import threading

from corecoder.mcp_runtime import MCPRuntime


async def background_task() -> str:
    """这段异步代码会由 Runtime 的后台事件循环执行。"""

    worker_name = threading.current_thread().name
    print(f"2. 异步任务运行在线程：{worker_name}")
    return "后台任务完成"


def main() -> None:
    """在主线程启动 Runtime、提交任务并关闭。"""

    runtime = MCPRuntime()
    print(f"1. Agent 所在线程：{threading.current_thread().name}")

    runtime.start()
    try:
        result = runtime._submit(background_task())
        print(f"3. 主线程收到结果：{result}")
    finally:
        runtime.close()
        print("4. Runtime 已关闭")


if __name__ == "__main__":
    main()
