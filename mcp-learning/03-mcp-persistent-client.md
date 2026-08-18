# 03 · MCP 持久连接：问题、方案与测试

## 1. 为什么需要持久连接

早期的 `call_stdio_tool()` 每调用一次工具，都会启动 Server、建立连接，调用结束后再关闭。演示场景可以这样做，但连续调用时会产生重复的进程启动和协议握手开销。

解决方案是新增 `PersistentMCPClient`：

```python
async with PersistentMCPClient(command, args) as client:
    await client.call_tool("add", {"a": 2, "b": 3})
    await client.call_tool("greet", {"name": "小明"})
```

进入 `async with` 时连接一次，代码块中的工具发现和多次调用都复用同一个 Client，退出时再统一关闭。

## 2. 如何管理异步资源

持久连接需要延长 MCP Client、stdio 通道和 Server 子进程的生命周期。项目使用 `AsyncExitStack` 保存这些异步资源的退出逻辑：

```text
connect() → 登记清理逻辑
多次调用 → 复用连接
close()   → 统一释放 Client、stdio 和 Server 子进程
```

如果启动或协议握手失败，`connect()` 也会立即关闭已经打开的部分资源，避免泄漏。

## 3. 处理了哪些边界问题

### 未连接就调用

问题：调用者可能忘记执行 `connect()`，直接调用 `list_tools()` 或 `call_tool()`。

解决：在 API 边界检查 `_client`，未连接时抛出带有操作提示的 `RuntimeError`，避免出现模糊的空对象错误。

### 重复关闭

问题：业务代码和外层清理逻辑可能重复调用 `close()`。

解决：第一次关闭后清空连接状态；后续关闭发现没有资源时直接返回，使关闭操作具有幂等性。

### 业务代码中途异常

问题：`async with` 内的业务代码可能抛出异常，如果没有统一清理，Server 子进程可能残留。

解决：`__aexit__()` 始终调用 `close()`，确保正常结束和异常退出都释放资源。

## 4. 测试如何证明

当前集成测试使用真实 stdio Server，而不是 mock：

- 进入和退出 `async with`：验证连接建立后会被清空。
- 未连接调用：验证得到明确的 `RuntimeError`。
- 连续调用 `add` 和 `greet`：验证结果正确且底层 Client 对象未改变。
- 连续调用两次 `close()`：验证重复关闭不会报错。
- 在代码块中故意抛出异常：验证异常传播后连接仍被释放。

这些测试证明的是当前 Client 的连接复用和基础生命周期安全。超时、并发控制、Server 意外退出和自动重连仍属于后续增强范围。

## 5. 面试中的简短讲法

> 针对每次 MCP 工具调用都重复启动 stdio Server 的性能问题，我实现了支持异步上下文管理的持久化 Client，在一个 Session 内复用工具发现和多次调用，并使用 AsyncExitStack 统一管理 Client、传输通道与子进程。针对未连接调用、重复关闭和业务异常退出补充了真实子进程集成测试，确保错误提示清晰且资源能够可靠释放。
