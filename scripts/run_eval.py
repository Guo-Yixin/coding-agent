from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent.evals import EvalCase, EvalRunner


def main() -> int:
    parser = argparse.ArgumentParser(description="Run reproducible Agent Eval cases")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("fake", "real"), default="fake")
    args = parser.parse_args()
    cases: list[EvalCase] = []
    for path in sorted(args.dataset.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        values = payload if isinstance(payload, list) else [payload]
        cases.extend(EvalCase.from_dict(value) for value in values)
    report = EvalRunner(output_dir=args.output, mode=args.mode).run(cases, repository=args.repo.resolve())
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.to_dict()["summary"]["passed_count"] == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
