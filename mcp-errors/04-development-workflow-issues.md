# 04 · 日志、格式与文档工作流问题

## 1. 中文输出在工具捕获中显示乱码

### 现象

演示程序实际运行成功，但工具捕获的 PowerShell 输出显示为乱码。

### 原因

Windows 控制台、子进程输出和捕获工具之间的编码设置不一致。它不代表 MCP JSON-RPC 内容损坏，因为断言结果和工具返回值均正确。

### 处理

测试依赖结构化断言，不依赖终端中文字形；用户本机 PowerShell 通常可正常显示。生产日志应统一 UTF-8，并显式配置日志采集器编码。

## 2. 为什么不能在 MCP Server stdout 随便 print

stdio MCP 使用 stdout 传输 JSON-RPC。业务调试内容写到 stdout 可能污染协议数据，导致 Client 无法解析。

解决方式：Client/Runtime 使用标准 logging；Server 调试应写 stderr 或使用 MCP logging 能力。

## 3. Ruff 导入顺序失败

### 现象

新增 `logging`、`threading` 等导入后：

```text
I001 Import block is un-sorted
RUF022 __all__ is not sorted
```

### 原因

代码功能正确，但不符合项目统一格式规则。

### 解决

```powershell
.\.venv\Scripts\python.exe -m ruff check <file> --fix
.\.venv\Scripts\python.exe -m ruff check corecoder tests examples
```

每次自动修复后重新检查，避免把格式失败带入 CI。

## 4. 文档路径判断错误导致 apply_patch 整体失败

### 现象

计划更新 `corecoder/MCP_RUNTIME_CALL_CHAIN.md`，但真实文件位于仓库根目录，补丁校验失败。

### 原因

依赖之前的路径记忆，没有先使用文件搜索确认当前状态。

### 解决

```powershell
rg --files | rg "MCP_RUNTIME_CALL_CHAIN"
```

确认真实路径后重新应用补丁。失败补丁没有产生半成品。

### 经验

任何批量修改前先以工作区当前文件为准，不依赖对话记忆；补丁失败后先检查是否原子回滚，再拆分为较小补丁。
