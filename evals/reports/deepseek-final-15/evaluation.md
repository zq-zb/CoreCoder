# CoreCoder Evaluation Report

- Model: deepseek-v4-flash
- Provider: openai
- Strategy: baseline
- Dataset: `ceccdefe45540244`
- Git commit: `30ceae089696bd7f119b24c12771bc463cae60be`

- Cases: 10/15
- Success rate: 66.7%
- Hidden test pass rate: 80.0%
- Scope compliance rate: 100.0%
- Average tool calls: 9.73
- Average failed test runs: 0.00
- Average duration: 17.70s
- Context compressions: 0
- Estimated context tokens saved: 0

| Case | Success | Hidden tests | Scope | Tool calls | Failures | Task reason |
|---|---:|---:|---:|---:|---|---|
| calculator-sign | yes | pass | pass | 6 | - | - |
| slugify-whitespace | yes | pass | pass | 7 | - | - |
| discount-call-chain | yes | pass | pass | 8 | - | - |
| timeout-validation | yes | pass | pass | 5 | - | - |
| truncate-contract | no | pass | pass | 15 | tool_budget_exceeded | - |
| retry-policy-boundary | yes | pass | pass | 10 | - | - |
| pagination-empty-page | yes | pass | pass | 9 | - | - |
| path-permission-boundary | no | fail | pass | 13 | agent_failed, hidden_test_failed, tool_budget_exceeded | 达到 Agent 最大工具调用轮数 |
| log-secret-redaction | yes | pass | pass | 6 | - | - |
| config-precedence | yes | pass | pass | 11 | - | - |
| webhook-signature-validation | no | pass | pass | 13 | agent_failed, tool_budget_exceeded | 达到 Agent 最大工具调用轮数 |
| lease-expiry-boundary | yes | pass | pass | 7 | - | - |
| ci-log-failure-classification | yes | pass | pass | 6 | - | - |
| protected-branch-normalization | no | fail | pass | 14 | agent_failed, hidden_test_failed, tool_budget_exceeded | 达到 Agent 最大工具调用轮数 |
| batch-deduplication-order | no | fail | pass | 16 | agent_failed, hidden_test_failed, tool_budget_exceeded | 达到 Agent 最大工具调用轮数 |
