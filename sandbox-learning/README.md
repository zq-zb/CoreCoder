# CoreCoder Docker 沙箱执行

## 1. 为什么命令策略还不够

正则策略能够拦截常见危险命令，但 shell 语法可以组合、转义和间接执行，无法仅靠字符串匹配覆盖。真正降低影响范围需要第二层隔离：即使命令绕过应用层检查，也只能在受限环境中运行。

## 2. 当前沙箱限制

Docker 执行器为每条命令创建一次性容器，并配置：

- 默认关闭网络：`--network none`。
- 根文件系统只读：`--read-only`。
- 只把当前工作区读写挂载到 `/workspace`。
- 删除全部 Linux capabilities：`--cap-drop ALL`。
- 禁止获取新权限：`no-new-privileges`。
- 默认内存 512 MB、CPU 1 核、PID 128。
- `/tmp` 使用 64 MB 临时文件系统，并禁止执行和 setuid。
- 容器内使用 UID 10001 的非 root 用户。
- 命令超时后，额外执行一次有限时长的强制容器清理。

## 3. 构建固定镜像

```powershell
docker build -f docker\Dockerfile.sandbox -t corecoder-sandbox:py311 .
```

镜像基于 Python 3.11，并固定安装 pytest 8.3.5。固定版本能减少环境漂移；后续可以通过内部镜像仓库管理审批过的基础镜像。

## 4. 使用方式

本地执行仍是默认模式：

```powershell
corecoder
```

显式启用 Docker 沙箱：

```powershell
corecoder --sandbox docker
```

文件读取与编辑工具仍由宿主侧工作区边界保护，Bash 命令进入容器执行。命令风险分级发生在容器启动之前，因此形成“应用层策略 + 容器隔离”两道防线。

## 5. 超时为什么还要清理容器

Python 杀掉 `docker run` 客户端进程，不一定能证明 Docker daemon 中的容器已经停止。执行器为容器分配唯一名称；发生超时时，再调用 `docker rm -f <name>`，并为清理设置 5 秒上限，防止清理过程无限阻塞。

## 6. 自动测试证明了什么

- Docker 参数确实包含网络、根文件系统、capability 和资源限制。
- 非法镜像名称在创建执行器时被拒绝。
- 命令输出、错误和退出码能够返回 Agent。
- 超时后会针对同一个唯一容器名执行清理。
- Bash 工具可以注入沙箱执行后端，而不破坏本地默认模式。

这些测试验证命令构造和状态处理，不等同于真实 Docker Engine 集成测试。

## 7. 本次真实环境问题

2026-09-07 检查发现 Docker CLI 29.2.1 已安装，但当前 Codex 进程无权读取 `C:\Users\HP\.docker\config.json`，也无权连接 `docker_engine` named pipe。因此本轮没有构建镜像或执行真实容器。

这应归类为“执行环境权限不足”，不是 Agent 推理失败或沙箱逻辑失败。获得正常 Docker Engine 权限后，还需要补一条真实集成测试。

## 8. 不能夸大的边界

- Docker 不是绝对安全边界，仍需要及时更新 Engine 和基础镜像。
- Windows bind mount 权限与 Linux 宿主不同，需要单独验证。
- 当前每条命令新建容器，隔离强但启动开销较高。
- 默认无网络会阻止在线安装依赖，这是有意的安全取舍。
- 生产环境建议使用专用沙箱节点、镜像白名单、只读缓存和更严格的运行时策略。

## 9. 简历表达

为降低 Coding Agent 执行任意 shell 命令的影响范围，我在应用层命令分级之外实现了可插拔 Docker 沙箱后端：默认禁网、只读根文件系统、非 root 运行，并限制 CPU、内存和进程数；针对命令超时设计唯一容器标识和二次强制清理，避免后台任务残留。沙箱通过 CLI 显式开启，本地模式保持兼容。
