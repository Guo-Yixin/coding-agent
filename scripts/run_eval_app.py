from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any

import httpx

from scripts.run_eval_agent import (
    _finalize_tool_trace,
    _install_eval_safety,
    _install_usage_callbacks,
    _instrument_retrieval,
    _instrument_runtime_events,
    _load_eval_model_environment,
    _sanitize_text,
    _usage_from_callback_calls,
    _write_json,
)


def _sse_post(client: httpx.Client, url: str, payload: dict[str, Any], timeout: int) -> list[dict[str, Any]]:
    response = client.post(url, json=payload, timeout=timeout)
    response.raise_for_status()
    events: list[dict[str, Any]] = []
    current_event = "message"
    data_lines: list[str] = []

    def flush() -> None:
        nonlocal current_event, data_lines
        if data_lines:
            raw = "\n".join(data_lines)
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = {"text": raw}
            events.append({"event": current_event, "data": data})
        current_event, data_lines = "message", []

    for line in response.text.splitlines():
        if not line:
            flush()
        elif line.startswith("event:"):
            current_event = line.partition(":")[2].strip()
        elif line.startswith("data:"):
            data_lines.append(line.partition(":")[2].lstrip())
    flush()
    return events


def _submit_plan_decision(
    client: httpx.Client,
    thread_url: str,
    plan: dict[str, Any],
    decision: str,
    timeout: int,
) -> list[dict[str, Any]]:
    if decision == "reject":
        content, action = "我拒绝这个实施方案，请不要修改仓库。", "reject_plan"
    elif decision == "approve":
        content, action = "确认实施", "approve_plan"
    else:
        return []
    return _sse_post(
        client,
        thread_url + "/stream-message",
        {"content": content, "interaction_action": action, "plan_id": plan["plan_id"]},
        timeout,
    )


def _latest_plan(thread: dict[str, Any]) -> dict[str, Any] | None:
    value = thread.get("latestPlan") or thread.get("latest_plan")
    return value if isinstance(value, dict) else None


def _eval_backend_for_thread(thread_id: str):
    try:
        from agent.server import _BACKENDS

        return _BACKENDS.get(thread_id)
    except Exception:
        return None


def _close_eval_sandbox(thread_id: str) -> dict[str, Any] | None:
    backend = _eval_backend_for_thread(thread_id)
    try:
        from agent.sandbox.eval_backend import close_opensandbox_backends

        evidence = close_opensandbox_backends([backend]) if backend is not None else []
        return evidence[0] if evidence else None
    except Exception:
        return None


def _postgres_thread_snapshot(dsn: str, thread_id: str) -> dict[str, Any]:
    """Verify the app wrote this run to the expected disposable PostgreSQL database."""

    from psycopg import connect
    from psycopg.conninfo import conninfo_to_dict

    parsed = conninfo_to_dict(dsn)
    database = str(parsed.get("dbname") or "")
    host = str(parsed.get("host") or "")
    port = str(parsed.get("port") or "")
    identity_ok = host in {"127.0.0.1", "localhost"} and database.startswith("coding_agent_eval_")
    with connect(dsn, connect_timeout=5) as connection:
        current = connection.execute("SELECT current_database(), current_user").fetchone()
        identity_ok = identity_ok and current[0] == database and current[1] == "eval_runner"
        counts: dict[str, int] = {}
        for table in ("threads", "runs", "run_events", "thread_messages", "thread_plans"):
            counts[table] = int(
                connection.execute(
                    f"SELECT count(*) FROM {table} WHERE thread_id = %s", (thread_id,)
                ).fetchone()[0]
            )
        checkpoint_table = connection.execute("SELECT to_regclass('public.checkpoints')").fetchone()[0]
        checkpoint_count = 0
        if checkpoint_table:
            checkpoint_count = int(
                connection.execute(
                    "SELECT count(*) FROM checkpoints WHERE thread_id = %s", (thread_id,)
                ).fetchone()[0]
            )
    records_ok = (
        counts["threads"] >= 1
        and counts["runs"] >= 1
        and counts["run_events"] >= 1
        and counts["thread_messages"] >= 2
        and counts["thread_plans"] >= 1
        and checkpoint_count >= 1
    )
    return {
        "identity_verified": bool(identity_ok),
        "records_persisted": bool(records_ok),
        "database_name": database,
        "host": host,
        "port": port,
        "record_counts": counts,
        "checkpoint_count": checkpoint_count,
    }


