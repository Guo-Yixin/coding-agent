"""Gitee API 访问封装。

本模块只负责与 Gitee HTTP API 和仓库 URL 解析相关的低层能力：
解析仓库地址、读取访问令牌、创建 Pull Request、发布 PR 评论、处理重复 PR 响应。

上层 LangChain/DeepAgents 工具定义在 `gitee_tools.py` 中。
这样的分层可以让 API 调用逻辑脱离模型工具协议，便于单元测试、复用和错误处理。
"""

from __future__ import annotations

import re

import httpx

from agent.env_utils import get_env
from agent.repository import Repository, mask_tokens, parse_repo_url

GiteeRepo = Repository


def parse_gitee_repo_url(repo_url: str) -> GiteeRepo:
    """解析 Gitee 仓库 URL。

    Args:
        repo_url: 用户输入或任务配置中的 Gitee 仓库地址，支持带 `.git` 后缀的 HTTPS 地址。

    Returns:
        标准化后的 `GiteeRepo`。

    Raises:
        ValueError: URL 不是 gitee.com 域名，或路径中无法解析出 owner/repo。
    """

    return parse_repo_url(repo_url, provider="gitee")


def normalize_gitee_repo_url(repo_url: str) -> str:
    """把 Gitee 仓库地址规范化为不含 token 的标准 HTTPS clone URL。

    这个函数只负责 URL 规范化，不再承担“仓库地址映射到本地目录”的职责。
    本地目录由 `repo_project_dir()` 固定推导为 `projects/<repo>`。
    """

    return parse_gitee_repo_url(repo_url).clone_url


# def authenticated_clone_url(repo: GiteeRepo) -> str:
#     """返回普通 Gitee clone URL。
#
#     函数名保留是为了兼容旧调用点。实际认证方式已按 open-swe 调整为：
#     Git 命令使用普通 URL，LocalShellBackend 通过 GIT_ASKPASS 注入 GITEE_TOKEN。
#     这样不会把 token 写入命令、日志或 .git/config。
#     """
#
#     return repo.clone_url


def get_gitee_token() -> str:
    """读取 Gitee 私人令牌，兼容 open-swe 的 SCM_GITEE_TOKEN。

    优先读取 `GITEE_TOKEN`，没有时回退到 `SCM_GITEE_TOKEN`。
    这两个变量只在 API 请求或 Git askpass 环境中使用，不应拼接到日志或命令文本中。
    """

    token = get_env("GITEE_TOKEN").strip() or get_env("SCM_GITEE_TOKEN").strip()
    if not token:
        raise RuntimeError("Missing required environment variable: GITEE_TOKEN or SCM_GITEE_TOKEN")
    return token


def mask_token(text: str) -> str:
    """对文本中的 Gitee Token 做脱敏。

    API 错误、Git 输出和异常信息可能包含访问令牌。
    所有写日志或返回给模型的外部错误文本都应经过该函数处理。
    """

    return mask_tokens(text)


def _existing_pr_from_error(text: str) -> dict | None:
    """从 Gitee 重复 PR 错误里提取已有 PR 地址。

    Gitee 在相同 head/base 已有 PR 时会返回 400，而不是幂等成功。
    对当前 Agent 来说，这种情况应该视为“PR 已存在，可复用”，否则同一分支重复执行时，
    已经完成的提交协作流程会被误判为失败。
    """

    # Gitee 返回体是自然语言错误，当前只能基于关键文本和 PR URL 做兼容解析。
    if "已存在相同源分支、目标分支" not in text:
        return None
    match = re.search(r"https://gitee\.com/[^\"<>\\\s]+/pulls/\d+", text)
    if not match:
        return None
    url = match.group(0)
    return {
        "html_url": url,
        "url": url,
        "reused": True,
        "message": "已复用相同源分支和目标分支的现有 Pull Request",
    }


def create_pull_request(
    *,
    owner: str,
    repo: str,
    head: str,
    base: str | None,
    title: str,
    body: str,
) -> dict:
    """调用 Gitee API 创建 Pull Request。

    Args:
        owner: Gitee 仓库 owner。
        repo: Gitee 仓库名称。
        head: 源分支名称。
        base: 目标分支名称。
        title: PR 标题。
        body: PR 描述。

    Returns:
        Gitee API 返回的 PR JSON；如果检测到重复 PR，则返回带 `reused=True` 的兼容结构。

    Raises:
        RuntimeError: API 返回失败且无法识别为可复用 PR。
    """

    api_base = get_env("GITEE_API_BASE_URL", "https://gitee.com/api/v5").rstrip("/")
    token = get_gitee_token()
    url = f"{api_base}/repos/{owner}/{repo}/pulls"
    # Gitee v5 API 使用 access_token 表单字段认证。
    # 该 payload 不写日志，调用异常向上抛出前也应在上层做 token 脱敏。
    target_base = base or str((_gitee_get(f"/repos/{owner}/{repo}") or {}).get("default_branch") or "master")
    payload = {
        "access_token": token,
        "title": title,
        "head": head,
        "base": target_base,
        "body": body,
    }
    with httpx.Client(timeout=30) as client:
        response = client.post(url, data=payload)
    if response.status_code >= 400:
        # 相同 head/base 的 PR 已存在时复用已有 PR，保证工具具备幂等语义。
        existing = _existing_pr_from_error(response.text)
        if existing is not None:
            return existing
        raise RuntimeError(f"Gitee 创建 PR 失败: {response.status_code} {mask_token(response.text)}")
    return response.json()


