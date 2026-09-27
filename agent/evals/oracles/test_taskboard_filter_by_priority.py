from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    sys.path.insert(0, str(Path(sys.argv[1]).resolve()))
    from taskboard import filter_by_priority

    tasks = [
        {"id": 1, "priority": "URGENT"}, {"id": 2, "priority": "High"},
        {"id": 3, "priority": "backlog"}, {"id": 4, "priority": "LOW"},
        {"id": 5, "priority": "unknown"}, {"id": 6}, {"id": 7, "priority": None},
    ]
    snapshot = [dict(task) for task in tasks]
    assert [task["id"] for task in filter_by_priority(tasks, "high")] == [1, 2]
    assert [task["id"] for task in filter_by_priority(tasks, ["low", "urgent"])] == [1, 3, 4]
    assert [task["id"] for task in filter_by_priority(tasks, "unknown")] == [5, 6, 7]
    assert filter_by_priority(tasks, []) == []
    assert filter_by_priority(tasks) == tasks
    assert tasks == snapshot


if __name__ == "__main__":
    main()
