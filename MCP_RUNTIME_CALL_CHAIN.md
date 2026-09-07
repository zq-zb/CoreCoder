# MCP Runtime 关键内容浓缩

## 1. 各层职责

- **MCP Server**：提供真正的业务工具，例如 `add`、`greet`。
- **MCP SDK Client**：实现 MCP 协议通信，负责连接、工具发现和工具调用。
- **PersistentMCPClient**：在 SDK 之上统一管理连接状态、生命周期和返回结果转换。
- **MCPRuntime**：为同步 Agent 维护后台线程、固定 asyncio 事件循环和 Owner Task。
- **MCPToolAdapter**：把 MCP 工具定义转换成 CoreCoder 的 Tool，并把 `execute()` 转交给 Runtime。
- **Agent**：把工具 Schema 提供给 LLM，执行 LLM 选择的工具，再把工具结果写回对话。

## 2. 一次工具调用的完整路径

```text
adapter.execute(a=2, b=3)
        ↓
runtime.call_tool("add", {"a": 2, "b": 3})
        ↓
主线程创建 _CallToolCommand，并放入后台 Queue
        ↓
Owner Task 从 Queue 取出命令
        ↓
PersistentMCPClient.call_tool()
        ↓
MCP SDK Client.call_tool()
        ↓
MCP Server 执行 add
        ↓
结果 5 通过 Future 沿原路径返回 Adapter
```

## 3. 为什么需要 Runtime

Agent 的 Tool 接口是同步的，而 MCP SDK 调用是异步的。Runtime 在后台线程维护固定的 asyncio 事件循环，主线程通过命令队列发送请求，再通过 `concurrent.futures.Future` 同步等待结果，从而连接同步 Agent 和异步 MCP。

## 4. 为什么需要 Owner Task

MCP SDK 底层使用 AnyIO。连接的创建、使用和关闭需要由同一个异步 Task 管理，否则可能出现 `Attempted to exit cancel scope in a different task`。因此 Owner Task 长期持有 Client，并统一执行工具发现、工具调用和关闭。

## 5. 长连接的准确理解

MCP SDK 本身支持在同一个会话中连续调用多个工具。`PersistentMCPClient` 不是重新实现长连接，而是 CoreCoder 的项目级封装，用于统一：

- `connect()` / `close()` 生命周期；
- 未连接状态检查；
- SDK 类型到 `DiscoveredTool`、`MCPToolCallResult` 的转换；
- 后续超时、错误分类、重试和日志的扩展位置。

在同一个 `async with` 中连续调用 `add` 和 `greet`，底层 Client 对象保持不变，最后只关闭一次。

## 6. `list_tools` 和 `call_tool`

- `list_tools()` 对应工具发现：询问 Server 提供哪些工具。
- `call_tool(name, arguments)` 对应通用工具调用：按名称和参数调用指定工具。

它们不是具体业务工具。真正的工具是 `add`、`greet` 等。因此工具数量增加不会要求 Runtime 为每个工具新增调用方法。

## 7. 当前已经验证

- 一个 SDK Client 会话可连续调用多个工具；
- `PersistentMCPClient` 可复用同一个底层 Client；
- Adapter 能把 Agent 风格调用转换为 Runtime 调用；
- Runtime 能把主线程请求交给后台 Owner Task；
- Owner Task 能通过真实 stdio MCP Server 执行工具并返回结果；
- MCP 相关自动化测试共 20 项通过。

## 8. 面试简述

> MCP SDK 本身支持会话复用。我在其上封装 PersistentMCPClient，集中管理连接状态、生命周期和结果转换；再通过 MCPRuntime 的后台事件循环、命令队列与 Owner Task，解决同步 Agent Tool 接口和异步 MCP 长连接之间的衔接问题。MCPToolAdapter 则负责动态 Schema 适配，让 Agent 可以用统一 Tool 接口调用 MCP Server。

## 9. 后续工程化能力

超时隔离、两阶段有界关闭、状态机、错误分类、安全重试、熔断、多 Server 和并发舱壁的完整说明见 `mcp-learning/05-mcp-resilience.md`。
