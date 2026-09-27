from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.evals.reporting import write_report_data
from agent.evals.schemas import EvalCaseResult, EvalReport


def _safe_environment() -> dict[str, str]:
    names = {
        "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE", "HOME",
        "APPDATA", "LOCALAPPDATA", "VIRTUAL_ENV", "PYTHON", "PYTHONPATH",
    }
    environment = {key: value for key, value in os.environ.items() if key.upper() in names}
    environment["GIT_TERMINAL_PROMPT"] = "0"
    return environment


def _source_fingerprint() -> str:
    completed = subprocess.run(
        ["git", "diff", "--binary", "HEAD", "--", "agent", "scripts", "tests"],
        cwd=PROJECT_ROOT, capture_output=True, check=False, shell=False,
    )
    return hashlib.sha256(completed.stdout).hexdigest() if completed.returncode == 0 else "unavailable"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run PostgreSQL persistence checks against an ephemeral local container")
    parser.add_argument("--output", type=Path, help="New output directory; defaults to the external Agent Eval run root")
    parser.add_argument("--image", default="postgres:18", help="PostgreSQL Docker image (official postgres:<version> tags only)")
    parser.add_argument("--timeout", type=int, default=180, help="Maximum seconds to wait for database startup and tests")
    args = parser.parse_args()
    if not re.fullmatch(r"postgres:[0-9]+(?:-alpine)?", args.image):
        raise SystemExit("--image must be an official postgres:<version> image tag")
    if args.timeout < 30 or args.timeout > 900:
        raise SystemExit("--timeout must be between 30 and 900 seconds")

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    configured_root = os.environ.get("CODING_AGENT_EVAL_ROOT", "").strip()
    eval_root = Path(configured_root) if configured_root else PROJECT_ROOT.parent / "coding-agent-eval-runs"
    output_dir = (args.output or eval_root / "runs" / run_id / "postgres-persistence").expanduser().resolve()
    if output_dir == PROJECT_ROOT or PROJECT_ROOT in output_dir.parents:
        raise SystemExit("PostgreSQL Eval output must be outside the coding-agent source repository")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise SystemExit(f"Refusing to overwrite non-empty output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    case_dir = output_dir / "cases" / "postgres-persistence-smoke"
    case_dir.mkdir(parents=True)

    suffix = uuid4().hex[:10]
    container_name = f"coding-agent-eval-pg-{suffix}"
    database_name = f"coding_agent_eval_{suffix}"
    password = secrets.token_urlsafe(32)
    dsn = ""
    container_started = False
    cleanup_succeeded = False
    stdout = ""
    stderr = ""
    errors: list[str] = []
    test_latency = 0
    database_version = "unknown"
    tests_passed = False
    started = time.perf_counter()

    try:
        docker = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=20, check=False, shell=False,
        )
        if docker.returncode != 0:
            raise RuntimeError("Docker daemon is unavailable; PostgreSQL Eval requires a local Docker Engine")
        launched = subprocess.run(
            [
                "docker", "run", "-d", "--rm", "--name", container_name,
                "-e", "POSTGRES_USER=eval_runner", "-e", f"POSTGRES_PASSWORD={password}",
                "-e", f"POSTGRES_DB={database_name}", "-p", "127.0.0.1::5432", args.image,
            ],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60, check=False, shell=False,
        )
        if launched.returncode != 0:
            raise RuntimeError("Could not start the disposable PostgreSQL container: " + (launched.stderr or "")[-800:])
        container_started = True
        port_result = subprocess.run(
            ["docker", "port", container_name, "5432/tcp"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=15, check=False, shell=False,
        )
        match = re.fullmatch(r"127\.0\.0\.1:(\d+)\s*", port_result.stdout.strip())
        if port_result.returncode != 0 or not match:
            raise RuntimeError("Temporary PostgreSQL port was not bound exclusively to localhost")
        dsn = f"postgresql://eval_runner:{password}@127.0.0.1:{match.group(1)}/{database_name}"

        import psycopg

        deadline = time.monotonic() + min(args.timeout, 120)
        connection = None
        last_connection_error = None
        while time.monotonic() < deadline:
            try:
                connection = psycopg.connect(dsn, connect_timeout=3)
                break
            except psycopg.Error as exc:
                last_connection_error = exc
                time.sleep(2)
        if connection is None:
            raise RuntimeError(f"Disposable PostgreSQL did not become ready: {last_connection_error}")
        with connection:
            row = connection.execute("SELECT version(), current_database(), current_user").fetchone()
            database_version = str(row[0]).splitlines()[0]
            if row[1] != database_name or row[2] != "eval_runner":
                raise RuntimeError("PostgreSQL Eval connected to an unexpected database or role")
        connection.close()

        test_environment = _safe_environment()
        test_environment.update({"POSTGRES_DSN": dsn, "PERSISTENCE_BACKEND": "postgres"})
        test_environment.pop("CODING_AGENT_EVAL_MODE", None)
        test_started = time.perf_counter()
        tested = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/unit/test_persistence_factory.py", "-m", "integration", "-q"],
            cwd=PROJECT_ROOT, env=test_environment, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=args.timeout, check=False, shell=False,
        )
        test_latency = int((time.perf_counter() - test_started) * 1000)
        stdout = tested.stdout or ""
        stderr = tested.stderr or ""
        tests_passed = tested.returncode == 0
        if not tests_passed:
            errors.append(f"PostgreSQL persistence integration tests exited with {tested.returncode}")
    except Exception as exc:
        message = str(exc).replace(dsn, "[TEST_DATABASE_DSN]") if dsn else str(exc)
        message = message.replace(password, "[REDACTED]")
        errors.append(message[:1200])
    finally:
        if container_started:
            removed = subprocess.run(
                ["docker", "rm", "-f", container_name], capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=30, check=False, shell=False,
            )
            cleanup_succeeded = removed.returncode == 0
            if not cleanup_succeeded:
                errors.append("Could not remove the disposable PostgreSQL container")

    log_text = (stdout + ("\n" + stderr if stderr else "")).replace(dsn, "[TEST_DATABASE_DSN]") if dsn else stdout + ("\n" + stderr if stderr else "")
    log_text = log_text.replace(password, "[REDACTED]")
    (case_dir / "tests.log").write_text(log_text, encoding="utf-8")
    passed = tests_passed and cleanup_succeeded and not errors
    case_result = EvalCaseResult(
        case_id="postgres-persistence-smoke",
        status="passed" if passed else "failed",
        agent_exit_code=0 if tests_passed else 1,
        patch_apply=True,
        target_tests_passed=tests_passed,
        regression_tests_passed=None,
        retrieval_hit_at_k=None,
        tool_recovery_rate=None,
        input_tokens=None,
        output_tokens=None,
        total_tokens=None,
        agent_latency_ms=test_latency,
        target_test_latency_ms=test_latency,
        regression_test_latency_ms=0,
        errors=errors,
        artifacts={"tests": "cases/postgres-persistence-smoke/tests.log"},
        metadata={
            "database_evaluation": {
                "backend": "PostgreSQL",
                "image": args.image,
                "host_binding": "127.0.0.1 only",
                "localhost_only": True,
                "ephemeral_instance": True,
                "database_name": database_name,
                "database_version": database_version,
                "user": "eval_runner",
                "persistence_components": ["business_store", "langgraph_store", "checkpointer"],
                "component_results": {
                    "business_store": tests_passed,
                    "langgraph_store": tests_passed,
                    "checkpointer": tests_passed,
                },
                "cleanup_succeeded": cleanup_succeeded,
            }
        },
    )
    report = EvalReport(
        report_id=uuid4().hex[:16], mode="database", repository="coding-agent",
        cases=[case_result],
        config={
            "framework_source_sha": subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, capture_output=True,
                text=True, encoding="utf-8", errors="replace", check=False, shell=False,
            ).stdout.strip(),
            "framework_source_dirty_patch_sha256": _source_fingerprint(),
            "database_image": args.image,
            "runner_version": "postgres-1",
        },
        created_at=datetime.now(UTC).isoformat(),
    )
    data = report.to_dict()
    data["summary"]["total_latency_ms"] = int((time.perf_counter() - started) * 1000)
    (output_dir / "report.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_report_data(data, output_dir)
    print(json.dumps({"output_dir": str(output_dir), "status": case_result.status, "summary": data["summary"]}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
