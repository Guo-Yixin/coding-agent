from __future__ import annotations

from agent.tools import github_api


class _FakeResponse:
    status_code = 200
    content = b'{"ok": true}'
    text = '{"ok": true}'

    @staticmethod
    def json() -> dict[str, bool]:
        return {"ok": True}


class _FakeClient:
    last_headers: dict[str, str] | None = None
    last_request: tuple[str, str] | None = None

    def __init__(self, *, timeout: int, headers: dict[str, str]) -> None:
        self.last_headers = headers
        type(self).last_headers = headers

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def request(self, method: str, url: str, **kwargs: object) -> _FakeResponse:
        type(self).last_request = (method, url)
        return _FakeResponse()


def test_github_request_uses_bearer_token_without_url_credentials(monkeypatch) -> None:
    monkeypatch.setattr(github_api.httpx, "Client", _FakeClient)
    monkeypatch.setattr(github_api, "get_github_token", lambda: "secret-token")
    monkeypatch.setenv("GITHUB_API_BASE_URL", "https://api.github.com")

    result = github_api.get_repository(owner="Guo-Yixin", repo="test-coding-repo")

    assert result == {"ok": True}
    assert _FakeClient.last_headers["Authorization"] == "Bearer secret-token"
    assert _FakeClient.last_request == ("GET", "https://api.github.com/repos/Guo-Yixin/test-coding-repo")
    assert "secret-token" not in _FakeClient.last_request[1]


def test_create_pull_request_uses_repository_default_branch(monkeypatch) -> None:
    calls: list[tuple[str, str, dict]] = []

    def fake_request(method: str, path: str, **kwargs: object) -> dict:
        calls.append((method, path, kwargs))
        if method == "GET":
            return {"default_branch": "main"}
        return {"html_url": "https://github.com/Guo-Yixin/test-coding-repo/pull/1"}

    monkeypatch.setattr(github_api, "_github_request", fake_request)

    result = github_api.create_pull_request(
        owner="Guo-Yixin",
        repo="test-coding-repo",
        head="codex/test",
        base=None,
        title="Test",
        body="Body",
    )

    assert result["html_url"].endswith("/pull/1")
    assert calls[0][0:2] == ("GET", "/repos/Guo-Yixin/test-coding-repo")
    assert calls[1][2]["json"] == {
        "title": "Test",
        "head": "codex/test",
        "base": "main",
        "body": "Body",
        "draft": False,
    }
