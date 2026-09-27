from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any
from uuid import uuid4


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


def _usage_from_callback_calls(calls: list[dict[str, Any]]) -> dict[str, int] | dict[str, Any]:
    totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    if not calls:
        return {"input_tokens": None, "output_tokens": None, "total_tokens": None, "unavailable_reason": "model callbacks did not expose token usage"}
    for usage in calls:
        input_tokens = usage.get("input_tokens", usage.get("prompt_tokens"))
        output_tokens = usage.get("output_tokens", usage.get("completion_tokens"))
        total_tokens = usage.get("total_tokens")
        if input_tokens is None and output_tokens is None and total_tokens is None:
            return {"input_tokens": None, "output_tokens": None, "total_tokens": None, "unavailable_reason": "provider did not expose usage for every model call"}
        totals["input_tokens"] += int(input_tokens or 0)
        totals["output_tokens"] += int(output_tokens or 0)
        totals["total_tokens"] += int(total_tokens if total_tokens is not None else (input_tokens or 0) + (output_tokens or 0))
    return totals


def _install_usage_callbacks(record_eval_event):
    """Ask the OpenAI-compatible stream for usage and collect per-call totals."""

    from langchain_core.callbacks import BaseCallbackHandler

    calls: list[dict[str, Any]] = []

    class EvalUsageCallback(BaseCallbackHandler):
        def on_llm_end(self, response, **kwargs):
            usage = getattr(response, "llm_output", None) or {}
            usage = usage.get("token_usage") or usage.get("usage") or {}
            if not usage:
                generations = getattr(response, "generations", []) or []
                for group in generations:
                    for generation in group or []:
                        message = getattr(generation, "message", None)
                        usage = getattr(message, "usage_metadata", None) or {}
                        if usage:
                            break
                    if usage:
                        break
            normalized = {
                "input_tokens": usage.get("input_tokens", usage.get("prompt_tokens")),
                "output_tokens": usage.get("output_tokens", usage.get("completion_tokens")),
                "total_tokens": usage.get("total_tokens"),
            }
            calls.append(normalized)
            if any(value is not None for value in normalized.values()):
                record_eval_event("model_usage", normalized)

    callback = EvalUsageCallback()

    def instrument_factory(owner, attribute: str) -> None:
        original = getattr(owner, attribute, None)
        if original is None or getattr(original, "_eval_usage_instrumented", False):
            return

        def create(*args, **kwargs):
            model = original(*args, **kwargs)
            # ChatOpenAI's stream_usage requests the usage chunk from compatible providers.
            model_fields = getattr(type(model), "model_fields", {})
            updates = {"callbacks": [callback]}
            if "stream_usage" in model_fields:
                updates["stream_usage"] = True
            if hasattr(model, "model_copy"):
                model = model.model_copy(update=updates)
            elif hasattr(model, "stream_usage"):
                try:
                    model.stream_usage = True
                    model.callbacks = [callback]
                except Exception:
                    pass
            return model

        create._eval_usage_instrumented = True
        setattr(owner, attribute, create)

    import importlib

    for module_name, attribute in (
        ("agent.server", "make_main_model"),
        ("agent.core.task_intent", "make_intent_model"),
    ):
        try:
            instrument_factory(importlib.import_module(module_name), attribute)
        except ImportError:
            continue
    return calls


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


def _load_eval_model_environment() -> None:
    """Load only model settings into the Agent child, never into test processes or reports."""

    env_file = os.environ.get("EVAL_ENV_FILE", "").strip()
    if not env_file:
        return
    from dotenv import dotenv_values

    allowed = {
        "MAIN_MODEL",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE_URL",
    }
    for key, value in dotenv_values(env_file).items():
        if key in allowed and value is not None and key not in os.environ:
            os.environ[key] = value