def _gitee_get(path: str, *, params: dict | None = None) -> dict | list:
    """执行 Gitee GET 请求。

    Gitee v5 API 的只读接口同样使用 `access_token` 参数认证。这里集中处理
    token 注入、base url 和错误抛出，避免多个读取函数重复写 HTTP 细节。
    """

    api_base = get_env("GITEE_API_BASE_URL", "https://gitee.com/api/v5").rstrip("/")
    payload = dict(params or {})
    payload["access_token"] = get_gitee_token()
    url = f"{api_base}{path}"
    with httpx.Client(timeout=30) as client:
        response = client.get(url, params=payload)
    if response.status_code >= 400:
        raise RuntimeError(f"Gitee API 读取失败: {response.status_code} {mask_token(response.text)}")
    return response.json()


def get_pull_request(*, owner: str, repo: str, number: int) -> dict:
    """读取 Gitee Pull Request 详情。"""

    data = _gitee_get(f"/repos/{owner}/{repo}/pulls/{number}")
    return data if isinstance(data, dict) else {"items": data}


def list_pull_request_commits(*, owner: str, repo: str, number: int) -> list:
    """读取 Gitee Pull Request 的提交列表。"""

    data = _gitee_get(f"/repos/{owner}/{repo}/pulls/{number}/commits")
    return data if isinstance(data, list) else [data]


def list_pull_request_files(*, owner: str, repo: str, number: int) -> list:
    """读取 Gitee Pull Request 的文件变更列表。"""

    data = _gitee_get(f"/repos/{owner}/{repo}/pulls/{number}/files")
    return data if isinstance(data, list) else [data]


def list_pull_request_comments(*, owner: str, repo: str, number: int) -> list:
    """读取 Gitee Pull Request 的普通评论列表。"""

    data = _gitee_get(f"/repos/{owner}/{repo}/pulls/{number}/comments")
    return data if isinstance(data, list) else [data]


def post_pr_comment(*, owner: str, repo: str, number: int, body: str) -> dict:
    """调用 Gitee API 向 Pull Request 发布评论。

    Args:
        owner: Gitee 仓库 owner。
        repo: Gitee 仓库名称。
        number: PR 编号。
        body: 评论正文。

    Returns:
        Gitee API 返回的评论 JSON。

    Raises:
        RuntimeError: API 返回失败状态码。
    """

    api_base = get_env("GITEE_API_BASE_URL", "https://gitee.com/api/v5").rstrip("/")
    token = get_gitee_token()
    url = f"{api_base}/repos/{owner}/{repo}/pulls/{number}/comments"
    with httpx.Client(timeout=30) as client:
        response = client.post(url, data={"access_token": token, "body": body})
    if response.status_code >= 400:
        raise RuntimeError(f"Gitee 发布 PR 评论失败: {response.status_code} {mask_token(response.text)}")
    return response.json()


def create_issue(*, owner: str, repo: str, title: str, body: str, labels: list[str] | None = None) -> dict:
    """创建 Gitee Issue。"""

    api_base = get_env("GITEE_API_BASE_URL", "https://gitee.com/api/v5").rstrip("/")
    token = get_gitee_token()
    payload: dict[str, object] = {"access_token": token, "title": title, "body": body}
    if labels:
        payload["labels"] = ",".join(labels)
    with httpx.Client(timeout=30) as client:
        response = client.post(f"{api_base}/repos/{owner}/{repo}/issues", data=payload)
    if response.status_code >= 400:
        raise RuntimeError(f"Gitee 创建 Issue 失败: {response.status_code} {mask_token(response.text)}")
    return response.json()


def get_issue(*, owner: str, repo: str, number: int) -> dict:
    data = _gitee_get(f"/repos/{owner}/{repo}/issues/{number}")
    return data if isinstance(data, dict) else {"items": data}


def list_issue_comments(*, owner: str, repo: str, number: int) -> list:
    data = _gitee_get(f"/repos/{owner}/{repo}/issues/{number}/comments")
    return data if isinstance(data, list) else [data]


def post_issue_comment(*, owner: str, repo: str, number: int, body: str) -> dict:
    api_base = get_env("GITEE_API_BASE_URL", "https://gitee.com/api/v5").rstrip("/")
    token = get_gitee_token()
    with httpx.Client(timeout=30) as client:
        response = client.post(
            f"{api_base}/repos/{owner}/{repo}/issues/{number}/comments",
            data={"access_token": token, "body": body},
        )
    if response.status_code >= 400:
        raise RuntimeError(f"Gitee 发布 Issue 评论失败: {response.status_code} {mask_token(response.text)}")
    return response.json()
