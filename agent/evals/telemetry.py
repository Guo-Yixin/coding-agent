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


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        redacted = _SECRET_RE.sub(r"\1\2[REDACTED]", value)
        for key, secret in os.environ.items():
            if any(marker in key.upper() for marker in ("API_KEY", "_TOKEN", "_SECRET", "_PASSWORD", "_DSN")) and secret:
                redacted = redacted.replace(secret, "[REDACTED]")
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
