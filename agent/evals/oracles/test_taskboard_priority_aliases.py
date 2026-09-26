from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    root = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(root))
    from taskboard.tasks import sort_by_priority

    tasks = [
        {"id": 1, "priority": "low"},
        {"id": 2, "priority": "URGENT"},
        {"id": 3, "priority": "backlog"},
        {"id": 4, "priority": "high"},
        {"id": 5, "priority": "unknown"},
        {"id": 6, "priority": "unknown"},
        {"id": 7},
    ]
    assert [item["id"] for item in sort_by_priority(tasks)] == [2, 4, 1, 3, 5, 6, 7]


if __name__ == "__main__":
    main()
