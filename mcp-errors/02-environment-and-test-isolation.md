# 02 · Python 环境、PowerShell 与测试隔离问题

## 1. 系统 Python 缺少 MCP SDK

### 现象

直接运行：

```powershell
python examples\mcp_adapter_demo.py
```

出现：

```text
ModuleNotFoundError: No module named 'mcp'
```

### 原因

终端中的 `python` 指向系统 Python，而 MCP SDK 安装在项目 `.venv` 中。程序在导入阶段停止，尚未进入 Adapter、Runtime 或 Server。

### 解决

直接使用虚拟环境解释器：

```powershell
.\.venv\Scripts\python.exe examples\mcp_adapter_demo.py
```

### 避免方式

排查依赖错误时先确认：

```powershell
python -c "import sys; print(sys.executable)"
.\.venv\Scripts\python.exe -c "import mcp; print('ok')"
```

## 2. PowerShell 禁止执行 Activate.ps1

### 现象

```text
PSSecurityException
系统上禁止运行脚本
```

### 原因

Windows PowerShell ExecutionPolicy 禁止执行虚拟环境激活脚本。这不是 Python 或项目错误。

### 解决

不修改系统安全策略，直接调用：

```powershell
.\.venv\Scripts\python.exe
```

激活虚拟环境只是让 `python` 自动指向该解释器，直接使用完整路径效果相同。

## 3. 本地 `.env` 污染默认值测试

### 现象

全量测试出现：

```text
assert 'deepseek-v4-flash' == 'gpt-5.5'
```

### 原因

测试先删除环境变量，再调用 `Config.from_env()`；但该方法会重新读取项目 `.env`，把真实 DeepSeek 配置载入。测试结果因此依赖开发者机器。

### 错误写法

```python
monkeypatch.delenv("CORECODER_MODEL")
c = Config.from_env()
```

### 修复

默认值测试直接调用纯解析接口并传入空环境：

```python
c = parse_config(env={})
```

### 经验

配置测试应区分：

```text
集成测试：验证 .env 是否能被读取
纯单元测试：传入显式 env，不依赖本机文件
```

## 4. 本地 wheel 构建缺少 hatchling

### 现象

```text
ModuleNotFoundError: No module named 'hatchling'
```

### 原因

项目在 `pyproject.toml` 中声明 `hatchling` 为构建后端，但当前 `.venv` 没有安装它；使用 `--no-build-isolation` 时 pip 不会创建并安装隔离构建环境。

### 处理

没有把它误判成代码或打包配置错误，也没有擅自联网安装。CI 使用标准隔离构建时会按 `build-system.requires` 安装构建后端。

### 后续手动验证

获得安装授权后可执行：

```powershell
.\.venv\Scripts\python.exe -m pip install hatchling
.\.venv\Scripts\python.exe -m pip wheel . --no-deps
```
