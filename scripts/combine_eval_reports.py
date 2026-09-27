from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import shutil
import sys
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.evals.reporting import write_report_data


def _average(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return round(sum(present) / len(present), 4) if present else None


def _summary(cases: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "case_count": len(cases),
        "passed_count": sum(case.get("status") == "passed" for case in cases),
        "failed_count": sum(case.get("status") != "passed" for case in cases),
        "patch_apply_rate": _average([float(bool(case.get("patch_apply"))) for case in cases]),
        "target_test_pass_rate": _average([None if case.get("target_tests_passed") is None else float(bool(case.get("target_tests_passed"))) for case in cases]),
        "target_test_passed_case_count": sum(case.get("target_tests_passed") is True for case in cases),
        "target_test_case_count": sum(case.get("target_tests_passed") is not None for case in cases),
        "regression_test_pass_rate": _average([None if case.get("regression_tests_passed") is None else float(bool(case.get("regression_tests_passed"))) for case in cases]),
        "regression_test_passed_case_count": sum(case.get("regression_tests_passed") is True for case in cases),
        "regression_test_case_count": sum(case.get("regression_tests_passed") is not None for case in cases),
        "oracle_test_pass_rate": _average([None if case.get("oracle_tests_passed") is None else float(bool(case.get("oracle_tests_passed"))) for case in cases]),
        "oracle_test_passed_case_count": sum(case.get("oracle_tests_passed") is True for case in cases),
        "oracle_test_case_count": sum(case.get("oracle_tests_passed") is not None for case in cases),
        "retrieval_hit_at_k": _average([case.get("retrieval_hit_at_k") for case in cases]),
        "tool_recovery_rate": _average([case.get("tool_recovery_rate") for case in cases]),
        "total_tokens": sum(int(case["total_tokens"]) for case in cases if case.get("total_tokens") is not None) or None,
        "token_usage_case_count": sum(case.get("total_tokens") is not None for case in cases),
        "total_latency_ms": sum(int(case.get("agent_latency_ms") or 0) for case in cases),
    }


def _copy_report_case(source_report: Path, case: dict[str, Any], output: Path) -> dict[str, Any]:
    result = deepcopy(case)
    case_id = str(result["case_id"])
    source_id = str(source_report.parent.name)
    source_case = source_report.parent / "cases" / case_id
    target_case = output / "cases" / case_id / source_id
    for directory in ("artifacts", "traces"):
        source_directory = source_case / directory
        if source_directory.is_dir():
            shutil.copytree(source_directory, target_case / directory, dirs_exist_ok=True)
    artifact_paths: dict[str, str] = {}
    for label, value in result.get("artifacts", {}).items():
        normalized_path = str(value).replace("\\", "/")
        parts = Path(normalized_path).parts
        directory = "traces" if "traces" in parts else "artifacts"
        artifact_paths[label] = f"cases/{case_id}/{source_id}/{directory}/{Path(normalized_path).name}"
    result["artifacts"] = artifact_paths
    metadata = result.setdefault("metadata", {})
    for private_path in ("repo_path", "workspace_root", "state_files"):
        metadata.pop(private_path, None)
    metadata["provenance"] = {
        "source_report_id": str(json.loads(source_report.read_text(encoding="utf-8")).get("report_id", "unknown")),
        "agent_source_sha": metadata.get("agent_source_sha"),
        "target_repo_sha": metadata.get("target_repo_sha"),
        "run_artifacts": f"cases/{case_id}/{source_id}",
    }
    return result


def _copy_gate_report(report_path: Path, output: Path, gate_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    data = json.loads(report_path.read_text(encoding="utf-8"))
    cases = data.get("cases", [])
    case = cases[0] if cases else {}
    metadata = case.get("metadata", {})
    destination = output / "gates" / gate_id
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("report.json", "report.md", "report.html", "summary.md"):
        source = report_path.parent / name
        if source.is_file():
            shutil.copy2(source, destination / name)

    if gate_id == "real-opensandbox-agent":
        sandbox = metadata.get("sandbox", {})
        checks = {
            "真实 Agent 在 OpenSandbox 执行": metadata.get("sandbox_e2e_passed") is True,
            "补丁从容器回传": sandbox.get("host_patch_exported") is True,
            "沙箱资源清理": sandbox.get("cleanup_succeeded") is True,
            "注入命令错误后恢复": case.get("tool_recovery_rate") == 1.0,
            "目标、回归、隐藏验收": all(case.get(key) is True for key in ("target_tests_passed", "regression_tests_passed", "oracle_tests_passed")),
        }
        description = (
            f"DeepSeek Agent 在 OpenSandbox 中修改独立仓库，上传 {sandbox.get('uploaded_file_count', 0)} 个文件，"
            f"回传补丁 {sandbox.get('patch_bytes', 0)} 字节。"
        )
    else:
        api = metadata.get("api_e2e", {})
        postgres = api.get("postgres_e2e", {})
        sandbox = metadata.get("sandbox", {})
        instance = data.get("config", {}).get("postgres_instance", {})
        checks = {
            "真实 API / SSE 与计划审批": all(api.get(key) is True for key in ("health_passed", "thread_created", "sse_received", "approval_posted")),
            "一次性 PostgreSQL 记录写入": postgres.get("records_persisted") is True,
            "重启后 API 恢复": postgres.get("reconnect_verified") is True and postgres.get("backend_restarted") is True,
            "Agent 编码在沙箱执行并回传": sandbox.get("host_patch_exported") is True,
            "PostgreSQL 与沙箱清理": instance.get("cleanup_succeeded") is True and sandbox.get("cleanup_succeeded") is True,
        }
        description = (
            f"PostgreSQL {instance.get('version', 'unknown')}；一次性数据库 {instance.get('database_name', 'unknown')}；"
            f"运行事件 {postgres.get('record_counts', {}).get('run_events', 0)} 条。"
        )
    gate = {
        "id": gate_id,
        "title": "真实 Agent + OpenSandbox 编码" if gate_id == "real-opensandbox-agent" else "应用 API + OpenSandbox + PostgreSQL E2E",
        "status": "passed" if all(checks.values()) and case.get("status") == "passed" else "failed",
        "checks": checks,
        "description": description,
        "report_path": f"gates/{gate_id}/report.html",
        "source_report_id": data.get("report_id"),
        "agent_source_sha": data.get("config", {}).get("agent_source_sha"),
    }
    return gate, data


def main() -> int:
    parser = argparse.ArgumentParser(description="Combine separate Agent Eval runs into one reviewable suite report")
    parser.add_argument("--report", action="append", type=Path, required=True, help="Input report.json; later reports replace duplicate case IDs")
    parser.add_argument("--opensandbox-report", type=Path, required=True)
    parser.add_argument("--postgres-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    output = args.output.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"Refusing to overwrite non-empty output directory: {output}")
    output.mkdir(parents=True, exist_ok=True)
    selected: dict[str, tuple[Path, dict[str, Any]]] = {}
    source_ids: list[str] = []
    source_revisions: set[str] = set()
    for report_value in args.report:
        report_path = report_value.expanduser().resolve()
        data = json.loads(report_path.read_text(encoding="utf-8"))
        source_ids.append(str(data.get("report_id", report_path.parent.name)))
        for case in data.get("cases", []):
            selected[str(case["case_id"])] = (report_path, case)
            sha = str(case.get("metadata", {}).get("agent_source_sha", "")).strip()
            if sha:
                source_revisions.add(sha)
    cases = [_copy_report_case(path, case, output) for path, case in selected.values()]
    gates: list[dict[str, Any]] = []
    sandbox_gate, _ = _copy_gate_report(args.opensandbox_report.expanduser().resolve(), output, "real-opensandbox-agent")
    postgres_gate, _ = _copy_gate_report(args.postgres_report.expanduser().resolve(), output, "application-postgres-e2e")
    gates.extend([sandbox_gate, postgres_gate])
    current_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT,
        capture_output=True, text=True, encoding="utf-8", check=False, shell=False,
    ).stdout.strip() or None
    report_id = hashlib.sha256("|".join(source_ids + sorted(source_revisions)).encode()).hexdigest()[:16]
    result = {
        "report_id": report_id,
        "mode": "real",
        "repository": "https://github.com/Guo-Yixin/test-coding-eval",
        "created_at": datetime.now(UTC).isoformat(),
        "config": {
            "agent_source_sha": next(iter(source_revisions)) if len(source_revisions) == 1 else "逐题记录固定 Agent SHA，见案例详情",
            "framework_source_sha": current_sha,
            "runner_version": "4",
            "source_report_ids": source_ids,
            "system_gates": gates,
            "coding_case_count": len(cases),
            "report_scope": "旧五题 + 新五题；OpenSandbox 和 PostgreSQL 端到端能力作为独立门禁",
        },
        "summary": _summary(cases),
        "cases": cases,
    }
    result["config"]["agent_source_revisions"] = sorted(source_revisions)
    (output / "report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "run.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_report_data(result, output)
    print(json.dumps({"report_id": report_id, "summary": result["summary"], "system_gates": [{"id": gate["id"], "status": gate["status"]} for gate in gates]}, ensure_ascii=False))
    return 0 if result["summary"]["passed_count"] == result["summary"]["case_count"] and all(gate["status"] == "passed" for gate in gates) else 1


if __name__ == "__main__":
    raise SystemExit(main())
