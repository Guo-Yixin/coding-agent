from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.core.graph import build_agent
from agent.core.settings import SKILLS_DIR
from agent.prompt import get_system_prompt


def main() -> None:
    """验证 Gitee 仓库分析和复杂编码实施 skill 已存在，并被提示词接入。"""

    skill_path = SKILLS_DIR / "repo-bootstrap-analysis" / "SKILL.md"
    if not skill_path.exists():
        raise AssertionError(f"缺少 skill 文件：{skill_path}")

    content = skill_path.read_text(encoding="utf-8")
    required_terms = [
        "Gitee",
        "/projects/<repo>",
        "execute",
        "git clone https://gitee.com/<owner>/<repo>.git",
        "README.md",
        "测试方式",
        "是否确认实施该方案？",
    ]
    missing = [term for term in required_terms if term not in content]
    if missing:
        raise AssertionError(f"repo-bootstrap-analysis skill 缺少关键内容：{missing}")

    prompt = get_system_prompt("planning")
    if "repo-bootstrap-analysis" not in prompt or "fetch_url" not in prompt:
        raise AssertionError("系统提示词没有包含 repo-bootstrap-analysis 或 fetch_url 使用规则")

    coding_skill_path = SKILLS_DIR / "ai-coding-implementation" / "SKILL.md"
    if not coding_skill_path.exists():
        raise AssertionError(f"缺少 skill 文件：{coding_skill_path}")

    coding_content = coding_skill_path.read_text(encoding="utf-8")
    coding_required_terms = [
        "复杂业务代码实施流程",
        "不要反复读取同一个文件",
        "Git 收尾",
        "open_gitee_pull_request",
        "工具调用额度控制",
    ]
    coding_missing = [term for term in coding_required_terms if term not in coding_content]
    if coding_missing:
        raise AssertionError(f"ai-coding-implementation skill 缺少关键内容：{coding_missing}")

    coding_prompt = get_system_prompt("coding")
    if "ai-coding-implementation" not in coding_prompt:
        raise AssertionError("系统提示词没有要求 coding 使用 ai-coding-implementation")

    agent = build_agent("verify-repo-bootstrap-skill", task_kind="planning")
    if type(agent).__name__ != "CompiledStateGraph":
        raise AssertionError(f"build_agent 返回类型异常：{type(agent).__name__}")

    print("repo bootstrap skill verification passed")


if __name__ == "__main__":
    main()
