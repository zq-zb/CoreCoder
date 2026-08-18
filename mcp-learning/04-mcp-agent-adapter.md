# 04 · MCP 工具接入 Agent

## 1. 要解决的问题

CoreCoder Agent 只认识同步的 `Tool`：

```text
name + description + parameters + execute()
```

MCP 提供的是异步 Client 和 `input_schema`。因此需要同时解决：

- MCP 工具定义与 CoreCoder Tool 接口不同。
- Agent 的 `execute()` 是同步函数，MCP `call_tool()` 是异步函数。
- MCP/AnyIO 连接资源要求由同一个 asyncio Task 管理完整生命周期。

## 2. 三层设计

```text
MCPToolAdapter：翻译 Tool 接口
MCPRuntime：同步/异步桥接与任务调度
PersistentMCPClient：MCP 协议通信
```

`MCPToolAdapter` 把 `input_schema` 映射为 `parameters`，并把 Agent 的同步 `execute()` 转发给 Runtime。

`MCPRuntime` 在后台线程维护固定事件循环，通过命令队列把工具发现、工具调用和关闭请求交给 Owner Task。

`PersistentMCPClient` 负责连接 Server、发送 `list_tools`/`call_tool` 请求并转换响应。

## 3. 工具发现路径

```text
Runtime 连接 Server
→ Owner Task 调用 Client.list_tools()
→ Server 返回工具名称、描述和 JSON Schema
→ create_mcp_tool_adapters()
→ 生成 CoreCoder Tool 列表
→ Agent 把 Tool Schema 发送给 LLM
```

## 4. 工具调用路径

```text
LLM 选择 add(a=2, b=3)
→ Agent._exec_tool()
→ MCPToolAdapter.execute()
→ MCPRuntime.call_tool()
→ 命令进入后台队列
→ Owner Task 调用 PersistentMCPClient.call_tool()
→ Server 执行 add
→ 结果 5 沿原路径返回
→ Agent 把工具结果交回 LLM
```

## 5. 为什么需要 Owner Task

最初把 `connect()` 和 `close()` 分别提交到同一个事件循环，但两次提交属于不同 asyncio Task，AnyIO 因此拒绝关闭 CancelScope。

修复后由一个长期 Owner Task 完成连接、等待命令和关闭。详细复现与根因见 `mcp-errors/01-anyio-task-affinity.md`。

## 6. 测试策略

- Fake Runtime：验证 Adapter 是否原样转发工具名和参数。
- 真实 stdio Server：验证 Runtime 能发现并调用 `add`、`greet`。
- ScriptedLLM：不消耗 API，确定性模拟 LLM 选择 `add`。
- Agent 端到端测试：验证工具结果 `5` 被写入 `role=tool` 的对话消息，并生成最终回答。

## 7. 面试中的简短讲法

> 我通过 Adapter 将 MCP 工具 Schema 转换为 Agent 的 Tool 接口，并实现后台 MCP Runtime，在固定事件循环中使用 Owner Task 管理 Client 生命周期，通过线程安全命令队列桥接同步 Agent 与异步 MCP SDK。最终通过真实 stdio Server 和确定性测试 LLM 跑通了动态工具发现、模型选工具、跨进程调用和结果回填的端到端链路。
