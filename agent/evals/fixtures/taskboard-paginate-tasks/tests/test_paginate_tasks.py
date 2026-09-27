import pytest

from taskboard import paginate_tasks


def test_pages_are_one_based_and_preserve_input_order():
    tasks = [{"id": index} for index in range(1, 6)]
    assert [item["id"] for item in paginate_tasks(tasks, page=1, page_size=2)] == [1, 2]
    assert [item["id"] for item in paginate_tasks(tasks, page=2, page_size=2)] == [3, 4]
    assert [item["id"] for item in paginate_tasks(tasks, page=3, page_size=2)] == [5]


def test_pagination_accepts_iterables_and_returns_empty_for_pages_past_the_end():
    assert paginate_tasks(({"id": i} for i in range(3)), page=4, page_size=2) == []


@pytest.mark.parametrize("page,page_size", [(0, 2), (-1, 2), (1, 0), (1, -3), (True, 2), (1, 1.5)])
def test_pagination_rejects_non_positive_or_non_integer_arguments(page, page_size):
    with pytest.raises(ValueError):
        paginate_tasks([], page=page, page_size=page_size)
