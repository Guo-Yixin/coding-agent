from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def main() -> None:
    root = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(root))
    from taskboard import group_tasks_by_status

    tasks = [
        {"id": "a", "status": "Open"},
        {"id": "b", "status": "done"},
        {"id": "c", "status": "OPEN"},
        {"id": "d"},
        {"id": "e", "status": None},
    ]
    original = [dict(task) for task in tasks]
    groups = group_tasks_by_status(tasks)
    assert list(groups) == ["open", "done", "unknown"]
    assert [[item["id"] for item in group] for group in groups.values()] == [["a", "c"], ["b"], ["d", "e"]]
    assert tasks == original
    assert all(item is task for group in groups.values() for item in group for task in tasks if item["id"] == task["id"])


if __name__ == "__main__":
    main()
