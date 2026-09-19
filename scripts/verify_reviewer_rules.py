from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_RULES = ROOT / "agent" / "reviewer_rules" / "default_review_rules.md"
CODE_REVIEW_SKILL = ROOT / "agent" / "skills" / "code-review" / "SKILL.md"
WORKSPACE_RULES = Path("B:/ai_workspace/policies/review_rules.md")


def assert_contains(path: Path, expected: list[str]) -> None:
    text = path.read_text(encoding="utf-8")
    missing = [item for item in expected if item not in text]
    if missing:
        raise AssertionError(f"{path} 缺少关键内容: {missing}")


def main() -> None:
    if not DEFAULT_RULES.exists():
        raise AssertionError(f"默认审查规则不存在: {DEFAULT_RULES}")
    if not CODE_REVIEW_SKILL.exists():
        raise AssertionError(f"code-review skill 不存在: {CODE_REVIEW_SKILL}")

    assert_contains(
        DEFAULT_RULES,
        ["critical", "high", "SQL 注入", "XSS", "Gitee", "Windows"],
    )
    assert_contains(
        CODE_REVIEW_SKILL,
        ["load_default_review_rules", "get_review_diff_summary", "add_review_finding", "中文"],
    )

    # 默认规则工具只负责读取项目内置规则，不再读取工作区和仓库规则。
    # 工作区规则、仓库规则由 code-review skill 使用原生 read_file 读取。
    from agent.tools.reviewer_tools import load_default_review_rules

    result = load_default_review_rules.invoke({})
    sources = result["sources"]
    if "/policies/review_rules.md" in sources:
        raise AssertionError("默认规则工具不应读取工作区 review_rules.md")
    if "agent/reviewer_rules/default_review_rules.md" not in sources:
        raise AssertionError("默认规则工具必须加载项目内置默认规则")

    print("reviewer rules verification passed")


if __name__ == "__main__":
    main()
