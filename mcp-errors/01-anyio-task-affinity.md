# 01 · AnyIO 异步资源的 Task 归属错误

## 现象

Runtime 把 `PersistentMCPClient.connect()` 和 `close()` 分别提交到同一个后台事件循环，关闭时出现：

```text
RuntimeError: Attempted to exit cancel scope in a different task than it was entered in
```

复现命令：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_mcp_runtime.py::test_runtime_connects_and_closes_real_mcp_server -v
```

## 根因

`run_coroutine_threadsafe()` 每提交一次协程都会创建新的 asyncio Task：

```text
后台 Loop
├── Task A：connect()
└── Task B：close()
```

MCP SDK 的 stdio Client 底层使用 AnyIO CancelScope。该资源不仅要求在同一个线程和事件循环中使用，还要求由进入它的同一个 Task 负责退出。

## 错误方案

```python
runtime._submit(client.connect())
runtime._submit(client.close())
```

两次调用处于同一个 Loop，但不属于同一个 Task，因此无法正确退出资源上下文。

## 修复方向

创建一个长期存活的 Owner Task，让它负责完整生命周期：

```text
Owner Task
→ connect()
→ 等待命令
→ close()
```

主线程只向 Owner Task 发送命令，不再直接跨 Task 打开和关闭 MCP 资源。

## 验证结果

使用原复现命令重新运行，测试由失败变为通过：

```text
test_runtime_connects_and_closes_real_mcp_server PASSED
1 passed
```

全部 Runtime 测试同时通过，证明后台事件循环的启停、跨线程任务提交以及真实 MCP 连接生命周期可以共同工作。

## 面试中的简短讲法

> 在把同步 Agent 桥接到异步 MCP Client 时，我通过真实 stdio 集成测试发现 AnyIO 资源具有 Task 亲和性：仅保证同线程、同事件循环仍不足够。最终使用长期存活的 Owner Task 管理连接完整生命周期，并通过线程安全命令投递完成同步调用与异步资源管理的解耦。
