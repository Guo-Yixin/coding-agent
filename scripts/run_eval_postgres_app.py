from __future__ import annotations

import argparse
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

from agent.evals import EvalCase, EvalRunner
from agent.evals.reporting import write_report_data


def _docker(*args: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout, check=False, shell=False,
    )


def _wait_for_database(dsn: str, timeout: int) -> dict[str, str]:
    import psycopg

    deadline = time.monotonic() + min(timeout, 120)
    last_error = "not attempted"
    while time.monotonic() < deadline:
        try:
            with psycopg.connect(dsn, connect_timeout=3) as connection:
                version, database, role = connection.execute(
                    "SELECT version(), current_database(), current_user"
                ).fetchone()
            if not str(database).startswith("coding_agent_eval_") or role != "eval_runner":
                raise RuntimeError("Disposable PostgreSQL identity did not match expected eval database and role")
            return {"version": str(version).splitlines()[0], "database": str(database), "role": str(role)}
        except psycopg.Error as exc:
            last_error = type(exc).__name__
            time.sleep(2)
    raise RuntimeError(f"Disposable PostgreSQL did not become ready; last error: {last_error}")


def _refresh_report(output: Path, *, instance: dict[str, object], cleanup_succeeded: bool) -> bool:
    report_path = output / "report.json"
    if not report_path.is_file():
        return False
    data = json.loads(report_path.read_text(encoding="utf-8"))
    data.setdefault("config", {})["postgres_instance"] = {
        **instance,
        "localhost_only": True,
        "ephemeral": True,
        "cleanup_succeeded": cleanup_succeeded,
    }
    if not cleanup_succeeded:
        for case in data.get("cases", []):
            case["status"] = "failed"
            case.setdefault("errors", []).append("Disposable PostgreSQL container cleanup could not be verified")
    cases = data.get("cases", [])
    passed = sum(case.get("status") == "passed" for case in cases)
    summary = data.setdefault("summary", {})
    summary["passed_count"] = passed
    summary["failed_count"] = len(cases) - passed
    (output / "report.json").write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "run.json").write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_report_data(data, output)
    return passed == len(cases) and cleanup_succeeded


def main() -> int:
    parser = argparse.ArgumentParser(description="Run full app Agent Eval against a disposable PostgreSQL instance")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--agent-ref", required=True)
    parser.add_argument("--image", default="postgres:18")
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()

    if not re.fullmatch(r"postgres:[0-9]+(?:-alpine)?", args.image):
        raise SystemExit("--image must be an official postgres:<version> image tag")
    output = args.output.expanduser().resolve()
    if output == PROJECT_ROOT or PROJECT_ROOT in output.parents:
        raise SystemExit("PostgreSQL app Eval output must stay outside the coding-agent source repository")
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"Refusing to overwrite non-empty output directory: {output}")
    dataset = args.dataset.expanduser().resolve()
    cases = [
        EvalCase.from_dict(json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(dataset.glob("*.json"))
    ]
    if not cases:
        raise SystemExit(f"No cases found in {dataset}")
    for case in cases:
        if case.metadata.get("adapter") != "app" or case.metadata.get("persistence_backend") != "postgres":
            raise SystemExit(f"Case {case.case_id} must declare adapter=app and persistence_backend=postgres")

    output.mkdir(parents=True, exist_ok=True)
    suffix = uuid4().hex[:10]
    container_name = f"coding-agent-eval-app-pg-{suffix}"
    database_name = f"coding_agent_eval_{suffix}"
    password = secrets.token_urlsafe(32)
    dsn = ""
    container_started = False
    cleanup_succeeded = False
    run_failed = False
    database_identity: dict[str, object] = {
        "image": args.image,
        "container_name": container_name,
        "database_name": database_name,
        "user": "eval_runner",
        "port_binding": "127.0.0.1 only",
    }
    prior_dsn = os.environ.get("CODING_AGENT_EVAL_POSTGRES_DSN")
    try:
        info = _docker("info", "--format", "{{.ServerVersion}}", timeout=20)
        if info.returncode != 0:
            raise RuntimeError("Docker daemon is unavailable for PostgreSQL app Eval")
        launched = _docker(
            "run", "-d", "--rm", "--name", container_name,
            "-e", "POSTGRES_USER=eval_runner",
            "-e", f"POSTGRES_PASSWORD={password}",
            "-e", f"POSTGRES_DB={database_name}",
            "-p", "127.0.0.1::5432", args.image,
            timeout=60,
        )
        if launched.returncode != 0:
            raise RuntimeError("Could not start the task-owned disposable PostgreSQL container")
        container_started = True
        port_result = _docker("port", container_name, "5432/tcp", timeout=15)
        match = re.fullmatch(r"127\.0\.0\.1:(\d+)\s*", port_result.stdout.strip())
        if port_result.returncode != 0 or not match:
            raise RuntimeError("PostgreSQL port was not mapped exclusively to loopback")
        port = int(match.group(1))
        import psycopg
        from psycopg.conninfo import make_conninfo

        dsn = make_conninfo(
            host="127.0.0.1", port=port, dbname=database_name,
            user="eval_runner", password=password,
        )
        database_identity.update(_wait_for_database(dsn, args.timeout))
        os.environ["CODING_AGENT_EVAL_POSTGRES_DSN"] = dsn
        runner = EvalRunner(
            output_dir=output,
            mode="real",
            env_file=args.env_file,
            agent_source_root=PROJECT_ROOT,
            agent_revision=args.agent_ref,
        )
        report = runner.run(cases, repository=args.repo.expanduser().resolve())
        print(json.dumps({"report_id": report.report_id, "status": report.to_dict()["summary"]}, ensure_ascii=False))
    except Exception as exc:
        run_failed = True
        message = str(exc)
        for secret in (dsn, password):
            if secret:
                message = message.replace(secret, "[REDACTED]")
        (output / "postgres-app-runner-error.txt").write_text(
            f"{type(exc).__name__}: {message}\n", encoding="utf-8"
        )
        print(f"PostgreSQL app Eval failed: {type(exc).__name__}: {message}", file=sys.stderr)
    finally:
        if container_started:
            removed = _docker("rm", "-f", container_name, timeout=30)
            if removed.returncode == 0:
                cleanup_succeeded = True
            else:
                inspect = _docker("inspect", container_name, timeout=10)
                cleanup_succeeded = inspect.returncode != 0
        if prior_dsn is None:
            os.environ.pop("CODING_AGENT_EVAL_POSTGRES_DSN", None)
        else:
            os.environ["CODING_AGENT_EVAL_POSTGRES_DSN"] = prior_dsn
        if output.joinpath("report.json").exists():
            _refresh_report(output, instance=database_identity, cleanup_succeeded=cleanup_succeeded)
    return 0 if (
        not run_failed
        and cleanup_succeeded
        and output.joinpath("report.json").is_file()
        and json.loads(output.joinpath("report.json").read_text(encoding="utf-8"))["summary"].get("passed_count") == len(cases)
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
