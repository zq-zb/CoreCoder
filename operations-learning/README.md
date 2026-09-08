# CoreCoder 部署前检查与运维说明

## 1. 为什么需要 Doctor

Agent 故障不一定来自模型。Python 版本、缺少依赖、GitHub CLI 不存在、工作区不可写、模型配置错误或审批文件损坏，都可能导致任务失败。

如果这些问题全部表现为“Agent 执行失败”，排障会非常困难。因此 CoreCoder 提供独立的本地健康检查，把环境故障与推理故障分开。

## 2. 使用方式

源码环境：

```powershell
.\.venv\Scripts\python.exe -m corecoder.doctor --workspace .
```

安装项目后：

```powershell
corecoder-doctor --workspace .
```

机器可读 JSON：

```powershell
corecoder-doctor --workspace . --json
```

JSON 输出可以接入部署脚本、流水线或监控系统。只要存在 `FAIL`，进程退出码就是 1；`WARN` 表示可选能力缺失，不影响总体健康。

## 3. 当前检查项

- Python 是否满足 3.10 及以上。
- `openai` 和 `mcp` 依赖是否可导入。
- Git 是否可用。
- GitHub CLI 是否可用；缺失只警告，因为它不是所有任务必需。
- Docker CLI 与 Docker Engine 分开检查；Engine 不可访问时沙箱能力警告，但本地模式仍可运行。
- 工作区是否存在并可写。
- 模型、Provider 和 API Key 是否完成配置。
- 本地审批快照是否能够严格解析。

检查模型配置时只输出“API Key 已配置”，不会输出内容。Doctor 不请求模型接口，也不访问外部网络。

## 4. Fail Closed

审批文件属于安全控制状态。如果文件损坏、字段缺失、状态非法、命令哈希格式错误或审批 ID 重复，系统不会尝试猜测和修复为“已批准”，而是拒绝加载并报告失败。

这叫 fail closed：控制系统发生异常时默认不放行。相反，发生异常后默认允许叫 fail open，会带来权限绕过风险。

## 5. 本机验证结果

2026-09-07 本地检查结果：

- Python 3.11.5：通过。
- OpenAI SDK：通过。
- MCP SDK：通过。
- Git 2.52.0：通过。
- GitHub CLI 2.97.0：通过。
- 工作区读写：通过。
- DeepSeek 兼容配置：通过，未显示密钥。
- 默认审批存储：通过。

版本信息会随机器环境变化，简历或答辩前应重新运行，不要长期依赖这份静态记录。

## 6. 央国企面试表达

我为 Coding Agent 增加了无网络依赖的启动前健康检查，将运行环境、模型配置、安全状态与 Agent 推理错误分离。检查结果同时支持人类可读和 JSON 格式，并通过退出码接入自动化流程；审批存储采用 fail-closed 校验，损坏状态不会被误认为已授权。

## 7. 生产环境仍需补充

- 模型服务连通性检查应作为可选的主动探测，并设置超时与脱敏。
- 审批和审计数据应写入受控数据库或日志平台。
- 增加磁盘空间、CPU、内存和任务队列积压指标。
- 为运行服务提供 `/health/live` 与 `/health/ready` 探针。
- 制定日志保存周期、轮转、访问权限和告警阈值。
