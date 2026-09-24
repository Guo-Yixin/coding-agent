from __future__ import annotations

import pytest

from agent.repository import normalize_repo_url, parse_repo_url, project_dir


def test_parse_github_https_repo() -> None:
    repo = parse_repo_url("https://github.com/Guo-Yixin/test-coding-repo.git")

    assert repo.provider == "github"
    assert repo.owner == "Guo-Yixin"
    assert repo.repo == "test-coding-repo"
    assert repo.clone_url == "https://github.com/Guo-Yixin/test-coding-repo.git"
    assert repo.web_url == "https://github.com/Guo-Yixin/test-coding-repo"
    assert project_dir(repo) == "projects/github-Guo-Yixin-test-coding-repo"


def test_parse_shorthand_uses_selected_provider() -> None:
    repo = parse_repo_url("owner/repo", provider="gitee")

    assert repo.provider == "gitee"
    assert repo.clone_url == "https://gitee.com/owner/repo.git"
    assert project_dir(repo) == "projects/repo"


def test_full_url_cannot_conflict_with_selected_provider() -> None:
    with pytest.raises(ValueError, match="不是选择的平台"):
        parse_repo_url("https://github.com/owner/repo", provider="gitee")


def test_normalize_repo_url_removes_git_suffix_consistently() -> None:
    assert normalize_repo_url("owner/repo", provider="github") == "https://github.com/owner/repo.git"
