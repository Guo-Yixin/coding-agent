from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.evals.public_export import export_public_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a sanitized, shareable Agent Eval report bundle")
    parser.add_argument("run_dir", type=Path, help="Completed Eval run directory containing report.json")
    parser.add_argument("output_dir", type=Path, help="Destination for the public report and safe text artifacts")
    args = parser.parse_args()
    result = export_public_report(args.run_dir, args.output_dir)
    print(f"Exported {result['cases']} case(s): {args.output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
