from __future__ import annotations

from pathlib import Path
import subprocess
import sys

from agent.core.settings import PROJECT_ROOT


SKILL_ROOT = PROJECT_ROOT / ".agents" / "skills" / "coding-agent-issue-writer"


def test_issue_writer_skill_has_valid_metadata_and_references() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

    assert skill.startswith("---\n")
    assert "name: coding-agent-issue-writer" in skill
    assert "description:" in skill
    assert len(skill.splitlines()) < 500
    assert (SKILL_ROOT / "references" / "issue-contract.md").exists()
    assert (SKILL_ROOT / "examples.md").exists()


def test_issue_draft_validator_accepts_bug_draft(tmp_path: Path) -> None:
    draft = tmp_path / "bug.md"
    draft.write_text(
        """[Bug] test\n\n## Environment\nlocal\n\n## Reproduction\n1. run\n\n## Observed Behavior\nactual\n\n## Expected Behavior\nexpected\n\n## Acceptance Criteria\n- [ ] add regression test\n""",
        encoding="utf-8",
    )
    script = SKILL_ROOT / "scripts" / "validate_issue_draft.py"
    result = subprocess.run([sys.executable, str(script), str(draft)], capture_output=True, text=True)

    assert result.returncode == 0
    assert "OK" in result.stdout


def test_issue_draft_validator_rejects_missing_reproduction(tmp_path: Path) -> None:
    draft = tmp_path / "bug.md"
    draft.write_text("[Bug] incomplete\n\n## Acceptance Criteria\n- [ ] test\n", encoding="utf-8")
    script = SKILL_ROOT / "scripts" / "validate_issue_draft.py"
    result = subprocess.run([sys.executable, str(script), str(draft), "--kind", "bug"], capture_output=True, text=True)

    assert result.returncode == 1
    assert "missing bug section" in result.stderr
