# 第七阶段：MCP Agent 工程化深化详解

这份文档用于逐步学习本轮深化内容。建议按章节顺序阅读；每一章只回答四个问题：遇到了什么问题、为什么会发生、代码如何解决、方案还存在哪些边界。

## 0. 深化前后对比

深化前，系统只能证明正常路径可运行：

```text
Agent → Adapter → Runtime → Client → Server → 返回结果
```

深化后，系统开始回答真实工程问题：

```text
工具永久不返回怎么办？
Server 进程突然退出怎么办？
业务失败是否应该断开连接？
哪些错误允许重试？
连续失败如何避免请求风暴？
并发请求如何避免堆满队列？
一个 Server 故障如何不影响其他 Server？
如何只重启故障 Server？
如何保留调用耗时和失败类型？
```

## 1. 有界工具超时

### 问题

同步主线程通过 Future 等待后台 Owner Task 返回结果。如果 Server 一直不响应，主线程可能永久阻塞。

### 方案

`MCPRuntime.call_tool()` 接受单次调用期限：

```python
runtime.call_tool(
    "slow_echo",
    {"text": "hello", "delay": 10},
    timeout=0.05,
)
```

主线程通过：

```python
reply.result(timeout=timeout)
```

有限等待。超过期限时：

```text
记录 _unhealthy_reason
→ 状态 HEALTHY → DEGRADED
→ 记录 timeout 调用历史
→ 抛出 MCPToolTimeoutError
```

### 重要边界

主线程停止等待，不代表 Server 中的工具已经停止。超时是调用方观察到的事实，不是远端执行状态。

## 2. 超时后的故障隔离

### 问题

Owner Task 一次处理一个命令。慢工具仍在运行时继续入队，会让后续调用全部堆在它后面。

### 方案

超时后设置：

```python
self._unhealthy_reason = "工具 slow_echo 调用超时"
```

后续 `list_tools()` 和 `call_tool()` 在入队前执行：

```python
self._raise_if_unhealthy()
```

发现故障后立即抛出 `MCPRuntimeUnhealthyError`，新命令不会进入队列。

### 为什么不继续尝试

超时连接的远端状态不确定。继续使用可能造成命令积压或把多个业务操作发送到一个已失控的 Server。

## 3. 两阶段有界关闭

### 问题

旧实现的 `close()` 会等待当前工具自然结束。如果工具需要 10 秒、10 分钟或永远不返回，Runtime 无法在可预测时间内退出。

### 方案

```python
runtime.close(
    graceful_timeout=1.0,
    force_timeout=3.0,
)
```

第一阶段是优雅关闭：

```text
发送 None 关闭命令
→ 最多等待 graceful_timeout
→ 工具自然结束
→ Owner Task 关闭 Client
```

第二阶段是强制清理：

```text
优雅期限结束
→ owner_future.cancel()
→ Owner Task 收到 CancelledError
→ 进入 finally
→ PersistentMCPClient.close()
→ MCP SDK 关闭管道并终止 Server 进程树
```

### `_client_closed` 的作用

它不是清理动作，而是清理完成通知：

```python
finally:
    await client.close()
    self._client_closed.set()
```

主线程在强制阶段最多等待 `force_timeout`。如果信号仍未设置，抛出 `MCPRuntimeCloseError` 并进入 `FAILED`，不会永久等待或假装成功。

### 验证

真实工具设置运行 10 秒；调用 0.05 秒超时，关闭再优雅等待 0.05 秒。实际约 2 秒完成 SDK 进程树清理，没有等待完整 10 秒。

## 4. 为什么必须单独传播 CancelledError

### 问题

Owner Task 原来使用：

```python
except BaseException as error:
    command.reply.set_exception(error)
```

`asyncio.CancelledError` 也是 `BaseException`，强制取消会被误当作普通工具失败吞掉，Owner Task 继续循环，无法进入外层 `finally`。

### 修复

```python
except asyncio.CancelledError:
    raise
except BaseException as error:
    command.reply.set_exception(error)
```

取消必须向外传播，才能触发 Client 和 Server 清理。

## 5. Runtime 状态机

### 问题

仅依赖 `_client is None`、线程是否存在和 `_unhealthy_reason`，很难准确表达正在连接、降级、关闭失败等状态。

### 状态

```text
DISCONNECTED
CONNECTING
HEALTHY
DEGRADED
CLOSING
FAILED
```

### 主要转换

```text
DISCONNECTED → CONNECTING → HEALTHY
HEALTHY → DEGRADED：调用超时或传输故障
HEALTHY/DEGRADED → CLOSING：开始关闭
CLOSING → DISCONNECTED：清理成功
CLOSING → FAILED：强制清理或线程退出失败
```

