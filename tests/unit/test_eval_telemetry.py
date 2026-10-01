from __future__ import annotations

import json
from pathlib import Path

from agent.evals import telemetry


def test_short_config_flag_is_not_treated_as_a_secret(monkeypatch) -> None:
    """变量名命中 ``API_KEY`` 不代表取值是密钥材料。

    仓库允许 ``X_API_KEY_HELPER_DISABLED=1`` 这类布尔开关存在。把这种短取值
    当成密钥做全局子串替换，会连同 payload 里任意同名片段一起改写。
    """

    monkeypatch.setenv("CODING_AGENT_API_KEY_HELPER_DISABLED", "1")
    payload = {"repo_path": "C:/work/pytest-201/projects/target-repo", "attempt": "1"}

    assert telemetry._redact(payload) == payload


def test_recorded_event_keeps_workspace_path_intact(tmp_path: Path, monkeypatch) -> None:
    """回归：evals 事件里的工作区路径不能被环境开关改写。"""

    monkeypatch.setenv("CODING_AGENT_EVAL_MODE", "1")
    monkeypatch.setenv("CODING_AGENT_API_KEY_HELPER_DISABLED", "1")
    monkeypatch.setenv("EVAL_EVENT_FILE", str(tmp_path / "events.jsonl"))
    repo_path = "C:/work/pytest-201/projects/target-repo"

    telemetry.record_eval_event("workspace_binding", {"repo_path": repo_path})

    event = json.loads((tmp_path / "events.jsonl").read_text(encoding="utf-8").strip())
    assert event["payload"]["repo_path"] == repo_path


def test_environment_secret_is_still_redacted(monkeypatch) -> None:
    """真实密钥取值仍然必须被脱敏。"""

    dsn = "postgresql://eval:sup3rsecret@127.0.0.1:5432/eval_db"
    monkeypatch.setenv("POSTGRES_DSN", dsn)

    redacted = telemetry._redact({"connection": dsn, "note": f"connected via {dsn}"})

    assert dsn not in json.dumps(redacted)
    assert redacted == {"connection": "[REDACTED]", "note": "connected via [REDACTED]"}


def test_long_secret_is_redacted_without_corrupting_longer_tokens(monkeypatch) -> None:
    """只替换独立出现的取值：``postgres`` 不应改写 ``postgresql``。"""

    monkeypatch.setenv("POSTGRES_PASSWORD", "postgres")

    assert telemetry._redact("driver=postgresql host=db") == "driver=postgresql host=db"
    assert telemetry._redact("password is postgres") == "password is [REDACTED]"


def test_name_value_secret_pattern_is_still_masked() -> None:
    assert telemetry._redact("token=abc123def456") == "token=[REDACTED]"
