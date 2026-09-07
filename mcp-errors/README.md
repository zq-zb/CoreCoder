# MCP 错误与排查记录

这个目录记录 MCP 开发过程中由真实运行和集成测试发现的问题，重点保留复现方式、根因、错误尝试、修复方案与验证结果。

- `01-anyio-task-affinity.md`：MCP 连接与关闭发生在不同 asyncio Task，导致 AnyIO CancelScope 拒绝退出。
- `02-environment-and-test-isolation.md`：Python 环境、PowerShell 激活、`.env` 测试污染与构建后端问题。
- `03-timeout-cancellation-and-cleanup.md`：超时不等于取消、取消异常被吞和两阶段强制清理。
- `04-development-workflow-issues.md`：终端编码、stdio 日志、Ruff 格式和文档路径错误。
