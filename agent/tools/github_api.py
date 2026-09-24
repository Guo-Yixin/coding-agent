"""GitHub.com REST API 适配层。

只实现当前产品范围需要的能力：仓库信息、Issue/PR、普通评论、Review Comment
回流以及 GitHub Actions/Commit Status 读取和操作。Checks API 不作为 Fine-grained
PAT 的必需依赖，因为 GitHub 当前对该能力存在限制。
"""

from __future__ import annotations

from typing import Any

import httpx

from agent.env_utils import get_env
from agent.repository import Repository, get_provider_token, mask_tokens


def get_github_token() -> str:
    return get_provider_token("github")


def _github_request(method: str, path: str, *, params: dict[str, Any] | None = None, json: dict[str, Any] | None = None) -> Any:
    base = get_env("GITHUB_API_BASE_URL", "https://api.github.com").rstrip("/")
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {get_github_token()}",
        "X-GitHub-Api-Version": get_env("GITHUB_API_VERSION", "2022-11-28"),
    }
    with httpx.Client(timeout=30, headers=headers) as client:
        response = client.request(method, f"{base}{path}", params=params, json=json)
    if response.status_code >= 400:
        raise RuntimeError(f"GitHub API 请求失败: {response.status_code} {mask_tokens(response.text)}")
    if response.status_code == 204 or not response.content:
        return {}
    return response.json()


def get_repository(*, owner: str, repo: str) -> dict[str, Any]:
    return _github_request("GET", f"/repos/{owner}/{repo}")


def get_default_branch(*, owner: str, repo: str) -> str:
    data = get_repository(owner=owner, repo=repo)
    return str(data.get("default_branch") or "main")


def create_pull_request(*, owner: str, repo: str, head: str, base: str | None, title: str, body: str) -> dict[str, Any]:
    target_base = base or get_default_branch(owner=owner, repo=repo)
    payload = {"title": title, "head": head, "base": target_base, "body": body, "draft": False}
    try:
        return _github_request("POST", f"/repos/{owner}/{repo}/pulls", json=payload)
    except RuntimeError as exc:
        # GitHub 返回 422 时可能表示相同 head/base 的 PR 已存在；复用它保持幂等。
        if "422" not in str(exc):
            raise
        existing = _github_request(
            "GET",
            f"/repos/{owner}/{repo}/pulls",
            params={"state": "open", "head": f"{owner}:{head}", "base": target_base},
        )
        if isinstance(existing, list) and existing:
            result = dict(existing[0])
            result["reused"] = True
            return result
        raise


def get_pull_request(*, owner: str, repo: str, number: int) -> dict[str, Any]:
    return _github_request("GET", f"/repos/{owner}/{repo}/pulls/{number}")


def list_pull_request_commits(*, owner: str, repo: str, number: int) -> list[dict[str, Any]]:
    data = _github_request("GET", f"/repos/{owner}/{repo}/pulls/{number}/commits", params={"per_page": 100})
    return data if isinstance(data, list) else []


def list_pull_request_files(*, owner: str, repo: str, number: int) -> list[dict[str, Any]]:
    data = _github_request("GET", f"/repos/{owner}/{repo}/pulls/{number}/files", params={"per_page": 100})
    return data if isinstance(data, list) else []


def list_pull_request_comments(*, owner: str, repo: str, number: int) -> list[dict[str, Any]]:
    data = _github_request("GET", f"/repos/{owner}/{repo}/issues/{number}/comments", params={"per_page": 100})
    return data if isinstance(data, list) else []


def list_pull_request_review_comments(*, owner: str, repo: str, number: int) -> list[dict[str, Any]]:
    data = _github_request("GET", f"/repos/{owner}/{repo}/pulls/{number}/comments", params={"per_page": 100})
    return data if isinstance(data, list) else []


def list_pull_request_reviews(*, owner: str, repo: str, number: int) -> list[dict[str, Any]]:
    data = _github_request("GET", f"/repos/{owner}/{repo}/pulls/{number}/reviews", params={"per_page": 100})
    return data if isinstance(data, list) else []