状态用锁保护，并记录状态转换日志，供健康检查和排障使用。

## 6. 错误分类

### `MCPToolExecutionError`

Server 已正常响应，但返回 `is_error=True`。这通常是业务失败，例如库存不足。连接仍可信，因此 Runtime 保持 `HEALTHY`。

测试证明 `fail_operation` 失败后，同一连接的 `echo` 仍能成功。

### `MCPTransportError`

Server 未返回合法响应就退出，或连接本身异常。当前连接不再可信，因此 Runtime 进入 `DEGRADED`。

测试 Server 使用 `os._exit(7)` 模拟进程崩溃，调用被记录为 `transport_error`。

### 为什么必须区分

```text
业务失败：只影响当前操作
传输失败：影响连接可靠性
超时：远端结果不确定
关闭失败：资源状态不确定
```

如果全部统一为一个 `RuntimeError`，上层无法选择正确恢复策略。

## 7. 结构化调用历史

Runtime 使用最大长度为 100 的 `deque` 保存 `MCPCallRecord`：

```text
tool_name
connection_generation
duration_seconds
outcome
error
```

`outcome` 包括：

```text
success
timeout
execution_error
transport_error
```

### 为什么使用有界队列

Runtime 可能长期运行。无限保存记录会导致内存持续增长；最近 100 条适合本地排障，生产环境可以替换为 OpenTelemetry 或 Prometheus。

### connection_generation

每次重新连接都会增加连接代次。它能回答：错误是否集中发生在同一条连接，重连后是否恢复。

## 8. 安全重试

### 问题

“失败就重试三次”可能重复转账、重复写文件或重复发送消息。

### 保守条件

只有同时满足以下条件才自动重试：

```text
错误 structuredContent.retryable == true
工具 readOnlyHint == true 或 idempotentHint == true
工具 destructiveHint != true
```

Server 负责说明错误是否瞬时；工具注解说明重复执行是否安全。缺少任一信息都不重试。

### 当前取舍

当前仅重试明确的工具执行错误，不自动重试超时。因为超时时第一次操作可能已经成功。

## 9. 熔断器

### 问题

外部依赖持续失败时，每个用户请求都继续访问它，会增加延迟、日志噪音和依赖压力。

### 状态

```text
CLOSED：正常放行并累计瞬时失败
OPEN：达到阈值，恢复窗口内快速失败
HALF_OPEN：窗口结束后只放行一次探测
```

探测成功回到 CLOSED；失败重新 OPEN。熔断器使用每 Server 独立锁，保证并行 Agent 调用时只有一个 HALF_OPEN 探测穿透。

## 10. 并发舱壁

### 问题

熔断器只能处理失败率。大量尚未失败但非常慢的请求，仍可能堆满 Owner Task 队列。

### 方案

每个 Server 使用独立 `BoundedSemaphore` 限制在途调用。并发槽耗尽时抛出 `MCPServerBusyError`，新请求不会进入 Runtime 队列。

### 熔断与舱壁的区别

```text
熔断：限制对连续失败依赖的流量
舱壁：限制单个依赖占用的并发资源
```

## 11. 多 Server 故障隔离

`MCPManager` 为每个 Server 创建独立：

```text
MCPRuntime
后台线程
asyncio 事件循环
Owner Task
Client
状态机
熔断器
并发舱壁
```

工具公开名称使用：

```text
server_name__tool_name
```

解决工具重名并明确路由目标。测试中 slow Server 超时进入 DEGRADED，math Server 仍成功执行 `add(20, 22)` 返回 42。

## 12. 单 Server 定向恢复

`restart_server(name)` 只执行：

```text
关闭目标旧 Runtime
→ 创建目标新 Runtime
→ 使用原配置重新连接
→ 重置该 Server 熔断器与并发舱壁
```

其他健康 Runtime 对象保持不变，不需要整体重启 Agent。

## 13. 最终验证

```text
pytest：125 passed
Ruff：All checks passed
compileall：通过
git diff --check：通过
```

可运行演示：

```powershell
.\.venv\Scripts\python.exe examples\mcp_timeout_recovery_demo.py
.\.venv\Scripts\python.exe examples\mcp_manager_demo.py
.\.venv\Scripts\python.exe examples\mcp_deepseek_agent_demo.py
```

## 14. 建议学习顺序

1. 先理解超时不等于取消。
2. 再理解 DEGRADED 为什么拒绝新请求。
3. 再看优雅关闭与强制清理。
4. 理解 CancelledError 为什么不能吞。
5. 学习业务错误与连接错误的区别。
6. 最后学习重试、熔断、舱壁和多 Server。

每理解一章，可以用“针对什么问题、做了什么、为什么这样做、如何验证”四句话复述。
