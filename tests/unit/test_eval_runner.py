from __future__ import annotations

import json
from pathlib import Path

from agent.evals.runner import EvalRunner
from agent.evals.schemas import EvalCase


def test_eval_runner_generates_stable_report_artifacts(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "value.txt").write_text("before\n", encoding="utf-8")
    output = tmp_path / "eval_runs"
    case = EvalCase(
        case_id="fake-case",
        prompt="change value",
        gold_files=["value.txt"],
        fake_command=[
            "python",
            "-c",
            "from pathlib import Path; Path('value.txt').write_text('after\\n'); Path('.eval/retrieval.json').write_text('[{\\\"path\\\":\\\"value.txt\\\"}]'); Path('.eval/usage.json').write_text('{\\\"input_tokens\\\":2,\\\"output_tokens\\\":3}')",
        ],
    )

    report = EvalRunner(output_dir=output, mode="fake").run([case], repository=repo)

    assert report.cases[0].status == "passed"
    assert report.cases[0].patch_apply is True
    assert report.cases[0].retrieval_hit_at_k == 1.0
    assert report.cases[0].total_tokens == 5
    assert (output / "report.json").exists()
    assert (output / "summary.md").exists()
    assert json.loads((output / "report.json").read_text(encoding="utf-8"))["report_id"] == report.report_id
