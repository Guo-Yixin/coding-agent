from __future__ import annotations

import sys
from datetime import date
from pathlib import Path


def main() -> None:
    sys.path.insert(0, str(Path(sys.argv[1]).resolve()))
    from taskboard import find_overdue_tasks

    tasks = [
        {"id": 1, "due_date": "2024-02-28", "status": "open"},
        {"id": 2, "due_date": "2024-02-29", "status": "in progress"},
        {"id": 3, "due_date": "2024-03-01", "status": "open"},
        {"id": 4, "due_date": "2024-02-01", "status": "cancelled"},
        {"id": 5, "due_date": "bad-date", "status": "open"},
        {"id": 6, "status": "open"},
    ]
    snapshot = [dict(task) for task in tasks]
    assert [task["id"] for task in find_overdue_tasks(tasks, today=date(2024, 3, 1))] == [1, 2]
    assert [task["id"] for task in find_overdue_tasks(tasks, today="2024-02-29")] == [1]
    assert find_overdue_tasks([], today="2024-02-29") == []
    try:
        find_overdue_tasks(tasks, today="2024-13-01")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid today must raise ValueError")
    assert tasks == snapshot


if __name__ == "__main__":
    main()
