from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    root = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(root))
    from taskboard.tasks import search_tasks

    tasks = [{"id": 1, "title": "Fix API timeout"}, {"id": 2, "title": "Write API docs"}, {"id": 3}]
    assert [item["id"] for item in search_tasks(tasks, "api")] == [1, 2]
    assert search_tasks(tasks, "") == tasks
    assert search_tasks(tasks, "not found") == []
    assert tasks[0]["title"] == "Fix API timeout"


if __name__ == "__main__":
    main()
