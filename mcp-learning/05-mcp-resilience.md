# 第五阶段：MCP Runtime 工程化容错与多 Server 隔离

## 1. 为什么正常调用链还不够

打通 `Agent → Adapter → Runtime → Client → Server` 只能证明系统在理想情况下可用。真实外部工具可能响应缓慢、永久卡死、返回业务错误或连续不可用；多个 Server 也可能提供同名工具。工程化目标是限制故障影响范围，并让失败可检测、可解释、可恢复。

## 2. 有界超时与两阶段关闭

工具调用超时后，主线程停止等待，但远端工具可能仍在执行。Runtime 因此进入 `DEGRADED`，记录故障原因并拒绝新命令，避免队列继续堆积。

关闭分为两个阶段：

```text
graceful_timeout 内：等待任务自然结束并优雅关闭
        ↓ 超时
取消 Owner Task
        ↓
Owner Task 在 finally 中执行 client.close()
        ↓
MCP SDK 关闭管道，必要时终止 Server 进程树
        ↓
force_timeout 内等待 _client_closed
```

如果强制清理仍未完成，Runtime 不会永久等待或假装成功，而是进入 `FAILED` 并抛出 `MCPRuntimeCloseError`。上层应丢弃该实例并交由外部进程管理器检查残留资源。

## 3. 显式状态机

```text
DISCONNECTED → CONNECTING → HEALTHY
                           ↓ 工具超时
                        DEGRADED
                           ↓ close
                         CLOSING
                     ↙             ↘
             DISCONNECTED          FAILED
```

状态机让调用拒绝、日志、健康检查和恢复逻辑拥有同一语义，避免依赖多个 `None` 和布尔变量猜测状态。

## 4. 错误分类

- `MCPToolTimeoutError`：调用方在期限内没有收到结果，Runtime 降级。
- `MCPToolExecutionError`：Server 已响应但工具明确失败，只影响本次调用。
- `MCPRuntimeUnhealthyError`：连接已降级，新命令在入队前被拒绝。
- `MCPRuntimeCloseError`：强制清理或后台线程未在期限内退出。
- `MCPCircuitOpenError`：连续瞬时失败达到阈值，熔断窗口内快速失败。
- `MCPServerBusyError`：单 Server 并发舱壁已满，请求不进入队列。

重要取舍：业务失败不应污染连接；超时也不等于远端任务已经失败或取消。

## 5. 结构化可观测性

Runtime 保存最近 100 条 `MCPCallRecord`，包含工具名、连接代次、耗时、结果类型和错误摘要。结果类型为 `success / timeout / execution_error / transport_error`。

使用有界 `deque` 是为了支持长期运行而不让历史记录无限占用内存；连接代次用于判断故障是否跨越重连边界。

## 6. 安全重试

自动重试必须同时满足：

```text
错误 structuredContent.retryable == true
并且
工具 readOnlyHint == true 或 idempotentHint == true
并且
destructiveHint != true
```

未知工具、破坏性工具、普通业务错误和超时默认不重试。超时只说明调用方没收到结果，不代表第一次操作没有成功；盲目重试转账、写文件或发送消息可能产生重复副作用。

## 7. 熔断器

每个 Server 拥有独立熔断器：

```text
CLOSED：正常调用并累计瞬时错误
OPEN：达到阈值，恢复窗口内快速失败
HALF_OPEN：窗口结束后只允许一次探测
探测成功 → CLOSED
探测失败 → OPEN
```

熔断状态使用独立锁，保证 Agent 并行调用时只有一个 HALF_OPEN 探测请求穿透。

## 8. 多 Server 与舱壁隔离

`MCPManager` 为每个 Server 创建独立 Runtime，因此各自拥有独立线程、事件循环、Owner Task、连接状态和熔断器。工具公开名称使用 `server_name__tool_name`，既解决同名冲突，也让日志和路由定位具体故障域。

每个 Server 还有独立并发信号量。容量耗尽时抛出 `MCPServerBusyError`，请求不会无限堆入单线程 Owner Task 队列。一个 Server 超时或拥塞时，其他 Server 仍可继续服务。

`restart_server(name)` 只关闭并重建指定故障 Runtime，不替换其他健康 Runtime；重启后会重置该 Server 的熔断器与并发舱壁。

## 9. 测试证据

- 10 秒工具在优雅期限后被取消，不等待完整 10 秒；
- 强制清理仍失败时有限返回并进入 `FAILED`；
- 业务工具失败后同一连接仍可执行其他工具；
- 安全瞬时错误重试成功，未知或不安全工具不重试；
- 连续错误开启熔断，HALF_OPEN 探测成功后恢复；
- 单 Server 并发超限快速失败；
- 一个 Server 超时不影响另一个 Server；
- 单独重启降级 Server 后恢复调用，其他健康 Runtime 对象保持不变；
- 全项目 125 项测试通过。

## 10. 面试表达

> 我将 MCP 外部工具视为不可靠依赖，为 Runtime 设计了显式连接状态机和两阶段有界关闭：调用超时后先隔离新请求，优雅期结束后取消 Owner Task，并依赖 SDK 的取消保护清理 stdio Server；清理仍超时则进入 FAILED 而不是假装成功。多 Server 层采用独立 Runtime、命名空间、熔断器和并发舱壁限制故障域。重试策略同时依赖 Server 的 retryable 元数据和 MCP 标准幂等/只读注解，避免非幂等工具产生重复副作用。

### 常见追问

**为什么超时后不直接重试？**

超时只说明调用方没收到结果，不代表远端没有成功。没有幂等保证时重试可能重复执行副作用。

**为什么取消 Owner Task，而不是主线程直接关闭 Client？**

AnyIO 资源具有 Task affinity。Client 的创建、调用和退出应保持在 Owner Task；取消后由其 `finally` 执行关闭，避免跨 Task 退出 cancel scope。

**熔断和超时有什么区别？**

超时约束单次调用时长；熔断根据连续瞬时失败，暂时阻止新流量继续冲击不健康依赖。

**为什么还需要舱壁？**

熔断处理失败率，舱壁限制并发资源占用。即使请求尚未失败，大量慢请求也可能耗尽线程或堆满队列，因此两者解决不同问题。
