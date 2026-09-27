from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.evals.reporting import write_report_data
from agent.evals.runner import EvalRunner


def _summary(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_count": 1,
        "passed_count": int(case.get("status") == "passed"),
        "failed_count": int(case.get("status") != "passed"),
        "patch_apply_rate": float(bool(case.get("patch_apply"))),
        "target_test_pass_rate": None if case.get("target_tests_passed") is None else float(bool(case.get("target_tests_passed"))),
        "target_test_passed_case_count": int(case.get("target_tests_passed") is True),
        "target_test_case_count": int(case.get("target_tests_passed") is not None),
        "regression_test_pass_rate": None if case.get("regression_tests_passed") is None else float(bool(case.get("regression_tests_passed"))),
        "regression_test_passed_case_count": int(case.get("regression_tests_passed") is True),
        "regression_test_case_count": int(case.get("regression_tests_passed") is not None),
        "oracle_test_pass_rate": None if case.get("oracle_tests_passed") is None else float(bool(case.get("oracle_tests_passed"))),
        "oracle_test_passed_case_count": int(case.get("oracle_tests_passed") is True),
        "oracle_test_case_count": int(case.get("oracle_tests_passed") is not None),
        "retrieval_hit_at_k": case.get("retrieval_hit_at_k"),
        "tool_recovery_rate": case.get("tool_recovery_rate"),
        "total_tokens": case.get("total_tokens"),
        "token_usage_case_count": int(case.get("total_tokens") is not None),
        "total_latency_ms": int(case.get("agent_latency_ms") or 0),
    }


def _commands(
    values: list[list[str] | str], *, python: str, repo: Path, source_root: Path
) -> list[list[str]]:
    normalized: list[list[str]] = []
    oracle_root = source_root / "agent" / "evals" / "oracles"
    for value in values:
        parts = [str(part) for part in value] if isinstance(value, list) else shlex.split(str(value))
        parts = [
            part.replace("{oracle_scripts}", str(oracle_root)).replace("{target_repo}", str(repo))
            for part in parts
        ]
        if parts and Path(parts[0]).name.lower() in {"python", "python.exe", "python3"}:
            parts[0] = python
        normalized.append(parts)
    return normalized


def _run(commands: list[list[str]], *, cwd: Path, timeout: int) -> tuple[bool, list[dict[str, Any]]]:
    results: list[dict[str, Any]] = []
    env = EvalRunner._safe_subprocess_env()
    env["PYTHONPATH"] = str(cwd)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    for command in commands:
        try:
            completed = subprocess.run(
                command, cwd=cwd, env=env, capture_output=True,
                text=True, encoding="utf-8", errors="replace",
                timeout=timeout, check=False, shell=False,
            )
            results.append({
                "command": command,
                "exit_code": completed.returncode,
                "stdout": completed.stdout[-8000:],
                "stderr": completed.stderr[-8000:],
            })
        except subprocess.TimeoutExpired as exc:
            results.append({"command": command, "exit_code": None, "timeout": True, "error": str(exc)[:1000]})
    return all(item.get("exit_code") == 0 for item in results), results


