# CoreCoder Evaluation Report

- Model: deepseek-v4-flash
- Provider: openai
- Strategy: baseline
- Dataset: `b9d33a775202755a`
- Git commit: `30ceae089696bd7f119b24c12771bc463cae60be`

- Cases: 3/6
- Success rate: 50.0%
- Hidden test pass rate: 50.0%
- Scope compliance rate: 100.0%
- Average tool calls: 11.00
- Average failed test runs: 0.00
- Average duration: 30.25s
- Context compressions: 0
- Estimated context tokens saved: 0

| Case | Success | Hidden tests | Scope | Tool calls | Failures | Task reason |
|---|---:|---:|---:|---:|---|---|
| log-secret-redaction | yes | pass | pass | 7 | - | - |
| protected-branch-normalization | yes | pass | pass | 8 | - | - |
| log-secret-redaction | no | fail | pass | 15 | agent_failed, hidden_test_failed, tool_budget_exceeded | 达到 Agent 最大工具调用轮数 |
| protected-branch-normalization | yes | pass | pass | 7 | - | - |
| log-secret-redaction | no | fail | pass | 14 | agent_failed, hidden_test_failed, tool_budget_exceeded | 达到 Agent 最大工具调用轮数 |
| protected-branch-normalization | no | fail | pass | 15 | agent_failed, hidden_test_failed, tool_budget_exceeded | 达到 Agent 最大工具调用轮数 |

## Stability

| Case | Passes | Runs | Pass rate |
|---|---:|---:|---:|
| log-secret-redaction | 1 | 3 | 33.3% |
| protected-branch-normalization | 2 | 3 | 66.7% |
