from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    sys.path.insert(0, str(Path(sys.argv[1]).resolve()))
    from taskboard import merge_task_updates

    tasks = [{"id": "a", "title": "A"}, {"id": "b", "title": "B", "tags": ["x"]}]
    before = [{**task, **({"tags": list(task["tags"])} if "tags" in task else {})} for task in tasks]
    updated = merge_task_updates(iter(tasks), "b", {"title": "B2", "priority": "high"})
    assert updated == [{"id": "a", "title": "A"}, {"id": "b", "title": "B2", "tags": ["x"], "priority": "high"}]
    assert updated[0] is tasks[0] and updated[1] is not tasks[1]
    assert tasks == before
    for bad_updates in ({"id": "other"}, {"id": None}):
        try:
            merge_task_updates(tasks, "b", bad_updates)
        except ValueError:
            continue
        raise AssertionError("changing the task id must be rejected")
    try:
        merge_task_updates(tasks, "missing", {"title": "x"})
    except KeyError:
        pass
    else:
        raise AssertionError("missing id must raise KeyError")


if __name__ == "__main__":
    main()
