# 阶段 10：让真实 Agent 使用检索，并支持公平 A/B

## 1. 发现的关键缺口

仓库检索已经有排序、缓存、增量刷新和离线基准，但检查正式评测入口后发现：`eval_cli._coding_tools()` 没有注册 `RepositorySearchTool`。

这意味着离线检索能力本身可以测试，单元测试中的自定义 Agent 也能收集指标，但真实模型评测时 Agent 根本看不到该工具。若直接在简历中声称“检索提高了 Agent 成功率”，证据是不成立的。

## 2. 怎么解决

评测 CLI 新增 `--retrieval on/off`：

- `on`：向真实 Agent 提供 `repository_search`，系统提示词包含“未知路径时先检索”；
- `off`：不提供工具，同时移除对应提示规则，避免模型被要求调用不存在的工具。

模型、数据集、上下文策略和任务预算保持一致，实验元数据分别记录：

- `structured-memory+retrieval-on`
- `structured-memory+retrieval-off`

因此两组的核心自变量只有“是否提供仓库检索能力”。

## 3. 为什么默认开启，但仍保留关闭开关

产品运行时应该默认使用已经验证过的上下文能力；实验时则必须能关闭它建立基线。关闭开关不是功能倒退，而是因果评估所需的对照组。

## 4. 运行方式

以下命令会调用真实模型并产生费用，因此不会在自动测试中执行：

```powershell
.\.venv\Scripts\python.exe -m corecoder.eval_cli --case access-policy-call-chain --run --strategy structured-memory --retrieval off --output evals/reports/agent-retrieval-off

.\.venv\Scripts\python.exe -m corecoder.eval_cli --case access-policy-call-chain --run --strategy structured-memory --retrieval on --output evals/reports/agent-retrieval-on
```

严谨实验应对同一批多文件案例分别重复至少 3 次，再比较成功率、隐藏测试通过率、工具调用数、输入 Token、耗时、成本和上下文召回率。单案例单次运行只能验证链路，不能证明稳定提升。

## 5. 面试表达

我在检查端到端评测链路时发现，检索工具虽已完成离线评测，但没有进入真实模型的工具集合。因此增加了显式检索开关，并让系统提示随工具能力同步变化，保证对照组不会收到无效指令。实验元数据记录检索配置，从而可以在同模型、同数据集和同预算下比较检索对任务成功率、Token 和成本的实际影响。
