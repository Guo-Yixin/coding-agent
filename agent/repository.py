"""统一的 Git 托管仓库模型和地址解析。

第一阶段支持 GitHub.com 和 Gitee Cloud 的 HTTPS 仓库地址，以及
``owner/repo`` 简写。认证令牌只从本地环境变量读取，不会进入仓库 URL、日志
或 Git 配置。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from agent.env_utils import get_env

SUPPORTED_PROVIDERS = ("github", "gitee")


@dataclass(frozen=True)
class Repository:
    provider: str
    owner: str
    repo: str
    clone_url: str
    web_url: str

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"


def provider_for_host(hostname: str) -> str | None:
    host = (hostname or "").lower().strip().rstrip(".")
    if host in {"github.com", "www.github.com"}:
        return "github"
    if host in {"gitee.com", "www.gitee.com"}:
        return "gitee"
    return None


def _provider_host(provider: str) -> str:
    if provider == "github":
        return "github.com"
    if provider == "gitee":
        return "gitee.com"
    raise ValueError(f"当前不支持的仓库平台: {provider}")


def parse_repo_url(repo_url: str, *, provider: str | None = None) -> Repository:
    """解析 GitHub/Gitee HTTPS URL 或 owner/repo 简写。"""

    text = (repo_url or "").strip()
    if not text:
        raise ValueError("仓库地址不能为空")

    if text.startswith(("http://", "https://")):
        parsed = urlparse(text)
        detected = provider_for_host(parsed.hostname or "")
        if detected is None:
            raise ValueError("只支持 github.com 或 gitee.com 仓库地址")
        if provider and provider != detected:
            raise ValueError(f"仓库地址属于 {detected}，不是选择的平台 {provider}")
        provider = detected
        parts = [part for part in parsed.path.strip("/").split("/") if part]
    else:
        provider = provider or get_env("DEFAULT_REPO_PROVIDER", "gitee").strip().lower()
        if provider not in SUPPORTED_PROVIDERS:
            raise ValueError(f"当前不支持的仓库平台: {provider}")
        shorthand = text.removesuffix(".git").strip().strip("/")
        parts = [part for part in shorthand.split("/") if part]

    if len(parts) != 2:
        raise ValueError(f"无法解析仓库地址，请使用完整 HTTPS URL 或 owner/repo: {repo_url}")

    owner = parts[0]
    repo = re.sub(r"\.git$", "", parts[1], flags=re.IGNORECASE)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", owner) or not re.fullmatch(r"[A-Za-z0-9_.-]+", repo):
        raise ValueError(f"仓库 owner/repo 格式不正确: {repo_url}")

    host = _provider_host(provider)
    base = f"https://{host}/{owner}/{repo}"
    return Repository(provider=provider, owner=owner, repo=repo, clone_url=f"{base}.git", web_url=base)


def normalize_repo_url(repo_url: str, *, provider: str | None = None) -> str:
    return parse_repo_url(repo_url, provider=provider).clone_url


def get_provider_token(provider: str) -> str:
    names = {
        "github": ("GITHUB_TOKEN",),
        "gitee": ("GITEE_TOKEN", "SCM_GITEE_TOKEN"),
    }
    if provider not in names:
        raise RuntimeError(f"当前不支持的仓库平台: {provider}")
    for name in names[provider]:
        value = get_env(name).strip()
        if value:
            return value
    raise RuntimeError(f"缺少 {provider} 仓库访问令牌，请在本地 .env 配置")


def mask_tokens(text: str) -> str:
    masked = text
    for name in ("GITHUB_TOKEN", "GITEE_TOKEN", "SCM_GITEE_TOKEN"):
        token = get_env(name).strip()
        if token:
            masked = masked.replace(token, "***")
    return masked


def project_dir(repo: Repository) -> str:
    """为平台、owner、repo 建立隔离的本地目录，避免同名仓库互相覆盖。"""

    # 保留既有 Gitee 工作区目录，避免升级后破坏已有本地记忆和 checkout。
    if repo.provider == "gitee":
        return f"projects/{repo.repo}"
    safe_provider = re.sub(r"[^A-Za-z0-9_.-]+", "-", repo.provider)
    safe_owner = re.sub(r"[^A-Za-z0-9_.-]+", "-", repo.owner)
    safe_repo = re.sub(r"[^A-Za-z0-9_.-]+", "-", repo.repo)
    return f"projects/{safe_provider}-{safe_owner}-{safe_repo}"
