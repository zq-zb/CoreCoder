# CoreCoder Resilience Campaign

- Scenarios: 5/5
- Pass rate: 100.0%
- Total duration: 277.140 ms

| Scenario | Expected | Actual | Recovery | Result |
|---|---|---|---:|---:|
| worker_loss_requeue | pending | pending | 37.142 ms | PASS |
| retry_exhaustion | failed | failed | 35.314 ms | PASS |
| cancel_during_worker_loss | cancelled | cancelled | 43.395 ms | PASS |
| idempotency_storm | 1 | 1 | 160.848 ms | PASS |
| approval_replay | rejected | rejected | 0.216 ms | PASS |

## Evidence

### worker_loss_requeue

```json
{
  "recovered_tasks": 1,
  "attempts": 1
}
```

### retry_exhaustion

```json
{
  "attempts": 1,
  "last_error": "Worker 租约过期且达到最大尝试次数"
}
```

### cancel_during_worker_loss

```json
{
  "intermediate_status": "cancel_requested"
}
```

### idempotency_storm

```json
{
  "submissions": 64,
  "unique_task_ids": 1,
  "stored_tasks": 1
}
```

### approval_replay

```json
{
  "first_status": "consumed",
  "second_allowed": false,
  "final_status": "consumed"
}
```
