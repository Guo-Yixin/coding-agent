from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    root = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(root))
    from taskboard.tasks import filter_by_status

    tasks = [{"id": 1, "status": "open"}, {"id": 2, "status": "done"}, {"id": 3, "status": "OPEN"}]
    original = [dict(item) for item in tasks]
    assert [item["id"] for item in filter_by_status(tasks, "Open")] == [1, 3]
    assert filter_by_status(tasks, None) == tasks
    assert filter_by_status(tasks, "blocked") == []
    assert tasks == original


if __name__ == "__main__":
    main()
