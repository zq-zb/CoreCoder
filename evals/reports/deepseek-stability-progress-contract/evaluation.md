# CoreCoder Evaluation Report

- Model: deepseek-v4-flash
- Provider: openai
- Strategy: baseline
- Dataset: `41e5c020bc43c525`
- Git commit: `30ceae089696bd7f119b24c12771bc463cae60be`

- Cases: 3/3
- Success rate: 100.0%
- Hidden test pass rate: 100.0%
- Scope compliance rate: 100.0%
- Average tool calls: 5.67
- Average failed test runs: 0.00
- Average duration: 23.76s
- Context compressions: 0
- Estimated context tokens saved: 0

| Case | Success | Hidden tests | Scope | Tool calls | Failures | Task reason |
|---|---:|---:|---:|---:|---|---|
| log-secret-redaction | yes | pass | pass | 5 | - | - |
| log-secret-redaction | yes | pass | pass | 6 | - | - |
| log-secret-redaction | yes | pass | pass | 6 | - | - |

## Stability

| Case | Passes | Runs | Pass rate |
|---|---:|---:|---:|
| log-secret-redaction | 3 | 3 | 100.0% |
