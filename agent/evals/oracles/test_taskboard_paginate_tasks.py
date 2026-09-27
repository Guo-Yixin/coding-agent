from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    sys.path.insert(0, str(Path(sys.argv[1]).resolve()))
    from taskboard import paginate_tasks

    tasks = [{"id": i} for i in range(8)]
    snapshot = [dict(task) for task in tasks]
    assert [row["id"] for row in paginate_tasks(iter(tasks), page=2, page_size=3)] == [3, 4, 5]
    assert paginate_tasks(tasks, page=9, page_size=3) == []
    for page, size in ((0, 1), (1, 0), (True, 1), (1, 1.2)):
        try:
            paginate_tasks(tasks, page=page, page_size=size)
        except ValueError:
            continue
        raise AssertionError(f"invalid pagination accepted: page={page!r}, size={size!r}")
    assert tasks == snapshot


if __name__ == "__main__":
    main()
