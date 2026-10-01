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


def test_compound_identifiers_are_not_split_by_a_secret_value(monkeypatch) -> None:
    """下划线属于标识符字符：``postgres_user`` 不应变成 ``[REDACTED]_user``。"""

    monkeypatch.setenv("POSTGRES_PASSWORD", "postgres")
    payload = {"repo_path": "/work/postgres_backup", "id": "postgres_user"}

    assert telemetry._redact(payload) == payload


def test_values_shorter_than_the_threshold_are_plain_configuration(monkeypatch) -> None:
    """契约：短于 ``_ENV_SECRET_MIN_LENGTH`` 的取值不是密钥材料，任何形式都不替换。

    包含 JSON 的引号形式——``_SECRET_RE`` 要求标记名后紧跟 ``=`` 或 ``:``，
    引号挡在中间时匹配不到，因此 ``{"password": "s3cr3t"}`` 保持原样。只有
    无引号的 ``password=s3cr3t`` 才会被 ``_SECRET_RE`` 拦截。
    """

    monkeypatch.setenv("REVIEW_PASSWORD", "s3cr3t")
    payload = {"password": "s3cr3t"}

    assert telemetry._redact(payload) == payload
    assert telemetry._redact('{"password": "s3cr3t"}') == '{"password": "s3cr3t"}'
    assert telemetry._redact("password=s3cr3t") == "password=[REDACTED]"


def test_long_environment_secret_is_redacted_inside_nested_payloads(monkeypatch) -> None:
    """对照：达到阈值的密钥在字典取值与 JSON 字符串里都仍然被脱敏。"""

    dsn = "postgresql://eval:sup3rsecret@127.0.0.1:5432/eval_db"
    monkeypatch.setenv("POSTGRES_DSN", dsn)
    embedded = json.dumps({"dsn": dsn})

    redacted = telemetry._redact({"payload": {"content": embedded}})

    assert dsn in embedded
    assert redacted["payload"]["content"] == '{"dsn": "[REDACTED]"}'


def test_name_value_secret_pattern_is_still_masked() -> None:
    assert telemetry._redact("token=abc123def456") == "token=[REDACTED]"