def _instrument_retrieval(record_eval_event, injection: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Add trace-only observation around the existing hybrid search tool."""

    import importlib
    from functools import wraps

    module = importlib.import_module("agent.retrieval.hybrid_search")
    original = module.hybrid_code_search
    if getattr(original, "_eval_instrumented", False):
        return []
    injection = injection if isinstance(injection, dict) else {}
    inject_tool = str(injection.get("tool") or "")
    inject_remaining = 1 if injection else 0
    pending_recovery: list[dict[str, Any]] = []

    @wraps(original)
    def traced(*args, **kwargs):
        nonlocal inject_remaining
        case_repo = os.environ.get("EVAL_CASE_REPO", "").strip()
        requested_repo = kwargs.get("repo_path", args[1] if len(args) > 1 else "")
        if case_repo:
            if "repo_path" in kwargs:
                kwargs["repo_path"] = case_repo
            elif len(args) > 1:
                args = (*args[:1], case_repo, *args[2:])
            record_eval_event(
                "workspace_binding",
                {"tool": "hybrid_code_search", "requested_repo": str(requested_repo), "bound_repo": case_repo},
            )
        query = kwargs.get("query", args[0] if args else "")
        if inject_remaining and inject_tool == "hybrid_code_search":
            inject_remaining -= 1
            failure = {
                "probe_id": uuid4().hex,
                "tool_name": inject_tool,
                "query": str(query)[:300],
                "recovered": False,
                "injected": True,
            }
            pending_recovery.append(failure)
            record_eval_event("tool_error", {**failure, "error_type": "TimeoutError"})
            raise TimeoutError(str(injection.get("message") or "Injected one-shot Eval timeout for tool recovery"))
        result = original(*args, **kwargs)
        payload = result if isinstance(result, dict) else {}
        record_eval_event(
            "retrieval",
            {
                "query": kwargs.get("query", args[0] if args else ""),
                "hits": payload.get("hits", []),
                "trace": payload.get("trace", {}),
            },
        )
        if pending_recovery:
            for failed in pending_recovery:
                if not failed["recovered"]:
                    failed["recovered"] = True
                    failed["recovery"] = "success"
                    failed["recovery_strategy"] = "retry_hybrid_code_search"
                    record_eval_event(
                        "tool_recovery",
                        {"probe_id": failed["probe_id"], "tool_name": failed["tool_name"],
                         "strategy": failed["recovery_strategy"], "success": True},
                    )
        return result

    traced._eval_instrumented = True
    module.hybrid_code_search = traced
    for module_name in ("agent.retrieval", "agent.tools", "agent.server"):
        try:
            owner = importlib.import_module(module_name)
        except ImportError:
            continue
        if hasattr(owner, "hybrid_code_search"):
            owner.hybrid_code_search = traced
    return pending_recovery


def _finalize_tool_trace(trace_path: Path) -> None:
    """Join raw tool lifecycle records by call id and annotate later recovery evidence."""

    if not trace_path.is_file():
        return
    events = []
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    names = {
        str(event.get("payload", {}).get("tool_call_id")): event.get("payload", {}).get("tool_name")
        for event in events
        if event.get("type") == "tool_call" and event.get("payload", {}).get("tool_call_id")
    }
    for event in events:
        payload = event.get("payload", {})
        call_id = str(payload.get("tool_call_id") or "")
        if call_id and not payload.get("tool_name") and names.get(call_id):
            payload["tool_name"] = names[call_id]
    successful_recoveries = {
        str((event.get("payload") or {}).get("probe_id"))
        for event in events
        if event.get("type") == "tool_recovery"
        and (event.get("payload") or {}).get("success") is True
    }
    recoveries: list[dict[str, Any]] = []
    fallback_tools = {"hybrid_code_search", "read_file", "execute", "grep", "ls", "glob"}
    for index, event in enumerate(events):
        payload = event.get("payload", {})
        probe_id = str(payload.get("probe_id") or "")
        if event.get("type") != "tool_error" or payload.get("injected") is not True or not probe_id:
            continue
        if probe_id in successful_recoveries:
            payload["recovered"] = True
            payload["recovery"] = "success"
            continue
        for later in events[index + 1:]:
            later_payload = later.get("payload", {})
            if (
                later.get("type") == "tool_result"
                and later_payload.get("tool_name") in fallback_tools
                and later_payload.get("status") != "error"
                and later_payload.get("failed") is not True
            ):
                payload["recovered"] = True
                payload["recovery"] = "success"
                payload["recovery_strategy"] = f"fallback_{later_payload.get('tool_name')}"
                recoveries.append({
                    "timestamp": later.get("timestamp"),
                    "type": "tool_recovery",
                    "payload": {
                        "probe_id": probe_id,
                        "tool_name": payload.get("tool_name"),
                        "strategy": payload["recovery_strategy"],
                        "success": True,
                    },
                })
                break
    events.extend(recoveries)
    for index, event in enumerate(events):
        payload = event.get("payload", {})
        if event.get("type") not in {"tool_error", "tool_failed"} or not payload.get("tool_name"):
            continue
        tool_name = payload["tool_name"]
        recovered = any(
            later.get("type") == "tool_result" and later.get("payload", {}).get("tool_name") == tool_name
            for later in events[index + 1:]
        )
        if recovered:
            payload["recovered"] = True
            payload["recovery"] = "success"
    trace_path.write_text(
        "".join(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )


def _record_tool_messages(messages: list[Any], record_eval_event) -> None:
    for message in messages:
        message_type = message.get("type", "") if isinstance(message, dict) else getattr(message, "type", "")
        if str(message_type).lower() in {"ai", "aimessage", "assistant"}:
            calls = message.get("tool_calls", []) if isinstance(message, dict) else getattr(message, "tool_calls", [])
            for call in calls or []:
                if isinstance(call, dict):
                    call_id = call.get("id") or call.get("tool_call_id")
                    name = call.get("name") or call.get("tool_name")
                else:
                    call_id = getattr(call, "id", None)
                    name = getattr(call, "name", None)
                record_eval_event("tool_call", {"tool_call_id": call_id, "tool_name": name})
        elif str(message_type).lower() in {"tool", "toolmessage"}:
            call_id = message.get("tool_call_id") if isinstance(message, dict) else getattr(message, "tool_call_id", None)
            status = message.get("status") if isinstance(message, dict) else getattr(message, "status", None)
            name = message.get("name") if isinstance(message, dict) else getattr(message, "name", None)
            content = message.get("content") if isinstance(message, dict) else getattr(message, "content", None)
            kind = "tool_error" if status == "error" else "tool_result"
            record_eval_event(
                kind,
                {"tool_call_id": call_id, "tool_name": name, "status": status,
                 "content": str(content or "")[:1000]},
            )


def _instrument_runtime_events(record_eval_event) -> None:
    """Capture tool lifecycle events from the Agent's real stream parser."""

    import agent.core.streaming_runtime as streaming_runtime

    original = streaming_runtime._tool_event_from_raw
    if getattr(original, "_eval_instrumented", False):
        return

    def traced(event):
        payload = original(event)
        if isinstance(payload, dict):
            name = payload.get("name") or payload.get("tool_name")
            phase = payload.get("event") or payload.get("status") or "event"
            phase_text = str(phase).lower().replace("-", "_")
            event_type = (
                "tool_call" if phase_text in {"tool_started", "started", "start"}
                else "tool_error" if phase_text in {"tool_error", "error", "failed"}
                else "tool_result" if phase_text in {"tool_finished", "finished", "completed", "success"}
                else "tool_event"
            )
            record_eval_event(
                event_type,
                {
                    "tool_name": name,
                    "tool_call_id": payload.get("id") or payload.get("tool_call_id"),
                    "status": payload.get("status"),
                    "error": str(payload.get("error") or "")[:500] or None,
                },
            )
        return payload

    traced._eval_instrumented = True
    streaming_runtime._tool_event_from_raw = traced


def _install_eval_safety(repo_url: str) -> None:
    """Keep a pinned Eval checkout local and disable repository-changing actions."""

    import re
    import agent.core.repository_workspace as repository_workspace
    import agent.server as server
    from agent.backends.local_shell import LocalShellBackend
    from agent.core.repo_memory import repo_project_dir
    from agent.repository import parse_repo_url

    expected_repo = parse_repo_url(repo_url)

    def prepare_pinned_workspace(repo, backend, *, thread_id=None, create_task_branch=False):
        directory = repo_project_dir(repo).replace("\\", "/")
        target = backend.workspace.resolve(directory)
        if not target.is_dir():
            raise RuntimeError(f"Eval repository snapshot is missing: {directory}")
        remote_result = backend.run("git remote get-url origin", cwd=directory)
        actual_url = str(getattr(remote_result, "stdout", "")).strip()
        actual_repo = parse_repo_url(actual_url)
        if (actual_repo.provider, actual_repo.owner.lower(), actual_repo.repo.lower()) != (
            expected_repo.provider,
            expected_repo.owner.lower(),
            expected_repo.repo.lower(),
        ):
            raise RuntimeError("Eval workspace origin does not match the declared task repository")
        branch_result = backend.run("git branch --show-current", cwd=directory)
        branch = str(getattr(branch_result, "stdout", "")).strip() or "eval-baseline"
        return repository_workspace.PreparedRepositoryWorkspace(directory, branch, branch)

    repository_workspace.prepare_repository_workspace = prepare_pinned_workspace

    blocked_tools = {
        "open_gitee_pull_request",
        "publish_gitee_pr_comment",
        "create_gitee_issue",
        "publish_gitee_issue_comment",
        "open_github_pull_request",
        "publish_github_pr_comment",
        "create_github_issue",
        "publish_github_issue_comment",
        "rerun_github_actions",
        "cancel_github_actions",
    }
    original_create = server.create_deep_agent

    def create_eval_agent(*args, **kwargs):
        tools = kwargs.get("tools")
        if tools is not None:
            kwargs["tools"] = [
                tool for tool in tools
                if str(getattr(tool, "name", getattr(tool, "__name__", ""))) not in blocked_tools
            ]
        return original_create(*args, **kwargs)

    server.create_deep_agent = create_eval_agent

    original_run = LocalShellBackend.run
    original_execute = LocalShellBackend.execute

    def guarded_run(self, command, cwd=".", timeout=300):
        if _blocks_eval_git_write(str(command)):
            raise PermissionError("Agent Eval blocks Git write and remote-sync commands")
        return original_run(self, command, cwd=cwd, timeout=timeout)

    def guarded_execute(self, command, *, timeout=None):
        if _blocks_eval_git_write(str(command)):
            raise PermissionError("Agent Eval blocks Git write and remote-sync commands")
        return original_execute(self, command, timeout=timeout)

    LocalShellBackend.run = guarded_run
    LocalShellBackend.execute = guarded_execute


def _blocks_eval_git_write(command: str) -> bool:
    """Conservatively reject repository-changing Git commands, including `git -C` forms."""

    import re

    forbidden = re.compile(
        r"(?i)\b(push|commit|fetch|pull|reset|clean|worktree|merge|rebase|tag|config|"
        r"checkout|switch|cherry-pick|revert|stash|am|apply)\b"
    )
    for match in re.finditer(r"(?i)\bgit(?:\.exe)?\b", command):
        tail = re.split(r"&&|\|\||[;|\r\n]", command[match.end():], maxsplit=1)[0]
        if forbidden.search(tail):
            return True
        remote = re.search(r"(?i)\bremote\b(?:\s+([^\s]+))?", tail)
        if remote and remote.group(1) and remote.group(1).lower() not in {"get-url", "show", "-v", "--verbose"}:
            return True
        branch = re.search(r"(?i)\bbranch\b(.*)$", tail)
        if branch:
            options = set(re.findall(r"--?[A-Za-z-]+", branch.group(1)))
            read_only = {"-a", "-r", "-v", "-vv", "--all", "--remotes", "--verbose", "--list", "-l", "--show-current", "--contains", "--merged", "--no-merged"}
            operands = [word for word in re.split(r"\s+", branch.group(1).strip()) if word and not word.startswith("-")]
            if operands or options - read_only:
                return True
    return False


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    if os.environ.get("CODING_AGENT_EVAL_MODE") != "1":
        raise RuntimeError("This adapter may only run inside an isolated Agent Eval child process")
    source_root = Path(os.environ["EVAL_AGENT_SOURCE_ROOT"]).expanduser().resolve()
    sys.path.insert(0, str(source_root))
    _load_eval_model_environment()
    config_path = Path(os.environ["EVAL_CASE_CONFIG"]).expanduser().resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))

    from agent.evals.telemetry import record_eval_event
    from agent.env_utils import get_env
    from agent.repository import parse_repo_url

    injected_tool_failures = _instrument_retrieval(
        record_eval_event,
        config.get("metadata", {}).get("inject_tool_error_once"),
    )
    _instrument_runtime_events(record_eval_event)
    usage_calls = _install_usage_callbacks(record_eval_event)
    repo_url = str(config.get("metadata", {}).get("repo_url") or "").strip()
    if not repo_url:
        repo_url = str(os.environ.get("EVAL_REPO_URL", "")).strip()
    if not repo_url:
        raise RuntimeError("No repository URL was provided to the real Agent adapter")
    parse_repo_url(repo_url)
    _install_eval_safety(repo_url)
    from agent.core.runtime import run_agent_task
    from agent.core.graph import get_store

    def event_sink(event_type: str, payload: dict[str, Any]) -> None:
        record_eval_event("runtime:" + str(event_type), payload)

    thread_id = "eval-" + str(config["case_id"])
    plan_id = None
    plan_text = ""
    plan_pending_before_approval = False
    workspace_clean_before_approval = False
    results = [run_agent_task(
        repo_url=repo_url,
        prompt=str(config.get("prompt", "")),
        thread_id=thread_id,
        event_sink=event_sink,
        model_id=None,
    )]
    plan_id = results[0].get("plan_id") if isinstance(results[0], dict) else None
    pending_plan = None
    if config.get("metadata", {}).get("auto_approve_plan") is True:
        pending_plan = get_store().get_latest_thread_plan(thread_id, status="pending")
        if isinstance(pending_plan, dict):
            plan_id = plan_id or pending_plan.get("plan_id")
            plan_text = str(pending_plan.get("plan_text") or "")
            plan_pending_before_approval = pending_plan.get("status") == "pending"
            import subprocess

            workspace_status = subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=all"],
                cwd=Path(os.environ["EVAL_CASE_REPO"]).resolve(),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            workspace_clean_before_approval = workspace_status.returncode == 0 and not workspace_status.stdout.strip()
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
    _record_tool_messages(messages, record_eval_event)
    trace_path = Path(os.environ["EVAL_EVENT_FILE"]).expanduser().resolve()
    _finalize_tool_trace(trace_path)
    trace_events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines() if line.strip()] if trace_path.exists() else []
    intent_usage = [event.get("payload", {}) for event in trace_events if event.get("type") == "intent_model_usage"]
    usage = _usage_from_callback_calls(usage_calls)
    if usage.get("total_tokens") is None:
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
        "plan_pending_before_approval": plan_pending_before_approval,
        "workspace_clean_before_approval": workspace_clean_before_approval,
        "plan_text": _sanitize_text(plan_text),
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
