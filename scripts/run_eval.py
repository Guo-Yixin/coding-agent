from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.evals import EvalCase, EvalRunner
from agent.evals.sandbox_runner import SandboxEvalRunner


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Run reproducible Agent Eval cases")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--env-file", type=Path, help="Read model credentials from this file for the isolated Agent child; it is never copied into the Eval workspace")
    parser.add_argument("--mode", choices=("fake", "real", "sandbox"), default="real")
    args = parser.parse_args()
    repository = args.repo.resolve()
    configured_root = os.environ.get("CODING_AGENT_EVAL_ROOT", "").strip()
    if configured_root:
        eval_root = Path(configured_root)
    else:
        common_dir = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=repository, capture_output=True, text=True, check=False)
        common_path = Path(common_dir.stdout.strip()) if common_dir.returncode == 0 else repository / ".git"
        if not common_path.is_absolute():
            common_path = (repository / common_path).resolve()
        source_root = common_path.resolve().parent if common_path.name == ".git" else repository
        eval_root = source_root.parent / "coding-agent-eval-runs"
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    output = args.output or eval_root / "runs" / run_id
    cases: list[EvalCase] = []
    for path in sorted(args.dataset.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        values = payload if isinstance(payload, list) else [payload]
        cases.extend(EvalCase.from_dict(value) for value in values)
    if not cases:
        raise SystemExit(f"No JSON cases found in dataset: {args.dataset}")
    if args.mode == "real" and any(not case.base_ref for case in cases):
        fetched = subprocess.run(["git", "fetch", "origin", "main"], cwd=repository, capture_output=True, text=True, check=False)
        if fetched.returncode != 0:
            raise SystemExit(f"Could not refresh origin/main for cases without base_ref: {fetched.stderr[-1000:]}")
    if args.mode == "real":
        for case in cases:
            ref = case.base_ref or "origin/main"
            resolved = subprocess.run(
                ["git", "cat-file", "-e", f"{ref}^{{commit}}"], cwd=repository,
                capture_output=True, text=True, check=False,
            )
            if resolved.returncode != 0:
                raise SystemExit(f"Case {case.case_id} target commit is unavailable locally: {ref}")
    runner = SandboxEvalRunner(output_dir=output) if args.mode == "sandbox" else EvalRunner(
        output_dir=output,
        mode=args.mode,
        env_file=args.env_file,
        agent_source_root=PROJECT_ROOT,
    )
    report = runner.run(cases, repository=repository)
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.to_dict()["summary"]["passed_count"] == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