def _postgres_reconnect_verified(
    thread_id: str,
    before_restart: dict[str, Any],
    restored_thread: dict[str, Any],
    after_restart: dict[str, Any],
) -> bool:
    """Check the public Thread DTO (whose key is `id`) after a backend restart."""

    restored_id = restored_thread.get("thread_id") or restored_thread.get("id")
    return bool(
        restored_id == thread_id
        and len(restored_thread.get("messages", [])) >= 2
        and restored_thread.get("status") == before_restart.get("status")
        and after_restart.get("records_persisted") is True
    )


def _thread_text(thread: dict[str, Any]) -> str:
    chunks: list[str] = []
    for message in thread.get("messages", []) if isinstance(thread.get("messages"), list) else []:
        for chunk in message.get("chunks", []) if isinstance(message, dict) else []:
            content = (chunk.get("content") or chunk.get("text") or chunk.get("plan_text")) if isinstance(chunk, dict) else None
            if isinstance(content, str):
                chunks.append(content)
    return "\n\n".join(item for item in chunks if item)


def _parse_sse_text(value: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    current_event = "message"
    data_lines: list[str] = []
    for line in value.splitlines() + [""]:
        if not line:
            if data_lines:
                raw = "\n".join(data_lines)
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    payload = {"text": raw}
                events.append({"event": current_event, "data": payload})
            current_event, data_lines = "message", []
        elif line.startswith("event:"):
            current_event = line.partition(":")[2].strip()
        elif line.startswith("data:"):
            data_lines.append(line.partition(":")[2].lstrip())
    return events


def _run_browser_task(source_root: Path, api_url: str, repo_url: str, prompt: str, run_dir: Path, workspace_dir: Path, timeout: int) -> dict[str, Any]:
    """Serve the pinned Vue sources and send/approve a task in Chromium."""

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Browser Eval requires the optional Playwright dependency") from exc
    node, npm = shutil.which("node"), shutil.which("npm")
    if not node or not npm:
        raise RuntimeError("Browser Eval requires Node.js and npm")
    npm_cli = Path(npm).parent / "node_modules" / "npm" / "bin" / "npm-cli.js"
    if not npm_cli.is_file():
        raise RuntimeError("Browser Eval could not locate npm-cli.js for the Node.js installation")

    ui_dir = run_dir / "ui-runtime"
    if ui_dir.exists():
        raise FileExistsError(f"Refusing to reuse browser UI workspace: {ui_dir}")
    shutil.copytree(source_root / "ui", ui_dir, ignore=shutil.ignore_patterns("node_modules", "dist", ".vite"))
    install = subprocess.run(
        [node, str(npm_cli), "exec", "--yes", "--package=yarn@1.22.22", "--", "yarn", "install", "--frozen-lockfile", "--non-interactive"],
        cwd=ui_dir, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=min(600, timeout), check=False, shell=False,
    )
    if install.returncode != 0:
        raise RuntimeError(f"Pinned frontend dependency install failed: {(install.stdout + install.stderr)[-1600:]}")
    vite = ui_dir / "node_modules" / "vite" / "bin" / "vite.js"
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        ui_port = int(probe.getsockname()[1])
    environment = os.environ.copy()
    environment["VITE_DASHBOARD_API_BASE_URL"] = api_url
    process = subprocess.Popen(
        [node, str(vite), "--host", "127.0.0.1", "--port", str(ui_port), "--strictPort"],
        cwd=ui_dir, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    try:
        import httpx

        ui_url = f"http://127.0.0.1:{ui_port}"
        ready_by = time.monotonic() + min(60, timeout)
        with httpx.Client() as client:
            while time.monotonic() < ready_by:
                if process.poll() is not None:
                    output = process.stdout.read() if process.stdout else ""
                    raise RuntimeError(f"Vite frontend exited before ready: {output[-1200:]}")
                try:
                    if client.get(ui_url, timeout=2).status_code == 200:
                        break
                except httpx.HTTPError:
                    time.sleep(0.25)
            else:
                raise RuntimeError("Vue frontend did not become ready")

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_default_timeout(timeout * 1000)
            try:
                page.goto(ui_url, wait_until="networkidle", timeout=60_000)
                page.get_by_label("仓库平台").select_option("github")
                page.get_by_label("GitHub 仓库地址").fill(repo_url)
                page.get_by_label("任务指令").fill(prompt)
                with page.expect_response(
                    lambda response: response.request.method == "POST" and response.url.endswith("/dashboard/api/threads/stream-message"),
                    timeout=timeout * 1000,
                ) as first_response:
                    page.get_by_role("button", name="发送").click()
                first_events = _parse_sse_text(first_response.value.text())
                thread_id = next((str(item["data"]["thread_id"]) for item in first_events if item.get("data", {}).get("thread_id")), "")
                if not thread_id:
                    raise RuntimeError("Browser task stream omitted the persisted thread ID")
                pending = page.locator(".proposal-status-pending")
                pending.wait_for(state="visible")
                plan_text = page.locator(".proposal-card-content").inner_text()
                pending_plan_displayed = "待你确认" in pending.inner_text()
                backend = _eval_backend_for_thread(thread_id)
                if callable(getattr(backend, "workspace_is_clean", None)):
                    clean_before_approval = backend.workspace_is_clean()
                else:
                    workspace_status = subprocess.run(
                        ["git", "status", "--porcelain", "--untracked-files=all"], cwd=workspace_dir,
                        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
                    )
                    clean_before_approval = workspace_status.returncode == 0 and not workspace_status.stdout.strip()
                with page.expect_response(
                    lambda response: response.request.method == "POST" and response.url.endswith("/stream-message"),
                    timeout=timeout * 1000,
                ) as approval_response:
                    page.get_by_role("button", name="确认并实施").click()
                approval_events = _parse_sse_text(approval_response.value.text())
                status_pill = page.locator(".workspace-status .status-pill")
                status_pill.wait_for(state="visible", timeout=min(timeout * 1000, 30_000))
                status_pill.first.wait_for(state="visible")
                final_status_label = status_pill.first.inner_text()
                # The SSE request returns after the Agent run, but the Vue
                # store may render its final state on the next event-loop tick.
                # Give the UI a bounded chance to reflect that persisted state.
                if final_status_label != "已完成":
                    try:
                        page.wait_for_function(
                            "() => document.querySelector('.workspace-status .status-pill')?.textContent?.trim() === '已完成'",
                            timeout=min(timeout * 1000, 15_000),
                        )
                        final_status_label = status_pill.first.inner_text()
                    except Exception:
                        pass
                return {
                    "browser_started": True,
                    "page_loaded": True,
                    "repo_and_prompt_entered": True,
                    "task_submitted": True,
                    "pending_plan_displayed": pending_plan_displayed,
                    "workspace_clean_before_approval": clean_before_approval,
                    "approval_clicked": True,
                    "thread_id": thread_id,
                    "initial_event_count": len(first_events),
                    "approval_event_count": len(approval_events),
                    "plan_text": plan_text,
                    "final_status_label": final_status_label,
                    "completion_displayed": final_status_label == "已完成",
                }
            finally:
                browser.close()
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def main() -> int:
    if os.environ.get("CODING_AGENT_EVAL_MODE") != "1":
        raise RuntimeError("The app Eval adapter may only run inside an isolated Agent Eval case")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    source_root = Path(os.environ["EVAL_AGENT_SOURCE_ROOT"]).expanduser().resolve()
    sys.path.insert(0, str(source_root))
    _load_eval_model_environment()
    config = json.loads(Path(os.environ["EVAL_CASE_CONFIG"]).read_text(encoding="utf-8"))
    from agent.evals.telemetry import record_eval_event
    from agent.env_utils import get_env
    from agent.core.settings import PERSISTENCE_BACKEND, POSTGRES_DSN

    injection = _instrument_retrieval(record_eval_event, config.get("metadata", {}).get("inject_tool_error_once"))
    _instrument_runtime_events(record_eval_event)
    usage_calls = _install_usage_callbacks(record_eval_event)
    repo_url = str(config.get("metadata", {}).get("repo_url") or os.environ.get("EVAL_REPO_URL", "")).strip()
    if not repo_url:
        raise RuntimeError("No target repository URL was configured for the app Eval adapter")
    _install_eval_safety(repo_url)

    import uvicorn
    from agent.app import app

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False))
    thread = threading.Thread(target=server.run, name="eval-app-server", daemon=True)
    result: dict[str, Any] = {"status": "error"}
    try:
        thread.start()
        base_url = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + min(60, int(config.get("timeout_seconds", 480)))
        health: dict[str, Any] | None = None
        with httpx.Client() as client:
            while time.monotonic() < deadline:
                try:
                    response = client.get(base_url + "/health", timeout=2)
                    if response.status_code == 200:
                        health = response.json()
                        break
                except httpx.HTTPError:
                    time.sleep(0.25)
            if health is None:
                raise RuntimeError("CODING app did not become healthy before the ready timeout")

            state_root = Path(os.environ["CODING_DATA_DIR"]).resolve()
            db_paths = [
                Path(os.environ[key]).resolve()
                for key in ("CHECKPOINT_DB_PATH", "STORE_DB_PATH", "LANGGRAPH_STORE_DB_PATH")
            ]
            prompt = str(config.get("prompt", ""))
            metadata = config.get("metadata", {})
            plan_decision = str(metadata.get("plan_decision") or "approve")
            browser_evidence: dict[str, Any] | None = None
            plan_text = ""
            if config.get("metadata", {}).get("browser_e2e") is True:
                browser_evidence = _run_browser_task(
                    source_root,
                    base_url,
                    repo_url,
                    prompt,
                    Path(os.environ["EVAL_RESULT_FILE"]).resolve().parent.parent,
                    Path(os.environ["EVAL_CASE_REPO"]).resolve(),
                    int(config.get("timeout_seconds", 480)),
                )
                thread_id = str(browser_evidence["thread_id"])
                first_events = [None] * int(browser_evidence["initial_event_count"])
                second_events = [None] * int(browser_evidence["approval_event_count"])
                plan_pending = bool(browser_evidence.get("pending_plan_displayed"))
                clean_before_approval = bool(browser_evidence.get("workspace_clean_before_approval"))
                plan_text = str(browser_evidence.get("plan_text") or "")
            else:
                request = {"content": prompt, "repo": repo_url}
                first_events = _sse_post(client, base_url + "/dashboard/api/threads/stream-message", request, int(config.get("timeout_seconds", 480)))
                thread_id = next(
                    (str(item["data"]["thread_id"]) for item in first_events if item.get("data", {}).get("thread_id")),
                    "",
                )
                if not thread_id:
                    raise RuntimeError("App SSE response did not include a persisted thread_id")
            thread_url = base_url + "/dashboard/api/threads/" + thread_id
            if browser_evidence is None:
                first_thread = client.get(thread_url, timeout=10)
                first_thread.raise_for_status()
                first_payload = first_thread.json()
                plan = _latest_plan(first_payload)
                plan_pending = bool(plan and plan.get("status") == "pending" and plan.get("plan_id"))
                import subprocess

                backend = _eval_backend_for_thread(thread_id)
                if callable(getattr(backend, "workspace_is_clean", None)):
                    clean_before_approval = backend.workspace_is_clean()
                else:
                    workspace_status = subprocess.run(
                        ["git", "status", "--porcelain", "--untracked-files=all"],
                        cwd=Path(os.environ["EVAL_CASE_REPO"]).resolve(),
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        check=False,
                    )
                    clean_before_approval = workspace_status.returncode == 0 and not workspace_status.stdout.strip()
                second_events = []
                if plan_pending and plan_decision == "reject":
                    second_events = _submit_plan_decision(
                        client, thread_url, plan, "reject", int(config.get("timeout_seconds", 480))
                    )
                    plan_text = str((plan or {}).get("plan_text") or "")
                elif plan_pending and metadata.get("auto_approve_plan") is True:
                    second_events = _submit_plan_decision(
                        client, thread_url, plan, "approve", int(config.get("timeout_seconds", 480))
                    )
                    plan_text = str((plan or {}).get("plan_text") or "")
            final_response = client.get(thread_url, timeout=10)
            final_response.raise_for_status()
            final_payload = final_response.json()
            final_plan = _latest_plan(final_payload)
            sandbox_evidence = _close_eval_sandbox(thread_id)
            import subprocess

            final_workspace_status = subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=all"],
                cwd=Path(os.environ["EVAL_CASE_REPO"]).resolve(),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            workspace_clean_after_decision = (
                final_workspace_status.returncode == 0 and not final_workspace_status.stdout.strip()
            )
            # Persistence is initialized lazily on the first write, so verify only
            # after the task and plan decision have traversed the app API.
            sqlite_isolated = all(path.is_relative_to(state_root) for path in db_paths) and all(path.is_file() for path in db_paths)
            persistence_isolated = sqlite_isolated
            postgres_e2e: dict[str, Any] | None = None
            if PERSISTENCE_BACKEND == "postgres":
                before_restart = _postgres_thread_snapshot(POSTGRES_DSN, thread_id)
                if not before_restart["identity_verified"]:
                    raise RuntimeError("PostgreSQL E2E refused a database outside the runner's loopback eval instance")
                if not before_restart["records_persisted"]:
                    raise RuntimeError("PostgreSQL E2E found incomplete thread/run/plan/checkpoint records")

                # Stop and reconstruct the app's persistence singletons so the
                # follow-up API read uses a newly opened PostgreSQL connection.
                server.should_exit = True
                thread.join(timeout=30)
                if thread.is_alive():
                    server.force_exit = True
                    thread.join(timeout=5)
                if thread.is_alive():
                    raise RuntimeError("PostgreSQL E2E backend did not stop for its persistence restart check")
                from agent.core import graph as graph_module
                from agent.core.persistence import close_persistence

                close_persistence()
                graph_module._store = None
                graph_module._checkpointer = None
                graph_module._langgraph_store = None
                server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False))
                thread = threading.Thread(target=server.run, name="eval-app-server-restarted", daemon=True)
                thread.start()
                ready_by = time.monotonic() + 30
                while time.monotonic() < ready_by:
                    try:
                        if client.get(base_url + "/health", timeout=2).status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.25)
                else:
                    raise RuntimeError("PostgreSQL E2E app did not restart healthy")
                restored_response = client.get(thread_url, timeout=15)
                restored_response.raise_for_status()
                restored_thread = restored_response.json()
                after_restart = _postgres_thread_snapshot(POSTGRES_DSN, thread_id)
                reconnect_ok = _postgres_reconnect_verified(
                    thread_id, final_payload, restored_thread, after_restart
                )
                postgres_e2e = {
                    **before_restart,
                    "reconnect_verified": bool(reconnect_ok),
                    "backend_restarted": True,
                    "api_thread_restored": (restored_thread.get("thread_id") or restored_thread.get("id")) == thread_id,
                    "api_message_count_after_restart": len(restored_thread.get("messages", [])),
                    "status_after_restart": restored_thread.get("status"),
                    "record_counts_after_restart": after_restart["record_counts"],
                }
                persistence_isolated = bool(
                    postgres_e2e["identity_verified"]
                    and postgres_e2e["records_persisted"]
                    and postgres_e2e["reconnect_verified"]
                    and postgres_e2e["backend_restarted"]
                )
            result = {
                "status": "completed" if final_payload.get("status") in {"completed", "finished"} else "error",
                "model_provider": "DeepSeek",
                "model_name": get_env("MAIN_MODEL", "configured-default"),
                "thread_id": thread_id,
                "plan_approval_performed": bool(plan_pending and second_events and plan_decision == "approve"),
                "plan_rejection_performed": bool(plan_pending and second_events and plan_decision == "reject"),
                "plan_pending_before_approval": plan_pending,
                "workspace_clean_before_approval": clean_before_approval,
                "plan_pending_before_rejection": plan_pending if plan_decision == "reject" else None,
                "workspace_clean_before_rejection": clean_before_approval if plan_decision == "reject" else None,
                "workspace_clean_after_rejection": workspace_clean_after_decision if plan_decision == "reject" else None,
                "plan_text": plan_text,
                "sandbox": sandbox_evidence,
                "runtime_status": final_payload.get("status"),
                "final_plan_status": (final_plan or {}).get("status"),
                "api_e2e": {
                    "health_passed": True,
                    "thread_created": True,
                    "sse_received": bool(first_events),
                    "approval_posted": bool(second_events and plan_decision == "approve"),
                    "rejection_posted": bool(second_events and plan_decision == "reject"),
                    "workspace_clean_after_rejection": workspace_clean_after_decision if plan_decision == "reject" else None,
                    "sqlite_isolated": sqlite_isolated,
                    "persistence_backend": PERSISTENCE_BACKEND,
                    "persistence_isolated": persistence_isolated,
                    "postgres_e2e": postgres_e2e,
                    "database_paths": [str(path) for path in db_paths],
                    "initial_event_count": len(first_events),
                    "approval_event_count": len(second_events) if plan_decision == "approve" else 0,
                    "rejection_event_count": len(second_events) if plan_decision == "reject" else 0,
                    "final_status": final_payload.get("status"),
                    "final_plan_status": (final_plan or {}).get("status"),
                    "browser": browser_evidence,
                    "sandbox": sandbox_evidence,
                },
                "output": _sanitize_text(_thread_text(final_payload)),
            }
    finally:
        server.should_exit = True
        if thread.is_alive():
            thread.join(timeout=30)
        if thread.is_alive():
            server.force_exit = True
            thread.join(timeout=5)

    trace_path = Path(os.environ["EVAL_EVENT_FILE"]).expanduser().resolve()
    for failure in injection:
        if not failure.get("recovered"):
            record_eval_event("tool_error", {**failure, "error_type": "TimeoutError", "injected": True})
    _finalize_tool_trace(trace_path)
    _write_json(os.environ["EVAL_USAGE_FILE"], _usage_from_callback_calls(usage_calls))
    _write_json(os.environ["EVAL_RESULT_FILE"], result)
    print(json.dumps({key: value for key, value in result.items() if key != "output"}, ensure_ascii=False))
    return 0 if result.get("status") == "completed" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        result_path = os.environ.get("EVAL_RESULT_FILE")
        if result_path:
            _write_json(result_path, {"status": "error", "error": _sanitize_text(str(exc))[:2000]})
        traceback.print_exc(file=sys.stderr)
        raise
