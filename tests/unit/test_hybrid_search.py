from __future__ import annotations

import json
import importlib
from pathlib import Path

hybrid_search_module = importlib.import_module("agent.retrieval.hybrid_search")
from agent.retrieval.hybrid_search import hybrid_search


def test_hybrid_search_merges_codegraph_and_grep(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "runtime.py"
    source.write_text("def run_agent_task():\n    return 'ok'\n", encoding="utf-8")

    payload = [{
        "node": {
            "name": "run_agent_task",
            "qualifiedName": "run_agent_task",
            "kind": "function",
            "filePath": str(source),
            "startLine": 1,
            "endLine": 2,
            "signature": "def run_agent_task()",
        },
        "score": 120,
    }]

    class Completed:
        returncode = 0
        stdout = json.dumps(payload)
        stderr = ""

    monkeypatch.setattr(hybrid_search_module.shutil, "which", lambda _: "codegraph")
    monkeypatch.setattr(hybrid_search_module.subprocess, "run", lambda *args, **kwargs: Completed())

    result = hybrid_search("run_agent_task", tmp_path, limit=5)

    assert result.trace.codegraph_succeeded is True
    assert result.trace.grep_attempted is True
    assert result.trace.merged_count >= 1
    assert any(hit.source == "codegraph+grep" for hit in result.hits)


def test_hybrid_search_falls_back_when_codegraph_times_out(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "settings.py").write_text("POSTGRES_DSN = 'coding_agent_db'\n", encoding="utf-8")

    monkeypatch.setattr(hybrid_search_module.shutil, "which", lambda _: "codegraph")

    def timeout(*args, **kwargs):
        raise hybrid_search_module.subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs["timeout"])

    monkeypatch.setattr(hybrid_search_module.subprocess, "run", timeout)

    result = hybrid_search("POSTGRES_DSN", tmp_path)

    assert result.trace.codegraph_succeeded is False
    assert "failed" in (result.trace.fallback_reason or "")
    assert result.trace.grep_count == 1
    assert result.hits[0].source == "grep"


def test_hybrid_search_respects_context_budget(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "a.py").write_text("needle " + "x" * 500 + "\n", encoding="utf-8")
    monkeypatch.setattr(hybrid_search_module.shutil, "which", lambda _: None)

    result = hybrid_search("needle", tmp_path, context_budget_chars=20)

    assert result.trace.context_chars <= 20 or result.trace.merged_count == 1
