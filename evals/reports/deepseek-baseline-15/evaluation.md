# CoreCoder Evaluation Report

- Model: deepseek-v4-flash
- Provider: openai
- Strategy: baseline
- Dataset: `ceccdefe45540244`
- Git commit: `30ceae089696bd7f119b24c12771bc463cae60be`

- Cases: 13/15
- Success rate: 86.7%
- Hidden test pass rate: 100.0%
- Scope compliance rate: 100.0%
- Average tool calls: 8.27
- Average failed test runs: 0.07
- Average duration: 18.52s
- Context compressions: 0
- Estimated context tokens saved: 0

| Case | Success | Hidden tests | Scope | Tool calls | Failures |
|---|---:|---:|---:|---:|---|
| calculator-sign | yes | pass | pass | 6 | - |
| slugify-whitespace | yes | pass | pass | 6 | - |
| discount-call-chain | yes | pass | pass | 7 | - |
| timeout-validation | yes | pass | pass | 8 | - |
| truncate-contract | yes | pass | pass | 11 | - |
| retry-policy-boundary | yes | pass | pass | 7 | - |
| pagination-empty-page | yes | pass | pass | 8 | - |
| path-permission-boundary | yes | pass | pass | 9 | - |
| log-secret-redaction | yes | pass | pass | 8 | - |
| config-precedence | yes | pass | pass | 7 | - |
| webhook-signature-validation | yes | pass | pass | 10 | - |
| lease-expiry-boundary | yes | pass | pass | 7 | - |
| ci-log-failure-classification | no | pass | pass | 9 | agent_failed |
| protected-branch-normalization | no | pass | pass | 13 | agent_failed, tool_budget_exceeded |
| batch-deduplication-order | yes | pass | pass | 8 | - |
