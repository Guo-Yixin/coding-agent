from __future__ import annotations

from pathlib import Path

import pytest

from agent.store.sqlite_store import LocalSqliteStore


def test_plain_chat_streams_and_persists_assistant_reply(tmp_path: Path, monkeypatch) -> None:
    import agent.core.runtime as runtime

    store = LocalSqliteStore(tmp_path / "chat.sqlite")
    thread = store.create_chat_thread(thread_id="chat")
    store.add_thread_message(message_id="u1", thread_id="chat", author="user", content="第一轮", run_id="r1")
    emitted = []

    class Chunk:
        def __init__(self, content): self.content = content

    class FakeModel:
        def stream(self, messages):
            assert any(getattr(message, "content", "") == "第一轮" for message in messages)
            yield Chunk("并发")
            yield Chunk([{"type": "text", "text": "完成"}])

    monkeypatch.setattr(runtime, "get_store", lambda: store)
    monkeypatch.setattr("agent.core.model.make_main_model", lambda _model_id: FakeModel())
    try:
        result = runtime.run_plain_chat_task(
            thread_id=thread["thread_id"], run_id="run-1", model_id="deepseek-flash",
            event_sink=lambda event, payload: emitted.append((event, payload)),
        )
        assert result["status"] == "completed"
        assert result["content"] == "并发完成"
        assert [payload["content"] for event, payload in emitted if event == "text_delta"] == ["并发", "完成"]
        persisted = store.list_thread_messages("chat")
        assert persisted[-1]["content"] == "并发完成"
        assert persisted[-1]["metadata"]["model_id"] == "deepseek-flash"
        assert store.get_thread("chat")["latest_run_status"] == "completed"
    finally:
        store.close()


def test_plain_chat_rejects_project_bound_threads(tmp_path: Path, monkeypatch) -> None:
    import agent.core.runtime as runtime

    store = LocalSqliteStore(tmp_path / "chat.sqlite")
    project = store.create_project(
        project_id="p", name="Project", provider="github", repo_url="https://github.com/a/b.git",
        repo_owner="a", repo_name="b",
    )
    store.create_thread_for_project(thread_id="bound", project_id=project["project_id"])
    monkeypatch.setattr(runtime, "get_store", lambda: store)
    try:
        with pytest.raises(ValueError, match="不能关联项目"):
            runtime.run_plain_chat_task(thread_id="bound", run_id="run", model_id=None, event_sink=lambda *_args: None)
    finally:
        store.close()


def test_plain_chat_fails_when_model_returns_no_text(tmp_path: Path, monkeypatch) -> None:
    import agent.core.runtime as runtime

    store = LocalSqliteStore(tmp_path / "chat.sqlite")
    store.create_chat_thread(thread_id="chat")

    class Chunk:
        content = ""

    class FakeModel:
        def stream(self, _messages): return iter([Chunk()])

    monkeypatch.setattr(runtime, "get_store", lambda: store)
    monkeypatch.setattr("agent.core.model.make_main_model", lambda _model_id: FakeModel())
    try:
        with pytest.raises(RuntimeError, match="没有返回可显示的文本"):
            runtime.run_plain_chat_task(thread_id="chat", run_id="run", model_id=None, event_sink=lambda *_args: None)
    finally:
        store.close()
