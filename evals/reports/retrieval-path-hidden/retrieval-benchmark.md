# CoreCoder Retrieval Benchmark

- Cases: 3
- Target recall @1/@3/@5: 33.3% / 100.0% / 100.0%
- Context recall @1/@3/@5: 30.6% / 91.7% / 91.7%
- Mean reciprocal rank: 1.000
- Average duration: 0.003882s

| Case | Ranked files | Target R@1/R@3/R@5 | Context R@1/R@3/R@5 | First relevant |
|---|---|---|---|---:|
| discount-call-chain | checkout.py, pricing.py, test_checkout.py, checkout_legacy.py, checkout_validator.py | 0%/100%/100% | 33%/100%/100% | 1 |
| pagination-empty-page | service.py, api_client.py, test_service.py, page_serializer.py, pagination_metrics.py | 100%/100%/100% | 33%/100%/100% | 1 |
| access-policy-call-chain | models.py, access_policy.py, gateway.py | 0%/100%/100% | 25%/75%/75% | 1 |
