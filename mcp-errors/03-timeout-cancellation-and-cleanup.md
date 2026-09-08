# 03 · 超时、取消与强制清理问题

## 1. 把“停止等待”误认为“工具已停止”

### 现象

`reply.result(timeout=0.05)` 抛出超时异常，但 Server 中的 `slow_echo` 仍继续执行并最终返回。

### 原因

Future 的 timeout 只约束调用方等待时间，没有向 Owner Task 或 MCP Server 发送取消请求。

### 修复思路

分离两个概念：

```text
call timeout：主线程停止等待并隔离连接
shutdown timeout：关闭阶段取消 Owner Task 并清理 Server
```

## 2. close() 仍可能等待慢工具自然结束

### 现象

调用已经超时，但 `runtime.close()` 的关闭命令排在慢工具后面，仍需等待工具完成。

### 原因

Owner Task 串行处理队列：

```text
当前：slow_echo
队列：[None 关闭命令]
```

### 修复

实现两阶段关闭：优雅期限内等待；超时后调用 `owner_future.cancel()`，由 Owner Task 的 `finally` 关闭 Client。

## 3. CancelledError 被 BaseException 吞掉

### 现象

设计强制取消后，Owner Task 可能把取消当作工具异常写入 reply，然后继续循环，无法进入清理逻辑。

### 原因

```python
except BaseException as error:
    reply.set_exception(error)
```

会捕获 `asyncio.CancelledError`。

### 修复

```python
except asyncio.CancelledError:
    raise
except BaseException as error:
    reply.set_exception(error)
```

### 验证

10 秒工具在 0.05 秒优雅期限后被取消，SDK 约 2 秒完成进程树清理，Runtime 不等待完整 10 秒。

## 4. 取消 Future 不足以证明资源已清理

### 问题

`owner_future.cancel()` 表示取消请求已发出，不代表 Owner Task 的 `finally` 和 SDK shutdown 已经完成。

### 修复

增加：

```python
self._client_closed = threading.Event()
```

只有 `await client.close()` 结束后才 set。主线程以该信号确认清理完成。

## 5. 强制清理本身也可能超时

### 处理

`_client_closed.wait(force_timeout)` 仍返回 False 时：

```text
记录 MCPRuntimeCloseError
→ 尝试停止事件循环和线程
→ Runtime 状态进入 FAILED
→ 上层不得复用该实例
```

### 设计取舍

应用层无法保证操作系统中的任何进程都一定可以终止。工业系统应保证有限等待、明确报告失败，并把最终残留检查交给进程监督器，而不是永久阻塞或假装成功。
