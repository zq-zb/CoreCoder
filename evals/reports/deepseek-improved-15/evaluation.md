# CoreCoder Evaluation Report

- Model: deepseek-v4-flash
- Provider: openai
- Strategy: baseline
- Dataset: `ceccdefe45540244`
- Git commit: `30ceae089696bd7f119b24c12771bc463cae60be`

- Cases: 14/15
- Success rate: 93.3%
- Hidden test pass rate: 93.3%
- Scope compliance rate: 100.0%
- Average tool calls: 6.93
- Average failed test runs: 0.07
- Average duration: 15.78s
- Context compressions: 0
- Estimated context tokens saved: 0

| Case | Success | Hidden tests | Scope | Tool calls | Failures | Task reason |
|---|---:|---:|---:|---:|---|---|
| calculator-sign | yes | pass | pass | 5 | - | - |
| slugify-whitespace | yes | pass | pass | 8 | - | - |
| discount-call-chain | yes | pass | pass | 6 | - | - |
| timeout-validation | yes | pass | pass | 5 | - | - |
| truncate-contract | yes | pass | pass | 6 | - | - |
| retry-policy-boundary | yes | pass | pass | 7 | - | - |
| pagination-empty-page | yes | pass | pass | 8 | - | - |
| path-permission-boundary | yes | pass | pass | 6 | - | - |
| log-secret-redaction | no | fail | pass | 4 | hidden_test_failed | - |
| config-precedence | yes | pass | pass | 11 | - | - |
| webhook-signature-validation | yes | pass | pass | 7 | - | - |
| lease-expiry-boundary | yes | pass | pass | 7 | - | - |
| ci-log-failure-classification | yes | pass | pass | 6 | - | - |
| protected-branch-normalization | yes | pass | pass | 7 | - | - |
| batch-deduplication-order | yes | pass | pass | 11 | - | - |
