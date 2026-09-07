# CoreCoder Evaluation Comparison

- Baseline: `structured-memory+retrieval-off`
- Candidate: `structured-memory+retrieval-guided`
- Comparable metadata: yes
- Results per group: 1
- Candidate repository searches: 1
- Candidate policy rejections: 1

| Metric | Candidate - baseline |
|---|---:|
| Success rate | +0.0% |
| Hidden test pass rate | +0.0% |
| Average tool calls | +1.00 |
| Average duration | -1.02s |
| Average prompt tokens | +2882 |
| Average completion tokens | -277 |

## Evidence warnings

- 每组少于 3 次结果，只能视为链路冒烟，不能证明稳定提升
- 模型费用不可用，应使用 Token 指标比较资源消耗
