from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.evals.comparison import compare_report_files


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare Agent Eval JSON reports")
    parser.add_argument("--reports", nargs="+", type=Path, required=True, help="One or more report.json paths")
    parser.add_argument("--output", type=Path, required=True, help="Output HTML path")
    args = parser.parse_args()
    output = compare_report_files(args.reports, args.output)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
