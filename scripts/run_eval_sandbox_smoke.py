from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.evals import EvalCase
from agent.evals.reporting import write_report_data
from agent.evals.sandbox_runner import SandboxEvalRunner
from agent.sandbox import OpenSandboxConfig, OpenSandboxExecutor, SandboxFile


def _run_safety_probes(config: OpenSandboxConfig) -> dict[str, object]:
    """Check client-side upload traversal rejection and server command timeout."""

    timeout_config = replace(config, command_timeout_seconds=1, keep_sandbox=False)
    executor = OpenSandboxExecutor(timeout_config)
    results: dict[str, object] = {
        "path_traversal_rejected": False,
        "timeout_enforced": False,
        "cleanup_succeeded": False,
    }
    started = time.perf_counter()
    try:
        executor.start()
        try:
            executor.upload_files([SandboxFile(path="../escape.txt", data=b"must-not-upload")])
        except ValueError as exc:
            results["path_traversal_rejected"] = "Unsafe OpenSandbox upload path" in str(exc)

        command_started = time.perf_counter()
        try:
            result = executor.execute("sleep 5", cwd=".")
            elapsed = time.perf_counter() - command_started
            results["timeout_enforced"] = result.exit_code not in (0, None) and elapsed < 4
        except Exception as exc:
            elapsed = time.perf_counter() - command_started
            results["timeout_enforced"] = elapsed < 4 and any(
                token in str(exc).lower() for token in ("timeout", "timed out", "deadline", "cancel")
            )
            results["timeout_error"] = type(exc).__name__
        results["timeout_latency_ms"] = int(elapsed * 1000)
    except Exception as exc:
        results["probe_error"] = str(exc)[:500]
    finally:
        try:
            executor.close()
            results["cleanup_succeeded"] = True
        except Exception as exc:
            results["cleanup_error"] = str(exc)[:500]
        results["probe_latency_ms"] = int((time.perf_counter() - started) * 1000)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a real OpenSandbox smoke evaluation with a synthetic, credential-free fixture"
    )
    parser.add_argument("--output", type=Path, help="New output directory outside the source repository")
    parser.add_argument(
        "--image",
        default=os.environ.get("OPEN_SANDBOX_IMAGE", "coding-agent-eval-alpine-git:3.20"),
        help="A Linux image with git and a POSIX shell (build scripts/opensandbox-smoke.Dockerfile for the smoke image)",
    )
    args = parser.parse_args()

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    eval_root = Path(os.environ.get("CODING_AGENT_EVAL_ROOT", PROJECT_ROOT.parent / "coding-agent-eval-runs"))
    output_dir = (args.output or eval_root / "runs" / run_id / "opensandbox-smoke").expanduser().resolve()
    if output_dir == PROJECT_ROOT or PROJECT_ROOT in output_dir.parents:
        raise SystemExit("OpenSandbox smoke output must be outside the coding-agent source repository")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise SystemExit(f"Refusing to overwrite non-empty output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    # This tiny fixture proves the sandbox upload filter with harmless sentinel data.
    fixture = output_dir / "fixture-repository"
    fixture.mkdir()
    (fixture / "baseline.txt").write_bytes(b"baseline")
    (fixture / ".env").write_text("API_KEY=sentinel-not-a-secret\n", encoding="utf-8")
    (fixture / "store.sqlite").write_bytes(b"sqlite-sentinel")

    case = EvalCase(
        case_id="opensandbox-isolation-smoke",
        prompt="Create result.txt containing sandbox-eval-ok.",
        target_tests=[["sh", "-c", "test \"$(cat result.txt)\" = sandbox-eval-ok"]],
        regression_tests=[["sh", "-c", "test \"$(cat baseline.txt)\" = baseline"]],
        oracle_tests=[[
            "sh", "-c",
            "test ! -e .env && test ! -e store.sqlite && test -f result.txt",
        ]],
        agent_command=["sh", "-c", "printf 'sandbox-eval-ok\\n' > result.txt"],
        requires_patch=True,
        timeout_seconds=90,
        allowed_files=["result.txt"],
        metadata={"required_changed_files": ["result.txt"]},
    )
    config = OpenSandboxConfig.from_env()
    config = OpenSandboxConfig(
        domain=config.domain,
        api_key=config.api_key,
        image=args.image,
        cpu=config.cpu,
        memory=config.memory,
        timeout_seconds=config.timeout_seconds,
        command_timeout_seconds=config.command_timeout_seconds,
        max_upload_bytes=config.max_upload_bytes,
        keep_sandbox=False,
        use_server_proxy=config.use_server_proxy,
    )
    report = SandboxEvalRunner(output_dir=output_dir, config=config).run([case], repository=fixture)
    safety = _run_safety_probes(config)
    result = report.cases[0]
    result.metadata["sandbox"]["safety_probes"] = safety
    required_checks = ("path_traversal_rejected", "timeout_enforced", "cleanup_succeeded")
    if not all(safety.get(name) is True for name in required_checks):
        result.status = "failed"
        result.errors.extend(
            f"OpenSandbox safety probe failed: {name}"
            for name in required_checks
            if safety.get(name) is not True
        )
    report_data = report.to_dict()
    report_data["summary"]["total_latency_ms"] += int(safety.get("probe_latency_ms", 0))
    (output_dir / "report.json").write_text(
        json.dumps(report_data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    write_report_data(report_data, output_dir)
    (output_dir / "smoke-summary.json").write_text(
        json.dumps({"output_dir": str(output_dir), "summary": report_data["summary"]}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"output_dir": str(output_dir), "summary": report_data["summary"]}, ensure_ascii=False))
    return 0 if report_data["summary"]["passed_count"] == 1 else 1


if __name__ == "__main__":
    raise SystemExit(main())
