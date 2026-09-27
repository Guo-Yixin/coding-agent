from datetime import date

from taskboard import find_overdue_tasks


def test_returns_only_unfinished_tasks_strictly_before_today_in_input_order():
    tasks = [
        {"id": 1, "due_date": "2025-01-01", "status": "open"},
        {"id": 2, "due_date": "2025-01-02", "status": "open"},
        {"id": 3, "due_date": "2024-12-31", "status": "DONE"},
        {"id": 4, "due_date": "2024-12-30", "status": "open"},
    ]
    assert [task["id"] for task in find_overdue_tasks(tasks, today=date(2025, 1, 2))] == [1, 4]


def test_ignores_missing_or_invalid_due_dates_and_accepts_iso_today():
    tasks = [{"id": 1}, {"id": 2, "due_date": "not-a-date"}, {"id": 3, "due_date": "2024-01-01"}]
    assert [task["id"] for task in find_overdue_tasks(tasks, today="2024-02-01")] == [3]
