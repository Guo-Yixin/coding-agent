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
#
# 契约：短于该长度的取值一律按普通配置处理，任何形式都不替换——包括 JSON 的
# 引号形式。{"password": "s3cr3t"} 不会被 _SECRET_RE 拦截，因为该正则要求标记名
# 后面紧跟 = 或 :，引号挡在中间时匹配不到；具名短密钥只有写成 password=s3cr3t
# 这种无引号形式才会被替换。
_ENV_SECRET_MIN_LENGTH = 8
# 取值替换的边界：出现在标识符字符内部时一律不替换，所以 postgres 不会把
# postgresql 或 postgres_user 切成 [REDACTED]。下划线属于标识符字符，连字符不是
# ——它在路径和命令行里是分隔符，仍算合法边界。
_IDENTIFIER_CHAR = r"[A-Za-z0-9_]"


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
    """只替换作为完整标识符出现的密钥取值。"""

    secrets = _environment_secrets()
    if not secrets:
        return text
    alternation = "|".join(re.escape(secret) for secret in secrets)
    return re.sub(rf"(?<!{_IDENTIFIER_CHAR})(?:{alternation})(?!{_IDENTIFIER_CHAR})", "[REDACTED]", text)


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
