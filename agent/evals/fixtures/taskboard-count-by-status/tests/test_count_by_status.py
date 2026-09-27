from taskboard import count_by_status


def test_counts_normalized_statuses_and_keeps_first_seen_order():
    tasks = [
        {"id": 1, "status": "Open"},
        {"id": 2, "status": "done"},
        {"id": 3, "status": " OPEN "},
        {"id": 4},
        {"id": 5, "status": None},
    ]
    assert count_by_status(tasks) == {"open": 2, "done": 1, "unknown": 2}


def test_empty_input_has_no_groups():
    assert count_by_status([]) == {}
