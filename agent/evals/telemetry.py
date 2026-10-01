from __future__ import annotations

import json
import os
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()
_SECRET_RE = re.compile(r"(?i)(api[_-]?key|token|password|secret)(\s*[=:]\s*)([^\s,;]+)")
_ENV_SECRET_MARKERS = ("API_KEY", "_TOKEN", "_SECRET", "_PASSWORD", "_DSN")
# 变量名命中标记不代表取值就是密钥材料：仓库里允许 X_API_KEY_HELPER_DISABLED=1
# 这类布尔开关存在。取值过短时（0/1/true/no）把它当密钥做子串替换，除了会改写
# payload 里的无关内容，还会先把文本改掉，让后面真正的长密钥再也匹配不上。
_ENV_SECRET_MIN_LENGTH = 8


def _environment_secrets() -> tuple[str, ...]:
    """收集需要脱敏的环境变量取值，长取值排在前，保证优先匹配更长的密钥。"""

    secrets = {
        value
        for key, value in os.environ.items()
        if len(value) >= _ENV_SECRET_MIN_LENGTH
        and any(marker in key.upper() for marker in _ENV_SECRET_MARKERS)
    }
    return tuple(sorted(secrets, key=len, reverse=True))


def _redact_environment_secrets(text: str) -> str:
    """只替换独立出现的密钥取值，不改写更长 token 的内部片段。"""

    secrets = _environment_secrets()
    if not secrets:
        return text
    alternation = "|".join(re.escape(secret) for secret in secrets)
    return re.sub(rf"(?<![A-Za-z0-9])(?:{alternation})(?![A-Za-z0-9])", "[REDACTED]", text)


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        redacted = _SECRET_RE.sub(r"\1\2[REDACTED]", value)
        redacted = _redact_environment_secrets(redacted)
        return redacted[:8000]
    if isinstance(value, dict):
        return {str(key): _redact(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _redact(str(value))


def record_eval_event(event_type: str, payload: dict[str, Any] | None = None) -> None:
    """Append a redacted structured event only inside an Eval child process."""
    if os.environ.get("CODING_AGENT_EVAL_MODE", "").strip() != "1":
        return
    target = os.environ.get("EVAL_EVENT_FILE", "").strip()
    if not target:
        return
    event = {
        "timestamp": datetime.now(UTC).isoformat(),
        "type": event_type,
        "payload": _redact(payload or {}),
    }
    path = Path(target).expanduser().resolve()
    with _LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
