# MCP Agent 简历与面试指南

## 一句话项目定位

在 CoreCoder 中实现支持真实 DeepSeek 工具选择的 MCP Agent 运行层，并针对外部工具的不可靠性补齐长连接生命周期、有界取消、安全重试、熔断、多 Server 故障隔离和结构化可观测性。

## 简历描述（精简版）

- 设计 `MCPToolAdapter + MCPRuntime + PersistentMCPClient` 分层架构，将 MCP 动态工具发现与同步 Agent Tool 接口衔接，并通过后台事件循环、Owner Task 和命令队列管理异步长连接生命周期。
- 针对慢工具和 Server 崩溃实现显式状态机与两阶段有界关闭；调用超时后隔离新请求，优雅期结束后取消 Owner Task，并在 SDK 清理期限内终止异常 stdio Server。
- 基于 MCP `ToolAnnotations` 和结构化 `retryable` 元数据实现保守重试，结合每 Server 熔断器、HALF_OPEN 单探测和并发舱壁，避免非幂等副作用与故障扩散。
- 实现多 MCP Server 独立 Runtime 和 `server__tool` 命名空间；一个 Server 降级时其他 Server 保持可用，并支持只重启故障 Server。
- 使用真实 stdio Server、DeepSeek 工具调用和跨平台 CI 验证正常与失败链路；本地全量 125 项测试通过。

## 三分钟项目介绍

### 1. 背景

CoreCoder 原有 Agent 只认识项目内部 Tool，而 MCP Server 的工具 Schema、异步调用方式和连接生命周期与 Agent 不一致。我需要把真实 MCP 工具动态接入 Agent，同时保证外部 Server 不稳定时不会拖垮整个进程。

### 2. 核心架构

```text
Agent
  ↓ Tool Schema / execute
MCPToolAdapter
  ↓ 同步调用
MCPRuntime
  ↓ 命令队列
Owner Task（固定后台事件循环）
  ↓ 异步调用
PersistentMCPClient
  ↓ MCP SDK / stdio
MCP Server
```

Adapter 负责 Schema 与调用接口转换；Runtime 负责同步/异步桥接；Owner Task 保证 AnyIO 资源在同一 Task 创建、使用和关闭；Client 层隔离 SDK 类型并统一错误结果。

### 3. 最难的问题

最初连接和关闭分属不同 asyncio Task，触发 AnyIO cancel scope 的 Task affinity 错误。我改成长期 Owner Task，通过命令队列串行接收工具发现、调用和关闭命令，确保完整生命周期处于同一 Task。

另一个难点是超时不等于远端任务失败。我没有直接重试，而是把 Runtime 降级并拒绝新请求；关闭时先给优雅期限，超时后取消 Owner Task，由其 `finally` 调用 SDK 清理 Server。强制清理仍超时则进入 FAILED，不伪装成功。

### 4. 工程化扩展

多 Server 各自使用独立 Runtime 和熔断器；命名空间解决同名工具；并发舱壁限制单 Server 在途请求。自动重试同时要求错误明确可重试、工具明确只读或幂等且非破坏性。

### 5. 验证结果

真实 DeepSeek 能在 `add / greet / 不调用工具` 之间自主选择；10 秒慢工具可以在有界时间内被清理；Server 进程崩溃会分类为 transport error；一个 Server 超时不影响另一个 Server。全量 125 项测试通过。

## 高频追问与回答要点

### 为什么需要 PersistentMCPClient，SDK 自己不能长连接吗？

SDK 本身支持长连接。封装的目的不是重新实现能力，而是集中管理生命周期、连接状态、SDK 类型转换和统一错误边界，为 Runtime 提供稳定内部接口。

### 为什么需要 Runtime？

Agent 的 Tool API 是同步的，MCP SDK 是异步的。Runtime 使用后台线程和固定事件循环承载异步 Client，主线程通过线程安全队列与 Future 同步等待结果。

### 为什么只用一个 Owner Task？

AnyIO 的 cancel scope 具有 Task affinity。Client 在一个 Task 中进入，却在另一个 Task 退出会报错。Owner Task 持有连接完整生命周期并通过队列接收命令。

### 超时后为什么把 Runtime 降级？

调用方超时后无法确定远端是否仍在执行、是否已经产生副作用。继续向同一串行 Owner Task 入队会造成积压，因此先隔离新流量，再清理或重连。

### 为什么不能自动重试所有超时？

第一次请求可能已经成功。转账、写文件或发消息等非幂等操作重试会重复产生副作用。项目只对 Server 明确 `retryable=true` 且工具明确只读/幂等、非破坏性的执行错误重试。

### 业务错误为什么不让 Runtime 降级？

`is_error=True` 表示协议连接正常、Server 已响应，只是本次业务操作失败。测试验证失败后同一连接仍能执行其他工具。把业务错误等同于连接故障会造成不必要的可用性下降。

### 两阶段关闭解决什么？

优雅关闭给正常任务收尾机会；强制阶段保证永久卡死的工具不会让进程无限等待。强制清理也有期限，超期后明确进入 FAILED 并交给外部监督者处理。

### 熔断和舱壁有什么区别？

熔断根据连续瞬时失败阻断流量；舱壁限制单个依赖占用的并发资源。一个解决失败风暴，一个解决慢请求导致的资源耗尽。

### 多 Server 如何隔离？

每个 Server 拥有独立 Runtime、线程、事件循环、Owner Task、状态和熔断器。slow Server 的队列或连接不会占用 math Server 的运行资源。

### 当前方案还有哪些边界？

- stdio Server 以进程为故障域，HTTP 传输还需独立连接池与鉴权设计；
- 调用历史目前保存在进程内，生产环境应接 OpenTelemetry/Prometheus；
- 熔断状态未持久化，多实例部署需要外部协调或接受实例级熔断；
- Server 工具注解来自提供方，仍需本地策略白名单防止错误声明；
- 自动恢复目前偏保守，超时连接要求清理后显式重建。

主动说明这些限制，比声称“完全工业级”更可信。
