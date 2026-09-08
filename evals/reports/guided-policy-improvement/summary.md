# Guided Policy Improvement

- Model: `deepseek-v4-flash`
- Case: `access-policy-call-chain`
- Runs per variant: 1

| Variant | Prompt tokens | Tool calls | Policy rejects | Duration | Success | Hidden tests | Target recall | Context recall |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Initial guided | 30,714 | 16 | 1 | 18.76s | yes | pass | 100% | 75% |
| Policy propagation fixed | 26,536 | 16 | 2 | 16.94s | yes | pass | 100% | 75% |
| Search-alone prompt | 23,186 | 14 | 0 | 15.86s | yes | pass | 100% | 75% |

The final run selected `repository_search` alone in round one and had no policy rejection. Prompt tokens were 7,528 lower than the initial guided smoke run while correctness and retrieval recall remained unchanged.

These are single paid runs. They prove that the intended execution path was exercised and provide a directional cost signal, but they do not establish statistical significance or a stable 24.5% improvement.
