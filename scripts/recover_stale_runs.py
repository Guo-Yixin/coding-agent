"""恢复 PostgreSQL 中因 worker 崩溃而遗留的运行。"""

from __future__ import annotations

import json

from agent.core.graph import get_store
from agent.core.worker import WorkerLeaseManager


def main() -> int:
    run_ids = WorkerLeaseManager(get_store()).recover_stale_runs()
    print(json.dumps({"recovered_count": len(run_ids), "run_ids": run_ids}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
