# 阶段 13：Guided 检索策略一致性

## 1. 为什么没有直接压缩代码片段

上一轮真实 A/B 中，guided 比 off 多消耗 2,882 个输入 Token。进一步查看报告发现，仓库检索只返回 694 个字符，粗略不到 200 Token。因此检索正文并不是主要成本，直接把五行片段继续压短，很难解释大部分增量。

guided 的工具轨迹是 `bash → repository_search`，并记录了 1 次策略拒绝。模型先提出 Bash，Runtime 拒绝后再请求一次模型。由于每轮请求都会携带系统提示、工具 Schema 和已有历史，这次额外往返可能比检索正文昂贵得多。

## 2. 找到的实现缺陷

`Agent` 初始化时会根据 `repository_retrieval_policy="guided"` 生成强约束提示。但 `CodingTaskRunner` 为文件工具安装工作区安全守卫后，需要刷新工具 Schema，因此重新调用了 `system_prompt(guarded_tools)`。

这次调用没有继续传递 Agent 的检索策略，系统提示退回 available 模式：

- 提示层只建议“路径未知时可以检索”；
- 执行层仍要求“必须先检索”；
- 模型不知道硬约束，先读取或运行命令后才被拒绝。

这属于配置漂移：两个组件都各自正常，但组合后对同一策略形成不同理解。

## 3. 如何修复

安全守卫刷新系统提示时，显式传递：

```python
repository_retrieval_policy=self.agent.repository_retrieval_policy
```

这样工作区守卫只改变工具执行边界和 Schema 来源，不改变上层已经选择的检索策略。执行层的拒绝逻辑仍然保留，作为模型不遵守提示时的安全兜底，而不再充当模型获知规则的主要渠道。

## 4. 如何验证

新增回归测试，在 guided Agent 上安装 `CodingTaskRunner` 后检查最终系统提示仍包含：

- `Guided retrieval policy`
- `runtime enforces this ordering`

这个测试直接覆盖发生漂移的组件边界。下一步需要重新运行同案例真实评测，观察首次工具是否从 Bash 变为 repository_search，以及策略拒绝和输入 Token 是否下降。真实调用属于新的付费实验，应单独确认后执行。

## 5. 面试表达

> 真实 A/B 显示 guided 检索增加了 2,882 个输入 Token，但检索正文只有 694 字符。我没有直接压缩片段，而是沿工具轨迹做成本归因，发现工作区安全守卫重建系统提示时丢失了 guided 参数，导致提示层建议检索、执行层却强制检索，产生一次无效模型往返。修复后增加组件边界回归测试，使提示策略与运行时策略保持一致，并保留执行层校验作为兜底。
