from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from agent.sandbox.opensandbox_executor import (
    OpenSandboxConfig,
    OpenSandboxExecutor,
    collect_safe_workspace_files,
    sandbox_health,
)


def test_collect_safe_workspace_files_excludes_credentials_and_runtime_state(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / ".git").mkdir()
    (tmp_path / ".venv").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('ok')", encoding="utf-8")
    (tmp_path / ".env").write_text("PASSWORD=secret", encoding="utf-8")
    (tmp_path / "store.sqlite").write_bytes(b"sqlite")
    (tmp_path / ".git" / "config").write_text("token", encoding="utf-8")
    (tmp_path / ".venv" / "python.exe").write_bytes(b"binary")

    files = collect_safe_workspace_files(tmp_path)

    assert [item.path for item in files] == ["src/main.py"]
    assert files[0].data == b"print('ok')"


def test_collect_safe_workspace_files_rejects_large_files(tmp_path: Path) -> None:
    (tmp_path / "large.txt").write_bytes(b"x" * 10)

    assert collect_safe_workspace_files(tmp_path, max_file_bytes=5) == []


def test_config_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPEN_SANDBOX_DOMAIN", "http://192.168.11.128:8080/")
    monkeypatch.setenv("OPEN_SANDBOX_IMAGE", "python:3.12")
    monkeypatch.setenv("OPEN_SANDBOX_TIMEOUT_SECONDS", "42")

    config = OpenSandboxConfig.from_env()

    assert config.domain == "http://192.168.11.128:8080"
    assert config.image == "python:3.12"
    assert config.timeout_seconds == 42


def test_sandbox_health_reports_connection_error_without_raising() -> None:
    result = sandbox_health("http://127.0.0.1:1", timeout_seconds=0.1)

    assert result["ok"] is False
    assert result["status_code"] is None


def test_sync_executor_reuses_event_loop_for_one_lifecycle() -> None:
    executor = OpenSandboxExecutor(OpenSandboxConfig(domain="http://sandbox.test"))
    loop_ids: list[int] = []

    async def record_loop() -> None:
        loop_ids.append(id(asyncio.get_running_loop()))

    try:
        executor._run_sync(record_loop())
        executor._run_sync(record_loop())
    finally:
        executor.close()

    assert len(loop_ids) == 2
    assert loop_ids[0] == loop_ids[1]
    assert executor._sync_loop is None
