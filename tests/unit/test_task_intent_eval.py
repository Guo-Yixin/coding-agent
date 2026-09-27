from __future__ import annotations

import pytest

from agent.core.task_intent import _apply_security_guard


@pytest.mark.parametrize(
    "prompt",
    [
        "请先使用 hybrid_code_search 定位 search_tasks，再实现大小写不敏感标题搜索并补充 tests/test_search_tasks.py。",
        "请先使用 hybrid_code_search 定位 filter_by_status，再修复大小写不敏感筛选并补充测试。",
        "请先使用 hybrid_code_search 定位 sort_by_priority，再新增 urgent/backlog 别名并补充测试。",
        "请先使用 hybrid_code_search 定位 taskboard 的公开 API，再实现 group_tasks_by_status 并通过 taskboard 包导出。不要修改其他文件。",
        "请先使用 hybrid_code_search 定位现有筛选代码，再新增公开函数 select_tasks 并补充测试。不要修改其他文件。",
        "Please inspect the repository, implement the requested function, and add focused tests.",
    ],
)
@pytest.mark.parametrize("model_prediction", ["analysis", "planning"])
def test_direct_coding_request_overrides_analysis_or_planning_prediction(prompt: str, model_prediction: str) -> None:
    assert _apply_security_guard(prompt, model_prediction) == "coding"


def test_explicit_read_only_request_remains_read_only_even_with_coding_words() -> None:
    prompt = "请只给我一份实现方案，先不要修改代码。"
    assert _apply_security_guard(prompt, "coding") == "planning"


def test_file_scope_restriction_does_not_turn_coding_request_into_read_only() -> None:
    prompt = "请修复 filter_by_status，并补充测试。不要修改其他文件。"
    assert _apply_security_guard(prompt, "analysis") == "coding"


def test_explicit_no_code_request_remains_read_only_with_scope_words() -> None:
    prompt = "只分析这个问题，不要修改代码，也不要修改其他文件。"
    assert _apply_security_guard(prompt, "coding") == "analysis"


def test_analysis_question_about_implementation_is_not_a_direct_coding_request() -> None:
    prompt = "分析一下这个功能应该如何实现，暂时只解释思路。"
    assert _apply_security_guard(prompt, "analysis") == "analysis"

