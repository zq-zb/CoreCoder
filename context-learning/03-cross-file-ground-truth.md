# 03 · 跨文件检索真值

## 为什么要区分两种文件

Coding Agent 定位问题时会接触两类文件：最终需要修改的目标文件，以及为了理解调用关系必须阅读但不应修改的上下文文件。

以分页案例为例：缺陷最终位于 `service.py`，但 `api_client.py` 描述了分页接口，`test_service.py` 给出公开行为。若只用 `allowed_changed_files` 评估检索，系统即使完全没找到接口和测试，也可能显示 100% 召回。

## 新增的数据契约

评测案例的 `case.json` 可以声明：

```json
{
  "allowed_changed_files": ["service.py"],
  "relevant_context_files": ["api_client.py", "service.py", "test_service.py"]
}
```

- `allowed_changed_files` 仍是安全边界，决定 Agent 最终可以修改什么；
- `relevant_context_files` 是检索评测真值，表示合理定位该任务应召回哪些文件；
- 加载数据集时会验证上下文文件真实存在，防止清单与仓库漂移。

## 两个召回率

- Target recall：修改目标召回率，回答“有没有找到应修改文件”；
- Context recall：相关上下文召回率，回答“有没有找到理解问题需要的调用方、依赖和测试”。

未提供真值或 Agent 没有调用检索时报告 `n/a`，避免把“没有测量”误写成“能力为零”。单案例结果和全套汇总都保留这两个指标。

## 当前纳入的跨文件任务

1. 折扣调用链：`checkout.py → pricing.py → test_checkout.py`；
2. 分页调用链：`service.py → api_client.py + test_service.py`。

后续不需要给所有简单单文件案例强行添加上下文真值。真值应由任务调用关系决定，否则会为了指标好看而制造无意义文件。

## 面试表达

我把 Coding Agent 的检索评测拆成“修改目标召回”和“上下文依赖召回”。评测集显式标注跨文件调用链中的实现、依赖和测试文件，并在加载时校验真值有效性，从而避免仅用最终修改文件评价检索质量造成指标虚高。

## 你先记住三句话

1. 要改的文件，不等于需要读的全部文件。
2. 安全范围由 allowed changed files 管，检索质量由 relevant context files 衡量。
3. 分开统计后，检索结果才不会虚高。
