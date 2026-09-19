from __future__ import annotations

import hashlib
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from agent.core.settings import SKILLS_DIR


PROJECT_SKILLS_DIR = PROJECT_ROOT / "agent" / "skills"
SYNCED_SKILLS = (
    "repo-bootstrap-analysis",
    "ai-coding-implementation",
)


def _sha256(path: Path) -> str:
    """计算 skill 文件指纹，用来判断源码目录和运行时目录是否完全一致。"""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_skill(path: Path) -> str:
    """读取 skill 内容，并兼容少数编辑器写入的 UTF-8 BOM。"""

    return path.read_text(encoding="utf-8-sig")


def main() -> None:
    r"""验证项目内 skills 已同步到 DeepAgents 真实运行目录。

    DeepAgents 运行时读取的是 `B:\ai_workspace\skills`，而项目源码保存在
    `agent/skills`。这个脚本用于防止只改源码、不改运行目录，导致 Agent 继续
    使用旧规则。
    """

    for skill_name in SYNCED_SKILLS:
        source = PROJECT_SKILLS_DIR / skill_name / "SKILL.md"
        runtime = SKILLS_DIR / skill_name / "SKILL.md"

        if not source.exists():
            raise AssertionError(f"项目源码缺少 skill：{source}")
        if not runtime.exists():
            raise AssertionError(f"运行时目录缺少 skill：{runtime}")
        if _sha256(source) != _sha256(runtime):
            raise AssertionError(f"skill 未同步：{source} -> {runtime}")

        text = _read_skill(runtime)
        if "git -C projects" in text:
            raise AssertionError(f"skill 中仍包含错误命令路径：{runtime}")
        if "projects/projects" not in text:
            raise AssertionError(f"skill 缺少 projects/projects 防误用说明：{runtime}")
        if "所有面向用户的自然语言输出必须使用中文" not in text:
            raise AssertionError(f"skill 缺少中文输出规则：{runtime}")

    print("skills 同步验证通过")


if __name__ == "__main__":
    main()
