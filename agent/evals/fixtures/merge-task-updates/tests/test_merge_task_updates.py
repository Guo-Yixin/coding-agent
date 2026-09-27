import pytest

from taskboard import merge_task_updates


def test_updates_one_matching_task_without_mutating_the_input():
    tasks = [{"id": 1, "title": "First"}, {"id": 2, "title": "Old", "status": "open"}]
    snapshot = [dict(task) for task in tasks]
    updated = merge_task_updates(tasks, 2, {"title": "New", "status": "done"})
    assert updated == [{"id": 1, "title": "First"}, {"id": 2, "title": "New", "status": "done"}]
    assert updated is not tasks
    assert updated[1] is not tasks[1]
    assert tasks == snapshot


def test_update_keeps_identifier_and_rejects_missing_task():
    with pytest.raises(ValueError):
        merge_task_updates([{"id": 1}], 1, {"id": 2})
    with pytest.raises(KeyError):
        merge_task_updates([], 9, {"title": "missing"})
