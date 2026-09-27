from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    root = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(root))
    from taskboard import select_tasks

    tasks = [
        {"id": 1, "title": "Fix API timeout", "status": "Open"},
        {"id": 2, "title": "Write API docs", "status": "done"},
        {"id": 3, "title": "API migration", "status": "OPEN"},
        {"id": 4, "status": "open"},
        {"id": 5, "title": "Fix api client", "status": "closed"},
    ]
    original = [dict(task) for task in tasks]
    assert [item["id"] for item in select_tasks(tasks, status="open", query="api")] == [1, 3]
    assert [item["id"] for item in select_tasks(tasks, query="API")] == [1, 2, 3, 5]
    assert [item["id"] for item in select_tasks(tasks, status="OPEN")] == [1, 3, 4]
    assert [item["id"] for item in select_tasks(tasks)] == [1, 2, 3, 4, 5]
    assert tasks == original


if __name__ == "__main__":
    main()
