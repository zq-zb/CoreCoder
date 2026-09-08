# CoreCoder Retrieval Benchmark

- Cases: 2
- Target recall @1/@3/@5: 50.0% / 50.0% / 50.0%
- Context recall @1/@3/@5: 33.3% / 66.7% / 83.3%
- Mean reciprocal rank: 1.000
- Average duration: 0.010812s

| Case | Ranked files | Target R@1/R@3/R@5 | Context R@1/R@3/R@5 | First relevant |
|---|---|---|---|---:|
| discount-call-chain | checkout.py, test_checkout.py, checkout_legacy.py, checkout_validator.py, discount_audit.py | 0%/0%/0% | 33%/67%/67% | 1 |
| pagination-empty-page | service.py, test_service.py, page_serializer.py, pagination_metrics.py, api_client.py | 100%/100%/100% | 33%/67%/100% | 1 |
