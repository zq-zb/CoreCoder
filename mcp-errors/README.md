# MCP 错误与排查记录

这个目录记录 MCP 开发过程中由真实运行和集成测试发现的问题，重点保留复现方式、根因、错误尝试、修复方案与验证结果。

- `01-anyio-task-affinity.md`：MCP 连接与关闭发生在不同 asyncio Task，导致 AnyIO CancelScope 拒绝退出。