def post_pr_comment(*, owner: str, repo: str, number: int, body: str) -> dict[str, Any]:
    return _github_request("POST", f"/repos/{owner}/{repo}/issues/{number}/comments", json={"body": body})


def create_issue(*, owner: str, repo: str, title: str, body: str, labels: list[str] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"title": title, "body": body}
    if labels:
        payload["labels"] = labels
    return _github_request("POST", f"/repos/{owner}/{repo}/issues", json=payload)


def get_issue(*, owner: str, repo: str, number: int) -> dict[str, Any]:
    return _github_request("GET", f"/repos/{owner}/{repo}/issues/{number}")


def list_issue_comments(*, owner: str, repo: str, number: int) -> list[dict[str, Any]]:
    data = _github_request("GET", f"/repos/{owner}/{repo}/issues/{number}/comments", params={"per_page": 100})
    return data if isinstance(data, list) else []


def post_issue_comment(*, owner: str, repo: str, number: int, body: str) -> dict[str, Any]:
    return _github_request("POST", f"/repos/{owner}/{repo}/issues/{number}/comments", json={"body": body})


def get_issue_context(*, owner: str, repo: str, number: int) -> dict[str, Any]:
    issue = get_issue(owner=owner, repo=repo, number=number)
    comments = list_issue_comments(owner=owner, repo=repo, number=number)
    return {
        "issue": issue,
        "comments": comments,
        "summary": {
            "title": issue.get("title") if isinstance(issue, dict) else None,
            "state": issue.get("state") if isinstance(issue, dict) else None,
            "comments_count": len(comments),
        },
    }


def list_workflow_runs(*, owner: str, repo: str, head_sha: str | None = None) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"per_page": 50}
    if head_sha:
        params["head_sha"] = head_sha
    data = _github_request("GET", f"/repos/{owner}/{repo}/actions/runs", params=params)
    return list((data or {}).get("workflow_runs") or []) if isinstance(data, dict) else []


def list_commit_statuses(*, owner: str, repo: str, ref: str) -> list[dict[str, Any]]:
    data = _github_request("GET", f"/repos/{owner}/{repo}/commits/{ref}/statuses", params={"per_page": 100})
    return data if isinstance(data, list) else []


def rerun_workflow(*, owner: str, repo: str, run_id: int, failed_jobs_only: bool = False) -> dict[str, Any]:
    suffix = "rerun-failed-jobs" if failed_jobs_only else "rerun"
    return _github_request("POST", f"/repos/{owner}/{repo}/actions/runs/{run_id}/{suffix}")


def cancel_workflow(*, owner: str, repo: str, run_id: int) -> dict[str, Any]:
    return _github_request("POST", f"/repos/{owner}/{repo}/actions/runs/{run_id}/cancel")


def get_pull_request_context(*, owner: str, repo: str, number: int) -> dict[str, Any]:
    pull_request = get_pull_request(owner=owner, repo=repo, number=number)
    head_sha = ((pull_request.get("head") or {}).get("sha") or "") if isinstance(pull_request, dict) else ""
    commits = list_pull_request_commits(owner=owner, repo=repo, number=number)
    files = list_pull_request_files(owner=owner, repo=repo, number=number)
    comments = list_pull_request_comments(owner=owner, repo=repo, number=number)
    review_comments = list_pull_request_review_comments(owner=owner, repo=repo, number=number)
    reviews = list_pull_request_reviews(owner=owner, repo=repo, number=number)
    return {
        "pull_request": pull_request,
        "commits": commits,
        "files": files,
        "comments": comments,
        "review_comments": review_comments,
        "reviews": reviews,
        "workflow_runs": list_workflow_runs(owner=owner, repo=repo, head_sha=head_sha),
        "commit_statuses": list_commit_statuses(owner=owner, repo=repo, ref=head_sha) if head_sha else [],
        "summary": {
            "title": pull_request.get("title") if isinstance(pull_request, dict) else None,
            "state": pull_request.get("state") if isinstance(pull_request, dict) else None,
            "merged": pull_request.get("merged") if isinstance(pull_request, dict) else None,
            "mergeable_state": pull_request.get("mergeable_state") if isinstance(pull_request, dict) else None,
            "files_count": len(files),
            "commits_count": len(commits),
        },
    }
