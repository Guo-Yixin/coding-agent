from taskboard import filter_by_priority


def test_filter_accepts_one_or_many_priorities_case_insensitively():
    tasks = [
        {"id": 1, "priority": "HIGH"},
        {"id": 2, "priority": "medium"},
        {"id": 3, "priority": "low"},
        {"id": 4, "priority": "urgent"},
    ]
    assert [task["id"] for task in filter_by_priority(tasks, "high")] == [1, 4]
    assert [task["id"] for task in filter_by_priority(tasks, ["medium", "backlog"])] == [2, 3]


def test_none_returns_all_and_unknown_matches_missing_priority_without_mutating_input():
    tasks = [{"id": 1}, {"id": 2, "priority": None}, {"id": 3, "priority": "later"}]
    snapshot = [dict(task) for task in tasks]
    assert filter_by_priority(tasks) == tasks
    assert [task["id"] for task in filter_by_priority(tasks, "unknown")] == [1, 2]
    assert tasks == snapshot
