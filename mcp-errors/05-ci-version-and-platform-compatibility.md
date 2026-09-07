# 05 · CI 版本与平台兼容性故障

## 1. Python 3.10 在测试收集阶段全部失败

### 现象

GitHub Actions 的 Python 3.10 任务没有进入任何测试，共有 27 个测试模块在导入时失败：

```text
ImportError: cannot import name 'UTC' from 'datetime'
```

### 根因

项目在 `pyproject.toml` 中声明支持 Python 3.10，但 `datetime.UTC` 是 Python 3.11 才加入的名称。开发机使用较新 Python，因此本地 222 个测试全部通过，无法暴露该问题。

### 解决

把 `datetime.UTC` 统一替换为 Python 3.10 已支持且语义相同的 `datetime.timezone.utc`。没有通过删除 Python 3.10 测试来回避兼容承诺。

### 验证

- CI 保留 Python 3.10、3.11、3.12、3.13 矩阵；
- 本地完整回归通过；
- 由 GitHub Actions 再验证真正的 Python 3.10 环境。

## 2. 测试命令写死 Windows 的 `cd /d`

### 风险

Coding Agent 的离线演示和部分测试生成了如下命令：

```text
cd /d "工作目录" && python -m pytest ...
```

`/d` 是 Windows `cmd.exe` 的参数，在 Linux/macOS Shell 中不能使用。即使先修复 Python 导入，跨平台任务仍会在执行测试工具时失败。

### 解决

新增统一的 `command_in_directory()`：

- Windows 使用 `cd /d` 和 `subprocess.list2cmdline()`；
- Linux/macOS 使用 `cd` 和 `shlex.join()`；
- 路径和参数统一转义，支持包含空格的工作目录；
- 测试、评测和 CI 事故演示共享同一实现，避免多处拼接逐渐不一致。

### 测试中的一个小坑

在 Windows 上构造 `Path("/tmp/workspace")` 会被当前操作系统改写成反斜杠形式。测试 POSIX 命令时应传原始字符串，否则测试验证的是 Windows 改写后的路径，而不是目标平台命令。

## 面试表达

可以概括为：项目本地测试通过后，我通过 GitHub Actions 的多版本、多操作系统矩阵发现了开发环境无法覆盖的兼容性问题；随后修复 Python 最低版本 API，并抽象跨平台 Shell 命令生成器，通过参数转义和专项测试降低命令注入及路径空格风险。

## 3. 评测工作目录泄漏到后续任务

### 现象

单独运行测试可以通过，但完整 CI 中评测结束后，普通 Bash 测试报错：

```text
No such file or directory: /tmp/corecoder-eval-.../workspace
```

### 根因

`get_tool()` 返回注册表中的同一个工具对象。评测命令进入临时工作区后，Bash 工具记住了该目录；评测清理目录后，后续用例仍从已经删除的目录启动。这是典型的任务间可变状态泄漏，也会影响真实多任务 Agent。

### 解决

`get_tool()` 改为按类型创建新实例，默认 Agent 也为每个会话创建独立工具集合。注册表只承担“有哪些工具”的定义，不再作为所有任务共享的运行实例。

## 4. 测试执行器与 SDK 错误文本不稳定

- pytest 风格的顶层测试函数统一交给 pytest 执行，不再让 unittest 将其识别为“零测试”；
- MCP 工具失败测试只断言稳定契约（错误类型和工具名），不绑定 SDK 是否透传 Server 内部异常文本；
- 这样测试验证的是 CoreCoder 自己承诺的行为，而不是第三方库当前版本的展示细节。
