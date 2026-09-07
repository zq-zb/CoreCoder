"""通过 GitHub CLI 提供可测试的 GitHub 只读服务层。"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from typing import Any

_REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class GitHubServiceError(RuntimeError):
    """GitHub CLI 调用失败，并标记是否适合保守重试。"""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        self.retryable = retryable
        super().__init__(message)


@dataclass(frozen=True)
class GitHubService:
    """把 gh CLI 包装成不依赖 shell 字符串拼接的只读查询。"""

    timeout: float = 15.0
    max_log_chars: int = 12_000

    def read_issue(self, repository: str, issue_number: int) -> dict[str, Any]:
        repository = _validate_repository(repository)
        if issue_number <= 0:
            raise ValueError("Issue 编号必须大于 0")
        issue = self._run_json("api", f"repos/{repository}/issues/{issue_number}")
        if "pull_request" in issue:
            raise GitHubServiceError(f"#{issue_number} 是 Pull Request，不是 Issue")
        return {
            "repository": repository,
            "number": issue["number"],
            "title": issue["title"],
            "state": issue["state"],
            "body": issue.get("body") or "",
            "labels": [label["name"] for label in issue.get("labels", [])],
            "assignees": [user["login"] for user in issue.get("assignees", [])],
            "author": issue.get("user", {}).get("login"),
            "url": issue["html_url"],
        }

    def read_pull_request(self, repository: str, pull_number: int) -> dict[str, Any]:
        """读取 PR 摘要，避免把 GitHub API 的全量字段塞入上下文。"""

        repository = _validate_repository(repository)
        if pull_number <= 0:
            raise ValueError("Pull Request 编号必须大于 0")
        pull = self._run_json("api", f"repos/{repository}/pulls/{pull_number}")
        return {
            "repository": repository,
            "number": pull["number"],
            "title": pull["title"],
            "state": pull["state"],
            "draft": pull.get("draft", False),
            "body": pull.get("body") or "",
            "author": pull.get("user", {}).get("login"),
            "base_branch": pull.get("base", {}).get("ref"),
            "head_branch": pull.get("head", {}).get("ref"),
            "mergeable": pull.get("mergeable"),
            "changed_files": pull.get("changed_files", 0),
            "additions": pull.get("additions", 0),
            "deletions": pull.get("deletions", 0),
            "labels": [label["name"] for label in pull.get("labels", [])],
            "url": pull["html_url"],
        }

    def get_pull_request_diff(self, repository: str, pull_number: int) -> dict[str, Any]:
        """读取可控长度的 PR unified diff。"""

        repository = _validate_repository(repository)
        if pull_number <= 0:
            raise ValueError("Pull Request 编号必须大于 0")
        diff = self._run_text(
            "api",
            f"repos/{repository}/pulls/{pull_number}",
            "-H",
            "Accept: application/vnd.github.v3.diff",
        )
        truncated = len(diff) > self.max_log_chars
        if truncated:
            diff = diff[: self.max_log_chars] + "\n... Pull Request Diff 已截断 ..."
        return {
            "repository": repository,
            "pull_number": pull_number,
            "diff": diff,
            "truncated": truncated,
        }

    def list_failed_workflow_runs(self, repository: str, limit: int = 5) -> dict[str, Any]:
        repository = _validate_repository(repository)
        if not 1 <= limit <= 20:
            raise ValueError("失败 Workflow 查询数量必须在 1到20 之间")
        payload = self._run_json(
            "api",
            "--method",
            "GET",
            f"repos/{repository}/actions/runs",
            "-f",
            "status=failure",
            "-f",
            f"per_page={limit}",
        )
        runs = [
            {
                "run_id": run["id"],
                "name": run.get("name") or run.get("display_title") or "",
                "branch": run.get("head_branch"),
                "event": run.get("event"),
                "conclusion": run.get("conclusion"),
                "created_at": run.get("created_at"),
                "url": run.get("html_url"),
            }
            for run in payload.get("workflow_runs", [])[:limit]
        ]
        return {"repository": repository, "count": len(runs), "runs": runs}

    def get_workflow_run_failure(self, repository: str, run_id: int) -> dict[str, Any]:
        repository = _validate_repository(repository)
        if run_id <= 0:
            raise ValueError("Workflow Run ID 必须大于 0")
        payload = self._run_json("api", f"repos/{repository}/actions/runs/{run_id}/jobs?filter=latest")
        failed_jobs = []
        for job in payload.get("jobs", []):
            failed_steps = [
                {"number": step.get("number"), "name": step.get("name"), "conclusion": step.get("conclusion")}
                for step in job.get("steps", [])
                if step.get("conclusion") in {"failure", "cancelled", "timed_out"}
            ]
            if job.get("conclusion") != "success" or failed_steps:
                failed_jobs.append(
                    {
                        "job_id": job.get("id"),
                        "name": job.get("name"),
                        "conclusion": job.get("conclusion"),
                        "failed_steps": failed_steps,
                        "url": job.get("html_url"),
                    }
                )
        # 成功 Run 没有失败日志，避免再发起一次无意义的网络请求。
        logs = ""
        if failed_jobs:
            logs = self._run_text("run", "view", str(run_id), "--repo", repository, "--log-failed")
        if len(logs) > self.max_log_chars:
            logs = logs[: self.max_log_chars] + "\n... GitHub Actions 日志已截断 ..."
        return {
            "repository": repository,
            "run_id": run_id,
            "failed_jobs": failed_jobs,
            "failed_logs": logs,
        }

    def _run_json(self, *arguments: str) -> dict[str, Any]:
        output = self._run_text(*arguments)
        try:
            value = json.loads(output)
        except json.JSONDecodeError as error:
            raise GitHubServiceError(f"GitHub CLI 返回了无效 JSON：{error}") from error
        if not isinstance(value, dict):
            raise GitHubServiceError("GitHub CLI 返回的 JSON 不是对象")
        return value

    def _run_text(self, *arguments: str) -> str:
        command = ["gh", *arguments]
        try:
            completed = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
            )
        except FileNotFoundError as error:
            raise GitHubServiceError("未找到 GitHub CLI，请先安装 gh") from error
        except subprocess.TimeoutExpired as error:
            raise GitHubServiceError(f"GitHub 请求超过 {self.timeout} 秒", retryable=True) from error
        except subprocess.CalledProcessError as error:
            message = (error.stderr or error.stdout or str(error)).strip()
            retryable = _looks_transient(message)
            raise GitHubServiceError(f"GitHub CLI 调用失败：{message}", retryable=retryable) from error
        return completed.stdout.strip()


def _validate_repository(repository: str) -> str:
    repository = repository.strip()
    if not _REPOSITORY_PATTERN.fullmatch(repository):
        raise ValueError("仓库必须使用 owner/name 格式")
    return repository


def _looks_transient(message: str) -> bool:
    lowered = message.lower()
    return any(
        marker in lowered
        for marker in ("timeout", "timed out", "temporarily unavailable", "502", "503", "504")
    )