def main() -> int:
    parser = argparse.ArgumentParser(description="Re-run fixed tests and hidden oracle for a recorded Agent patch")
    parser.add_argument("--report", type=Path, required=True, help="Original real Eval report.json; it remains unchanged")
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--agent-source-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report_path = args.report.expanduser().resolve()
    output = args.output.expanduser().resolve()
    source_root = args.agent_source_root.expanduser().resolve()
    if output == source_root or source_root in output.parents:
        raise SystemExit("Rescore output must stay outside the Agent source repository")
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"Refusing to overwrite non-empty output directory: {output}")
    original = json.loads(report_path.read_text(encoding="utf-8"))
    matches = [case for case in original.get("cases", []) if case.get("case_id") == args.case_id]
    if len(matches) != 1:
        raise SystemExit(f"Expected exactly one case named {args.case_id!r} in the input report")
    case = json.loads(json.dumps(matches[0]))
    if case.get("agent_exit_code") != 0 or not case.get("patch_apply"):
        raise SystemExit("Oracle rescore requires a recorded successful Agent exit and patch application")
    if case.get("target_tests_passed") is not True or case.get("regression_tests_passed") is not True:
        raise SystemExit("Oracle rescore will not override a failed target or regression test")

    case_dir = report_path.parent / "cases" / args.case_id
    case_config = json.loads((case_dir / "artifacts" / "case-config.json").read_text(encoding="utf-8"))
    target_sha = str(case.get("metadata", {}).get("target_repo_sha", ""))
    repository = Path(str(original.get("repository", ""))).expanduser().resolve()
    if not target_sha or not repository.is_dir():
        raise SystemExit("The report does not identify a locally available fixed target repository revision")
    python = str(original.get("config", {}).get("python") or sys.executable)
    with tempfile.TemporaryDirectory(prefix=f"eval-oracle-rescore-{args.case_id}-") as temporary:
        candidate = Path(temporary) / "candidate"
        EvalRunner._extract_git_archive(repository, target_sha, candidate)
        EvalRunner._materialize_case_fixtures(
            __import__("agent.evals.schemas", fromlist=["EvalCase"]).EvalCase.from_dict(case_config),
            candidate,
        )
        EvalRunner._init_git_baseline(candidate)
        patch_ok, patch_error = EvalRunner._apply_patch_to_checkout(candidate, str(case.get("patch", "")))
        if not patch_ok:
            raise SystemExit(f"Recorded patch no longer applies to the pinned target and fixtures: {patch_error[-1000:]}")
        target_ok, target_results = _run(
            _commands(case_config.get("target_tests", []), python=python, repo=candidate, source_root=source_root),
            cwd=candidate,
            timeout=int(case_config.get("timeout_seconds", 600)),
        )
        regression_ok, regression_results = _run(
            _commands(case_config.get("regression_tests", []), python=python, repo=candidate, source_root=source_root),
            cwd=candidate,
            timeout=int(case_config.get("timeout_seconds", 600)),
        )
        oracle_ok, oracle_results = _run(
            _commands(case_config.get("oracle_tests", []), python=python, repo=candidate, source_root=source_root),
            cwd=candidate,
            timeout=int(case_config.get("timeout_seconds", 600)),
        )
        actual_files = EvalRunner._changed_files(candidate)

    allowed = set(case_config.get("allowed_files", []))
    required = set(case_config.get("metadata", {}).get("required_changed_files", []))
    scope_ok = (not allowed or set(actual_files).issubset(allowed)) and required.issubset(actual_files)
    if not target_ok or not regression_ok or not oracle_ok or not scope_ok:
        case["status"] = "failed"
    else:
        case["status"] = "passed"
    case["target_tests_passed"] = target_ok
    case["regression_tests_passed"] = regression_ok
    case["oracle_tests_passed"] = oracle_ok
    case["changed_files"] = actual_files
    case["patch_apply"] = patch_ok
    case["errors"] = [] if case["status"] == "passed" else [
        label for label, passed in (
            ("target tests failed during oracle rescore", target_ok),
            ("regression tests failed during oracle rescore", regression_ok),
            ("hidden oracle failed during oracle rescore", oracle_ok),
            ("patch scope/required-file check failed during oracle rescore", scope_ok),
        ) if not passed
    ]
    oracle_scripts = [str(part) for command in case_config.get("oracle_tests", []) for part in (command if isinstance(command, list) else [command])]
    oracle_script_hashes: dict[str, str] = {}
    for value in oracle_scripts:
        name = Path(value.replace("{oracle_scripts}", str(source_root / "agent" / "evals" / "oracles"))).name
        path = source_root / "agent" / "evals" / "oracles" / name
        if path.is_file():
            oracle_script_hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    case.setdefault("metadata", {})["oracle_rescore"] = {
        "source_report_id": original.get("report_id"),
        "original_report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
        "checked_at": datetime.now(UTC).isoformat(),
        "target_repo_sha": target_sha,
        "clean_baseline_patch_applied": patch_ok,
        "target_tests_passed": target_ok,
        "regression_tests_passed": regression_ok,
        "hidden_oracle_passed": oracle_ok,
        "changed_files_scope_passed": scope_ok,
        "oracle_script_sha256": oracle_script_hashes,
        "target_test_results": target_results,
        "regression_test_results": regression_results,
        "oracle_test_results": oracle_results,
    }

    output.mkdir(parents=True, exist_ok=True)
    copied_case = output / "cases" / args.case_id
    for directory_name in ("artifacts", "traces"):
        source_directory = case_dir / directory_name
        if source_directory.is_dir():
            shutil.copytree(source_directory, copied_case / directory_name, dirs_exist_ok=True)
    case["artifacts"] = {
        label: f"cases/{args.case_id}/artifacts/{Path(str(value)).name}"
        for label, value in case.get("artifacts", {}).items()
    }
    result = {
        **original,
        "report_id": hashlib.sha256((str(original.get("report_id")) + args.case_id + json.dumps(case["metadata"]["oracle_rescore"], sort_keys=True)).encode()).hexdigest()[:16],
        "created_at": datetime.now(UTC).isoformat(),
        "cases": [case],
        "summary": _summary(case),
        "config": {**original.get("config", {}), "oracle_rescore_of": original.get("report_id")},
    }
    (output / "report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "run.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_report_data(result, output)
    print(json.dumps({"report_id": result["report_id"], "case_id": args.case_id, "status": case["status"], "summary": result["summary"]}, ensure_ascii=False))
    return 0 if case["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
