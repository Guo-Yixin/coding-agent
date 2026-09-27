from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import agent.evals.runner as runner_module
from agent.evals.runner import EvalRunner
from agent.evals.schemas import EvalCase


def test_case_fixtures_are_hashed_and_materialized_inside_workspace(tmp_path: Path, monkeypatch) -> None:
    fake_module = tmp_path / "agent" / "evals" / "runner.py"
    fake_module.parent.mkdir(parents=True)
    fake_module.write_text("", encoding="utf-8")
    monkeypatch.setattr(runner_module, "__file__", str(fake_module))
    fixture = tmp_path / "agent" / "evals" / "fixtures" / "new-case" / "tests" / "test_feature.py"
    fixture.parent.mkdir(parents=True)
    fixture.write_text("def test_feature(): pass\n", encoding="utf-8")
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    case = EvalCase(case_id="new-case", prompt="", fixture_files=["tests/test_feature.py"])

    hashes = EvalRunner._materialize_case_fixtures(case, workspace)

    assert hashes == {"tests/test_feature.py": hashlib.sha256(fixture.read_bytes()).hexdigest()}
    assert (workspace / "tests" / "test_feature.py").read_bytes() == fixture.read_bytes()


@pytest.mark.parametrize("fixture_path", ["../outside.py", "C:/outside.py", ""])
def test_case_fixtures_reject_unsafe_paths(tmp_path: Path, monkeypatch, fixture_path: str) -> None:
    fake_module = tmp_path / "agent" / "evals" / "runner.py"
    fake_module.parent.mkdir(parents=True)
    fake_module.write_text("", encoding="utf-8")
    monkeypatch.setattr(runner_module, "__file__", str(fake_module))
    case = EvalCase(case_id="case", prompt="", fixture_files=[fixture_path])

    with pytest.raises(ValueError):
        EvalRunner._fixture_hashes(case)
