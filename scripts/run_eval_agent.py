from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any


def _write_json(path_value: str, payload: Any) -> None:
    path = Path(path_value).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _usage_from_messages(messages: list[Any], intent_usage: list[dict[str, Any]]) -> dict[str, int] | dict[str, Any]:
    totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    seen = False
    seen_ids: set[str] = set()
    for message in messages:
        message_id = str(message.get("id", "") if isinstance(message, dict) else getattr(message, "id", "") or "")
        if message_id and message_id in seen_ids:
            continue
        if message_id:
            seen_ids.add(message_id)
        usage = message.get("usage_metadata") if isinstance(message, dict) else getattr(message, "usage_metadata", None)
        if not isinstance(usage, dict):
            response_metadata = message.get("response_metadata") if isinstance(message, dict) else getattr(message, "response_metadata", None)
            usage = response_metadata.get("token_usage") if isinstance(response_metadata, dict) else None
        if not isinstance(usage, dict):
            continue
        input_tokens = usage.get("input_tokens", usage.get("prompt_tokens"))
        output_tokens = usage.get("output_tokens", usage.get("completion_tokens"))
        total_tokens = usage.get("total_tokens")
        if input_tokens is None and output_tokens is None and total_tokens is None:
            continue
        seen = True
        totals["input_tokens"] += int(input_tokens or 0)
        totals["output_tokens"] += int(output_tokens or 0)
        totals["total_tokens"] += int(total_tokens if total_tokens is not None else (input_tokens or 0) + (output_tokens or 0))
    for usage in intent_usage:
        input_tokens = usage.get("input_tokens", usage.get("prompt_tokens"))
        output_tokens = usage.get("output_tokens", usage.get("completion_tokens"))
        total_tokens = usage.get("total_tokens")
        if input_tokens is None and output_tokens is None and total_tokens is None:
            return {"input_tokens": None, "output_tokens": None, "total_tokens": None, "unavailable_reason": "provider SDK did not expose usage for every intent-classification call"}
        seen = True
        totals["input_tokens"] += int(input_tokens or 0)
        totals["output_tokens"] += int(output_tokens or 0)
        totals["total_tokens"] += int(total_tokens if total_tokens is not None else (input_tokens or 0) + (output_tokens or 0))
    return totals if seen else {"input_tokens": None, "output_tokens": None, "total_tokens": None, "unavailable_reason": "provider SDK did not expose usage_metadata on returned messages"}


def _message_text(messages: list[Any]) -> str:
    chunks: list[str] = []
    for message in messages:
        message_type = message.get("type", "") if isinstance(message, dict) else getattr(message, "type", "")
        if str(message_type).lower() not in {"ai", "aimessage", "assistant"}:
            continue
        content = message.get("content", "") if isinstance(message, dict) else getattr(message, "content", "")
        if isinstance(content, str):
            chunks.append(content)
        elif isinstance(content, list):
            chunks.extend(str(item.get("text", "")) for item in content if isinstance(item, dict) and item.get("text"))
    return "\n\n".join(item for item in chunks if item)


def _sanitize_text(value: str) -> str:
    import re

    value = re.sub(r"(?i)(api[_-]?key|token|password|secret)(\s*[=:]\s*)([^\s,;]+)", r"\1\2[REDACTED]", value)
    for key, secret in os.environ.items():
        if any(marker in key.upper() for marker in ("API_KEY", "_TOKEN", "_SECRET", "_PASSWORD", "_DSN")) and secret:
            value = value.replace(secret, "[REDACTED]")
    return value


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    if os.environ.get("CODING_AGENT_EVAL_MODE") != "1":
        raise RuntimeError("This adapter may only run inside an isolated Agent Eval child process")
    source_root = Path(os.environ["EVAL_AGENT_SOURCE_ROOT"]).expanduser().resolve()
    sys.path.insert(0, str(source_root))
    config_path = Path(os.environ["EVAL_CASE_CONFIG"]).expanduser().resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))

    from agent.core.runtime import run_agent_task
    from agent.evals.telemetry import record_eval_event
    from agent.env_utils import get_env
    from agent.repository import parse_repo_url

    repo_url = str(config.get("metadata", {}).get("repo_url") or "").strip()
    if not repo_url:
        # The runner resolves this from origin before copying the target snapshot.
        repo_url = str(os.environ.get("EVAL_REPO_URL", "")).strip()
    if not repo_url:
        raise RuntimeError("No repository URL was provided to the real Agent adapter")
    parse_repo_url(repo_url)

    def event_sink(event_type: str, payload: dict[str, Any]) -> None:
        record_eval_event("runtime:" + str(event_type), payload)

    thread_id = "eval-" + str(config["case_id"])
    results = [run_agent_task(
        repo_url=repo_url,
        prompt=str(config.get("prompt", "")),
        thread_id=thread_id,
        event_sink=event_sink,
        model_id=None,
    )]
    plan_id = results[0].get("plan_id") if isinstance(results[0], dict) else None
    if plan_id and config.get("metadata", {}).get("auto_approve_plan") is True:
        results.append(run_agent_task(
            repo_url=repo_url,
            prompt="确认实施",
            thread_id=thread_id,
            event_sink=event_sink,
            interaction_action="approve_plan",
            plan_id=str(plan_id),
            model_id=None,
        ))
    result = results[-1]
    messages = [message for item in results for message in (item.get("messages", []) if isinstance(item, dict) else [])]
    trace_path = Path(os.environ["EVAL_EVENT_FILE"]).expanduser().resolve()
    trace_events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines() if line.strip()] if trace_path.exists() else []
    intent_usage = [event.get("payload", {}) for event in trace_events if event.get("type") == "intent_model_usage"]
    usage = _usage_from_messages(messages, intent_usage)
    if not _message_text(messages) and trace_events:
        latest_text: dict[str, str] = {}
        for event in trace_events:
            payload = event.get("payload", {})
            if event.get("type") == "runtime:text_delta":
                key = str(payload.get("assistant_index") or payload.get("message_id") or "")
                if key:
                    latest_text[key] = str(payload.get("content") or "")
        output_text = "\n\n".join(latest_text[key] for key in sorted(latest_text, key=lambda value: int(value) if value.isdigit() else value) if latest_text[key])
    else:
        output_text = _message_text(messages)
    _write_json(os.environ["EVAL_USAGE_FILE"], usage)
    _write_json(os.environ["EVAL_RESULT_FILE"], {
        "status": result.get("status") if isinstance(result, dict) else None,
        "model_provider": "DeepSeek",
        "model_name": get_env("MAIN_MODEL", "configured-default"),
        "thread_id": result.get("thread_id") if isinstance(result, dict) else None,
        "run_id": result.get("run_id") if isinstance(result, dict) else None,
        "run_statuses": [item.get("status") for item in results if isinstance(item, dict)],
        "plan_approval_performed": bool(plan_id and len(results) > 1),
        "output": _sanitize_text(output_text),
    })
    print(_sanitize_text(output_text))
    print(json.dumps({"status": result.get("status"), "model_provider": "DeepSeek", "model_name": get_env("MAIN_MODEL", "configured-default"), "usage": usage}, ensure_ascii=False))
    return 0 if result.get("status") in {"completed", "awaiting_approval"} else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        error_path = os.environ.get("EVAL_RESULT_FILE")
        if error_path:
            _write_json(error_path, {"status": "error", "error": _sanitize_text(str(exc))[:2000]})
        traceback.print_exc(file=sys.stderr)
        raise
