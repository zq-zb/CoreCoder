# CoreCoder Retrieval Benchmark

- Cases: 2
- Target recall @1/@3/@5: 50.0% / 100.0% / 100.0%
- Context recall @1/@3/@5: 33.3% / 100.0% / 100.0%
- Mean reciprocal rank: 1.000
- Average duration: 0.002191s

| Case | Ranked files | Target R@1/R@3/R@5 | Context R@1/R@3/R@5 | First relevant |
|---|---|---|---|---:|
| discount-call-chain | checkout.py, test_checkout.py, pricing.py | 0%/100%/100% | 33%/100%/100% | 1 |
| pagination-empty-page | service.py, test_service.py, api_client.py | 100%/100%/100% | 33%/100%/100% | 1 |
