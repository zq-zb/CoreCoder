"""GitHub 只读服务的参数验证、结果整理和错误分类测试。"""

import json
import subprocess

import pytest

from corecoder.github_service import GitHubService, GitHubServiceError


def _completed(payload) -> subprocess.CompletedProcess:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.CompletedProcess([], 0, stdout=text, stderr="")


def test_read_issue_returns_only_agent_relevant_fields(monkeypatch):
    payload = {
        "number": 12,
        "title": "Fix timeout",
        "state": "open",
        "body": "Timeout after five seconds",
        "labels": [{"name": "bug"}],
        "assignees": [{"login": "alice"}],
        "user": {"login": "bob"},
        "html_url": "https://github.com/acme/core/issues/12",
        "unused": "不需要传给 Agent 的字段",
    }
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: _completed(payload))

    result = GitHubService().read_issue("acme/core", 12)

    assert result == {
        "repository": "acme/core",
        "number": 12,
        "title": "Fix timeout",
        "state": "open",
        "body": "Timeout after five seconds",
        "labels": ["bug"],
        "assignees": ["alice"],
        "author": "bob",
        "url": "https://github.com/acme/core/issues/12",
    }


def test_list_failed_workflow_runs_limits_and_normalizes_results(monkeypatch):
    payload = {
        "workflow_runs": [
            {
                "id": 101,
                "name": "tests",
                "head_branch": "main",
                "event": "push",
                "conclusion": "failure",
                "created_at": "2026-08-21T00:00:00Z",
                "html_url": "https://github.com/acme/core/actions/runs/101",
            }
        ]
    }
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        return _completed(payload)

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = GitHubService().list_failed_workflow_runs("acme/core", limit=3)

    assert result["count"] == 1
    assert result["runs"][0]["run_id"] == 101
    assert seen["command"] == [
        "gh", "api", "--method", "GET", "repos/acme/core/actions/runs",
        "-f", "status=failure", "-f", "per_page=3",
    ]


def test_read_pull_request_returns_summary_for_agent(monkeypatch):
    payload = {
        "number": 4,
        "title": "Add MCP tools",
        "state": "open",
        "draft": False,
        "body": "Implements dynamic discovery",
        "user": {"login": "alice"},
        "base": {"ref": "main"},
        "head": {"ref": "feature/mcp"},
        "mergeable": True,
        "changed_files": 3,
        "additions": 80,
        "deletions": 12,
        "labels": [{"name": "enhancement"}],
        "html_url": "https://github.com/acme/core/pull/4",
    }
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: _completed(payload))

    result = GitHubService().read_pull_request("acme/core", 4)

    assert result["head_branch"] == "feature/mcp"
    assert result["base_branch"] == "main"
    assert result["changed_files"] == 3
    assert result["labels"] == ["enhancement"]


def test_pull_request_diff_is_truncated_to_context_budget(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: _completed("x" * 20))

    result = GitHubService(max_log_chars=10).get_pull_request_diff("acme/core", 4)

    assert result["truncated"] is True
    assert result["diff"].startswith("x" * 10)
    assert "Diff 已截断" in result["diff"]


def test_workflow_failure_combines_failed_steps_and_logs(monkeypatch):
    jobs = {
        "jobs": [
            {
                "id": 9,
                "name": "pytest",
                "conclusion": "failure",
                "html_url": "https://github.com/acme/core/actions/runs/101/job/9",
                "steps": [
                    {"number": 1, "name": "checkout", "conclusion": "success"},
                    {"number": 2, "name": "tests", "conclusion": "failure"},
                ],
            }
        ]
    }
    responses = iter([_completed(jobs), _completed("AssertionError: expected 5")])
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: next(responses))

    result = GitHubService().get_workflow_run_failure("acme/core", 101)

    assert result["failed_jobs"][0]["failed_steps"] == [
        {"number": 2, "name": "tests", "conclusion": "failure"}
    ]
    assert "AssertionError" in result["failed_logs"]


def test_successful_workflow_run_skips_failed_log_request(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return _completed({"jobs": [{"id": 1, "name": "tests", "conclusion": "success", "steps": []}]})

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = GitHubService().get_workflow_run_failure("acme/core", 101)

    assert result["failed_jobs"] == []
    assert result["failed_logs"] == ""
    assert len(calls) == 1


def test_github_service_rejects_unsafe_repository_and_marks_timeout_retryable(monkeypatch):
    service = GitHubService(timeout=0.1)
    with pytest.raises(ValueError, match="owner/name"):
        service.read_issue("acme/core; rm -rf", 1)

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("gh", 0.1)

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(GitHubServiceError) as captured:
        service.read_issue("acme/core", 1)
    assert captured.value.retryable is True


def test_github_auth_error_is_not_retried_blindly(monkeypatch):
    def auth_failure(*args, **kwargs):
        raise subprocess.CalledProcessError(1, ["gh"], stderr="authentication token is invalid")

    monkeypatch.setattr(subprocess, "run", auth_failure)
    with pytest.raises(GitHubServiceError) as captured:
        GitHubService().read_issue("acme/core", 1)
    assert captured.value.retryable is False
