from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

from agent.evals.reporting import write_report_data


_ARTIFACT_ALLOWLIST = {"agent-output.txt", "patch.diff", "tests.log", "agent-events.jsonl", "manual-review.md"}
_SECRET_PATTERNS = (
    re.compile(r"(?i)(\b(?:api[_-]?key|token|password|secret)\b[\"']?\s*[:=]\s*[\"']?)([^\s,;\"'}]+)"),
    re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{16,}(?![A-Za-z0-9_-])"),
)
_WINDOWS_ABSOLUTE = re.compile(r"(?i)\b[A-Z]:\\(?:[^\s\"'<>|]+)")
_UNIX_HOME = re.compile(r"(?<![\w.])/(?:home|Users|mnt|tmp|private)/[^\s\"'<>|]+")


def export_public_report(run_dir: Path, output_dir: Path) -> dict[str, Any]:
    """Export a reviewable report bundle without local workspace or state data."""

    run_dir = run_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    source_report = run_dir / "report.json"
    if not source_report.is_file():
        raise FileNotFoundError(f"No report.json found in {run_dir}")
    raw_data = json.loads(source_report.read_text(encoding="utf-8"))
    repo_label = Path(str(raw_data.get("repository", "benchmark")).rstrip("/\\")).name or "benchmark"
    data = _sanitize(raw_data)
    # Keep only fields useful for public benchmark evidence. Internal paths and
    # machine-specific config are intentionally excluded by allowlisting.
    data["repository"] = repo_label
    config = data.get("config", {})
    data["config"] = {
        key: config[key]
        for key in (
            "agent_source_sha", "agent_source_dirty_patch_sha256", "agent_adapter_sha256",
            "agent_runtime_snapshot_sha256", "agent_runtime_overlay_files", "framework_source_sha",
            "framework_source_dirty_patch_sha256", "case_manifest_sha256", "runner_version",
        )
        if key in config
    }

    for case in data.get("cases", []):
        metadata = case.get("metadata", {})
        case["metadata"] = {
            key: metadata[key]
            for key in (
                "model_provider", "model_name", "model_usage", "retrieval_call_count",
                "tool_usage", "test_behavior", "target_repo_sha", "expected_status",
                "model_call_limit", "tool_call_limit", "codegraph_index",
                "agent_adapter_sha256", "selected_adapter_sha256", "agent_runtime_snapshot_sha256",
                "database_evaluation", "plan_rejection_ok", "plan_rubric",
                "sandbox_e2e_passed", "sandbox",
            )
            if key in metadata
        }
        api_e2e = metadata.get("api_e2e")
        if isinstance(api_e2e, dict):
            safe_api_fields = (
                "health_passed", "thread_created", "sse_received", "approval_posted",
                "rejection_posted", "workspace_clean_after_rejection", "final_plan_status",
                "sqlite_isolated", "persistence_backend", "persistence_isolated",
                "final_status", "initial_event_count", "approval_event_count",
            )
            case["metadata"]["api_e2e"] = {key: api_e2e[key] for key in safe_api_fields if key in api_e2e}
            postgres = api_e2e.get("postgres_e2e")
            if isinstance(postgres, dict):
                case["metadata"]["api_e2e"]["postgres_e2e"] = {
                    key: postgres[key]
                    for key in (
                        "identity_verified", "records_persisted", "reconnect_verified",
                        "backend_restarted", "record_counts", "checkpoint_count",
                        "record_counts_after_restart", "api_thread_restored",
                        "api_message_count_after_restart", "status_after_restart",
                    )
                    if key in postgres
                }
            browser = api_e2e.get("browser")
            if isinstance(browser, dict):
                browser_fields = (
                    "browser_started", "page_loaded", "repo_and_prompt_entered", "task_submitted",
                    "pending_plan_displayed", "workspace_clean_before_approval", "approval_clicked",
                    "completion_displayed", "initial_event_count", "approval_event_count", "final_status_label",
                )
                case["metadata"]["api_e2e"]["browser"] = {key: browser[key] for key in browser_fields if key in browser}
        sandbox = metadata.get("sandbox")
        if isinstance(sandbox, dict):
            sandbox_fields = (
                "image", "uploaded_file_count", "uploaded_paths", "use_server_proxy",
                "cleanup_succeeded", "command_latency_ms", "oracle_test_latency_ms",
            )
            case["metadata"]["sandbox"] = {key: sandbox[key] for key in sandbox_fields if key in sandbox}
            case["metadata"]["sandbox"].update({
                key: sandbox[key]
                for key in (
                    "host_patch_exported", "uploaded_bytes", "target_workspace",
                    "patch_bytes", "already_closed", "error", "cleanup_error",
                )
                if key in sandbox
            })
            safety = sandbox.get("safety_probes")
            if isinstance(safety, dict):
                safe_probe_fields = (
                    "path_traversal_rejected", "timeout_enforced", "cleanup_succeeded",
                    "timeout_latency_ms", "probe_latency_ms", "timeout_error",
                )
                case["metadata"]["sandbox"]["safety_probes"] = {
                    key: safety[key] for key in safe_probe_fields if key in safety
                }
        artifacts = {}
        for label, relative in case.get("artifacts", {}).items():
            safe_relative = _safe_run_relative(relative)
            source = (run_dir / Path(*safe_relative.parts)).resolve()
            if not source.is_relative_to(run_dir) or source.name not in _ARTIFACT_ALLOWLIST or not source.is_file():
                continue
            destination = output_dir / Path(*safe_relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(_redact(source.read_text(encoding="utf-8", errors="replace")), encoding="utf-8")
            artifacts[label] = safe_relative.as_posix()
        case["artifacts"] = artifacts

    (output_dir / "report.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    views = write_report_data(data, output_dir)
    return {"report": "report.json", **views, "cases": len(data.get("cases", []))}


def _safe_run_relative(value: Any) -> PurePosixPath:
    raw = str(value).replace("\\", "/")
    path = PurePosixPath(raw)
    if path.is_absolute() or ":" in raw or ".." in path.parts:
        raise ValueError(f"Artifact path is not run-relative: {value!r}")
    return path


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _sanitize(item) for key, item in value.items() if key not in {"agent_source_root", "python", "repo_path", "workspace_root", "state_files"}}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        return _redact(value)
    return value


def _redact(value: str) -> str:
    for pattern in _SECRET_PATTERNS:
        if pattern.groups:
            value = pattern.sub(r"\1[REDACTED]", value)
        else:
            value = pattern.sub("[REDACTED]", value)
    value = _WINDOWS_ABSOLUTE.sub("[LOCAL_PATH]", value)
    value = _UNIX_HOME.sub("[LOCAL_PATH]", value)
    return value
