# CoreCoder Evaluation Report

- Model: deepseek-v4-flash
- Provider: openai
- Strategy: baseline
- Dataset: `bde831716c59f8cd`
- Git commit: `30ceae089696bd7f119b24c12771bc463cae60be`

- Cases: 1/3
- Success rate: 33.3%
- Hidden test pass rate: 33.3%
- Scope compliance rate: 100.0%
- Average tool calls: 8.00
- Average failed test runs: 0.00
- Average duration: 22.23s
- Context compressions: 0
- Estimated context tokens saved: 0

| Case | Success | Hidden tests | Scope | Tool calls | Failures | Task reason |
|---|---:|---:|---:|---:|---|---|
| protected-branch-normalization | no | fail | pass | 5 | hidden_test_failed | - |
| protected-branch-normalization | no | fail | pass | 8 | hidden_test_failed | - |
| protected-branch-normalization | yes | pass | pass | 11 | - | - |

## Stability

| Case | Passes | Runs | Pass rate |
|---|---:|---:|---:|
| protected-branch-normalization | 1 | 3 | 33.3% |
