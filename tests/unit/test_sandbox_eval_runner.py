from __future__ import annotations

import json
from pathlib import Path

from agent.evals.sandbox_runner import SandboxEvalRunner
from agent.evals.schemas import EvalCase
from agent.sandbox import OpenSandboxConfig, SandboxExecution


class FakeExecutor:
    def __init__(self, _: OpenSandboxConfig) -> None:
        self.files: dict[str, str] = {}
        self.commands: list[str] = []

    def start(self) -> str:
        return "fake-sandbox"

    def upload_files(self, files: list[object]) -> int:
        return len(files)

    def execute(self, command: str, *, cwd: str | None = None) -> SandboxExecution:
        self.commands.append(command)
        if command == "git diff --binary":
            return SandboxExecution("fake-sandbox", command, 0, "diff --git a/app.py b/app.py\n", "", 1)
        if command == "git diff --name-only":
            return SandboxExecution("fake-sandbox", command, 0, "app.py\n", "", 1)
        if command == "pytest -q":
            return SandboxExecution("fake-sandbox", command, 0, "1 passed\n", "", 1)
        return SandboxExecution("fake-sandbox", command, 0, "", "", 1)

    def read_file(self, path: str) -> str:
        values = {
            "repo/.eval/retrieval.json": json.dumps([{"path": "app.py", "rank": 1}]),
            "repo/.eval/events.jsonl": json.dumps({"kind": "tool_error", "recovered": True}),
            "repo/.eval/usage.json": json.dumps({"input_tokens": 10, "output_tokens": 5}),
        }
        return values[path]

    def close(self) -> None:
        pass


def test_sandbox_runner_produces_same_metrics_schema(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("print('ok')\n", encoding="utf-8")
    case = EvalCase(
        case_id="sandbox-smoke",
        prompt="修复 app.py",
        gold_files=["app.py"],
        target_tests=[["pytest", "-q"]],
        requires_patch=True,
        agent_command=["python", "agent.py"],
    )
    output = tmp_path / "out"
    runner = SandboxEvalRunner(
        output_dir=output,
        config=OpenSandboxConfig(domain="http://sandbox.test"),
        executor_factory=FakeExecutor,
    )

    report = runner.run([case], repository=tmp_path)

    result = report.cases[0]
    assert report.mode == "sandbox"
    assert result.patch_apply is True
    assert result.target_tests_passed is True
    assert result.retrieval_hit_at_k == 1.0
    assert (output / "report.json").exists()
