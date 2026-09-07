# CoreCoder Evaluation Report

- Model: deepseek-v4-flash
- Provider: openai
- Strategy: baseline
- Dataset: `b9d33a775202755a`
- Git commit: `30ceae089696bd7f119b24c12771bc463cae60be`

- Cases: 1/6
- Success rate: 16.7%
- Hidden test pass rate: 66.7%
- Scope compliance rate: 100.0%
- Average tool calls: 13.33
- Average failed test runs: 0.17
- Average duration: 36.50s
- Context compressions: 0
- Estimated context tokens saved: 0

| Case | Success | Hidden tests | Scope | Tool calls | Failures | Task reason |
|---|---:|---:|---:|---:|---|---|
| log-secret-redaction | yes | pass | pass | 8 | - | - |
| protected-branch-normalization | no | fail | pass | 13 | agent_failed, hidden_test_failed, tool_budget_exceeded | 达到 Agent 最大工具调用轮数 |
| log-secret-redaction | no | fail | pass | 14 | agent_failed, hidden_test_failed, tool_budget_exceeded | 达到 Agent 最大工具调用轮数 |
| protected-branch-normalization | no | pass | pass | 14 | agent_failed, tool_budget_exceeded | 达到 Agent 最大工具调用轮数 |
| log-secret-redaction | no | pass | pass | 15 | agent_failed, tool_budget_exceeded | 达到 Agent 最大工具调用轮数 |
| protected-branch-normalization | no | pass | pass | 16 | agent_failed, tool_budget_exceeded | 达到 Agent 最大工具调用轮数 |

## Stability

| Case | Passes | Runs | Pass rate |
|---|---:|---:|---:|
| log-secret-redaction | 1 | 3 | 33.3% |
| protected-branch-normalization | 0 | 3 | 0.0% |
