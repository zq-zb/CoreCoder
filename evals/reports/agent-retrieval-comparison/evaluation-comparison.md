# CoreCoder Evaluation Comparison

- Baseline: `structured-memory+retrieval-off`
- Candidate: `structured-memory+retrieval-on`
- Comparable metadata: yes
- Results per group: 1
- Candidate repository searches: 0

| Metric | Candidate - baseline |
|---|---:|
| Success rate | +0.0% |
| Hidden test pass rate | +0.0% |
| Average tool calls | +0.00 |
| Average duration | +4.74s |
| Average prompt tokens | +5061 |
| Average completion tokens | +535 |

## Evidence warnings

- 每组少于 3 次结果，只能视为链路冒烟，不能证明稳定提升
- 候选组没有实际调用 repository_search，不能归因于检索能力
- 模型费用不可用，应使用 Token 指标比较资源消耗
