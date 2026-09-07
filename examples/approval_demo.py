"""不执行真实外部命令，演示一次性审批生命周期。"""

import sys
from pathlib import Path

from corecoder.security import ApprovalManager, CommandPolicy


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    command = "git push origin main"
    decision = CommandPolicy().evaluate(command)
    snapshot = Path("evals/reports/demo/approvals.json")
    approvals = ApprovalManager(ttl_seconds=300, snapshot_path=snapshot)

    request = approvals.request(command, decision.reason)
    print(f"1. 风险等级：{decision.risk.value}")
    print(f"2. 生成审批单：{request.request_id} ({request.status.value})")

    approved = approvals.approve(request.request_id, "demo-reviewer")
    print(f"3. 审批通过：{approved.approver} ({approved.status.value})")

    consumed = approvals.consume(command)
    print(f"4. 精确命令首次消费：{consumed.status.value if consumed else 'denied'}")
    print(f"5. 相同审批再次消费：{'allowed' if approvals.consume(command) else 'denied'}")
    print(f"6. 审批快照：{snapshot.resolve()}")


if __name__ == "__main__":
    main()
