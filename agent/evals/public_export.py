from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

from agent.evals.reporting import write_report_data


_ARTIFACT_ALLOWLIST = {"agent-output.txt", "patch.diff", "tests.log", "agent-events.jsonl"}
_SECRET_PATTERNS = (
    re.compile(r"(?i)(\b(?:api[_-]?key|token|password|secret)\b[\"']?\s*[:=]\s*[\"']?)([^\s,;\"'}]+)"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
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
        for key in ("agent_source_sha", "agent_source_dirty_patch_sha256", "runner_version")
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
            )
            if key in metadata
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
