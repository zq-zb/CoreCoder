# CoreCoder Retrieval Scale Benchmark

- Query: `critical_payment_handler`
- Repetitions per size: 7

| Files | Cold (ms) | Warm mean (ms) | Warm P95 (ms) | One-file refresh (ms) | Speedup |
|---:|---:|---:|---:|---:|---:|
| 100 | 92.65 | 16.64 | 17.34 | 18.76 | 5.57x |
| 500 | 430.18 | 62.88 | 66.63 | 66.31 | 6.84x |
| 1000 | 862.86 | 137.54 | 148.65 | 139.84 | 6.27x |
| 3000 | 2884.72 | 387.23 | 402.46 | 410.42 | 7.45x |
