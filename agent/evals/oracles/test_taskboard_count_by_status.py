from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    sys.path.insert(0, str(Path(sys.argv[1]).resolve()))
    from taskboard import count_by_status

    tasks = [
        {"id": 1, "status": " Open "}, {"id": 2, "status": "DONE"},
        {"id": 3, "status": "open"}, {"id": 4}, {"id": 5, "status": "  "},
        {"id": 6, "status": None}, {"id": 7, "status": 7},
    ]
    original = [dict(task) for task in tasks]
    result = count_by_status(iter(tasks))
    assert result == {"open": 2, "done": 1, "unknown": 3, "7": 1}
    assert list(result) == ["open", "done", "unknown", "7"]
    assert tasks == original


if __name__ == "__main__":
    main()
