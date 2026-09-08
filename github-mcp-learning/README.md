# GitHub MCP 只读 MVP

## 1. 为什么选 GitHub

CoreCoder 保留本地工具完成高频编码操作，GitHub MCP 只负责外部协作信息：

```text
本地工具
├── read_file / grep / glob
├── edit_file / write_file
└── bash 运行测试

GitHub MCP
├── 读取 Issue 需求
├── 读取 PR 摘要与 Diff
├── 列出失败 Workflow
└── 读取失败 Job、Step 和日志
```

这样不用把已经稳定的本地文件工具重写成 MCP，同时可以展示 Agent 动态接入外部平台的能力。

## 2. MVP 工具

MCP Server 内部真实名称：

- `read_issue(repository, issue_number)`
- `read_pull_request(repository, pull_number)`
- `get_pull_request_diff(repository, pull_number)`
- `list_failed_workflow_runs(repository, limit=5)`
- `get_workflow_run_failure(repository, run_id)`

Manager 交给 Agent 的公开名称：

- `github__read_issue`
- `github__read_pull_request`
- `github__get_pull_request_diff`
- `github__list_failed_workflow_runs`
- `github__get_workflow_run_failure`

## 3. 调用路径

```text
Agent 选择 github__read_issue
        ↓
MCPToolAdapter 转换为真实名 read_issue
        ↓
MCPManager 路由到 github Server 的独立 Runtime
        ↓
MCP Client 通过 stdio 调用 github_mcp_server.py
        ↓
GitHubService 使用参数列表调用 gh CLI
        ↓
GitHub API 返回 JSON
        ↓
Server 返回文本 + structured_content
        ↓
Agent 继续用本地工具搜索、修改和测试
```

## 4. Issue 输出

Server 不把 GitHub API 的整个庞大响应交给 Agent，只保留：

```json
{
  "repository": "owner/repo",
  "number": 12,
  "title": "Fix timeout",
  "state": "open",
  "body": "...",
  "labels": ["bug"],
  "assignees": ["alice"],
  "author": "bob",
  "url": "..."
}
```

这会减少进入 LLM 上下文的无关字段。

## 5. Actions 诊断输出

第一步列出最近失败的 Run，让 Agent 获得 `run_id`。第二步按 `run_id` 读取：

- 失败 Job；
- 失败或超时 Step；
- Job 链接；
- `gh run view --log-failed` 返回的失败日志。

日志最多保留 12000 字符，避免一次将过大日志放入 Agent 上下文。

## 6. 安全与重试

三个工具全部声明：

```text
readOnlyHint = true
idempotentHint = true
destructiveHint = false
openWorldHint = true
```

- 不提供评论、创建 PR、push 等写操作。
- 仓库名必须符合 `owner/name`，并且 `subprocess` 不使用 `shell=True`。
- 只有超时、502/503/504 等瞬时错误才返回 `retryable=true`。
- 认证失败和参数错误不会盲目重试。

## 7. 运行方式

只验证 MCP 工具发现：

```powershell
.\.venv\Scripts\python.exe examples\github_mcp_demo.py
```

读取真实 Issue：

```powershell
.\.venv\Scripts\python.exe examples\github_mcp_demo.py --repo zq-zb/CoreCoder --issue 1
```

真实请求前需要 GitHub CLI 已登录：

```powershell
gh auth login
gh auth status
```

## 8. GitHub 登录问题与解决

2026-08-21 首次检查时，GitHub CLI 已安装，但 `zq-zb` 账号保存的 token 已失效，设备登录还曾遇到 GitHub 443 端口连接超时。

这不影响：

- 服务层单元测试；
- 真实 MCP 握手；
- 工具 Schema、安全注解和命名空间验证。

切换到可访问 GitHub 的网络后重新执行 `gh auth login`，登录已恢复。随后已通过真实 MCP 链路读取：

- `zq-zb/CoreCoder` PR #4 摘要；
- PR #4 unified diff，并验证大输出截断；
- Actions Run `32143593565`，确认所有 Job 成功。

## 9. 测试

- Issue 字段裁剪和结构化输出。
- 失败 Workflow 列表参数。
- Job、失败 Step 与日志合并。
- 仓库参数注入防护。
- 超时与认证失败的重试分类。
- 真实 MCP Server 握手、工具发现与 `github__` 命名空间。

## 10. 真实调用发现的超时问题

读取 PR #4 通过真实 MCP 链路成功，但首次 Actions 诊断超过 Runtime 统一的 5 秒期限，被分类为 `MCPToolTimeoutError`。

原因是 Actions 诊断最多包含两次 GitHub 请求：Job API 和失败日志。它与普通 Issue 读取共用 5 秒期限不合理。

解决方式：

- `MCPServerConfig` 增加 `call_timeout`，允许按 Server 的外部依赖特性配置期限。
- GitHub Server 演示配置为 30 秒，其他轻量 Server 仍保留 5 秒默认值。
- 成功 Run 直接返回空失败列表，不再请求不存在的失败日志。
