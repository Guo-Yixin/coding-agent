from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.core.middleware.run_limits import AgentRunLimits
from agent.core.task_intent import classify_task_kind, is_read_only_task
from agent.prompt import get_system_prompt


def main() -> None:
    review_prompts = [
        "请审查这个 PR：https://gitee.com/clumsypsc/test_coding_repo/pulls/8",
        "帮我做一次代码审查，只 review，不要修改代码",
        "请调用 reviewer 检查 Pull Request",
        "请帮我审查这个PR：https://gitee.com/msb-goldbin/abc-test/pulls/3，只做代码 review，不要修改代码。请读取 PR diff，审查规则，并输出中文审查报告。",
    ]
    for prompt in review_prompts:
        task_kind = classify_task_kind(prompt)
        assert task_kind == "review", f"应识别为 review: {prompt!r} -> {task_kind}"
        assert is_read_only_task(task_kind), "review 必须是只读任务"

    review_fix_plan_prompts = [
        "请读取 /reviews/ai_coding/pr-8-review.md，并结合 review findings 生成修复方案，先不要修改代码",
        "根据审查报告和结构化 findings，给我一个修复方案",
        "请读取 /reviews/abc-test/pr-3-review.md，并结合 review findings 生成修复方案，先不要修改代码。",
    ]
    for prompt in review_fix_plan_prompts:
        task_kind = classify_task_kind(prompt)
        assert task_kind == "planning", f"应识别为 planning: {prompt!r} -> {task_kind}"
        assert is_read_only_task(task_kind), "review 修复方案阶段必须是只读任务"

    review_fix_coding_prompts = [
        "确认实施这个 review 修复方案",
        "根据审查报告开始修改代码",
    ]
    for prompt in review_fix_coding_prompts:
        task_kind = classify_task_kind(prompt)
        assert task_kind == "coding", f"应识别为 coding: {prompt!r} -> {task_kind}"

    system_prompt = get_system_prompt("review")
    for expected in ["code_reviewer", "code-review", "load_default_review_rules", "中文审查报告"]:
        assert expected in system_prompt, f"review 系统提示词缺少: {expected}"

    planning_prompt = get_system_prompt("planning")
    for expected in ["/reviews/*.md", "list_review_findings", "结构化 findings", "修复方案"]:
        assert expected in planning_prompt, f"planning 系统提示词缺少 review 修复规则: {expected}"

    limits = AgentRunLimits.from_env("review")
    assert limits.max_tool_calls >= 120
    assert limits.max_seconds >= 900

    print("review task kind verification passed")


if __name__ == "__main__":
    main()
