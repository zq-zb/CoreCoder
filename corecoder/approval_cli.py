"""本地审批命令行：只管理审批状态，不直接执行命令。"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from .security import ApprovalManager


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="查看或批准 CoreCoder 高风险操作")
    parser.add_argument("--store", type=Path, default=Path(".corecoder/approvals.json"), help="审批快照路径")
    subcommands = parser.add_subparsers(dest="action", required=True)
    subcommands.add_parser("list", help="列出审批请求")
    approve = subcommands.add_parser("approve", help="批准一条待审批请求")
    approve.add_argument("request_id")
    approve.add_argument("--approver", required=True, help="审批人标识")
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    options = _parser().parse_args(argv)
    try:
        manager = ApprovalManager(snapshot_path=options.store)
        if options.action == "approve":
            request = manager.approve(options.request_id, options.approver)
            print(f"审批完成：{request.request_id}，审批人：{request.approver}")
            return 0
        requests = manager.list_requests()
    except (KeyError, ValueError) as error:
        print(f"审批操作失败：{error}")
        return 2

    if not requests:
        print("当前没有审批请求。")
        return 0
    for request in requests:
        expires = datetime.fromtimestamp(request.expires_at).astimezone().isoformat(timespec="seconds")
        print(f"{request.request_id}  {request.status.value:8}  截止：{expires}")
        print(f"  风险：{request.reason}")
        print(f"  命令：{request.command_preview}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
