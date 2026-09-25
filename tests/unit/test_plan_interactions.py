from agent.store.sqlite_store import LocalSqliteStore
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, TypedDict

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

import agent.core.runtime as runtime
import agent.core.streaming_runtime as streaming_runtime
from agent.tools.human_intervention import request_human_intervention


def test_plan_versions_and_decisions_are_conditional(tmp_path):
    store = LocalSqliteStore(tmp_path / "store.sqlite")
    try:
        store.add_thread_plan(
            plan_id="plan-v1", thread_id="thread-1", prompt="build feature",
            plan_text="version one", plan_path="", version=1,
        )
        store.add_thread_plan(
            plan_id="plan-v2", thread_id="thread-1", prompt="build feature plus detail",
            plan_text="version two", plan_path="", version=2, supersedes_plan_id="plan-v1",
        )

        assert store.transition_thread_plan(
            "plan-v1", thread_id="thread-1", expected_status="pending", status="superseded",
            decision_feedback="include the API endpoint",
        )["status"] == "superseded"
        assert store.get_thread_plan("plan-v2")["supersedes_plan_id"] == "plan-v1"
        assert store.transition_thread_plan(
            "plan-v2", thread_id="thread-1", expected_status="pending", status="approved"
        )["status"] == "approved"
        assert store.transition_thread_plan(
            "plan-v2", thread_id="thread-1", expected_status="pending", status="approved"
        ) is None
        assert store.transition_thread_plan(
            "plan-v2", thread_id="thread-1", expected_status="pending", status="rejected"
        ) is None
    finally:
        store.close()


def test_intervention_can_only_be_resumed_once_and_survives_store_reload(tmp_path):
    db_path = tmp_path / "store.sqlite"
    store = LocalSqliteStore(db_path)
    store.create_thread_intervention(
        intervention_id="intervention-1", thread_id="thread-1", run_id="run-1",
        payload={"question": "Continue?", "reason": "The operation is out of scope", "options": ["yes", "no"]},
    )
    resumed = store.resolve_thread_intervention(
        "intervention-1", thread_id="thread-1", response="yes, with the extra check"
    )
    assert resumed["status"] == "resuming"
    assert resumed["payload"]["question"] == "Continue?"
    assert store.get_latest_active_thread_intervention("thread-1")["intervention_id"] == "intervention-1"
    assert store.resolve_thread_intervention(
        "intervention-1", thread_id="thread-1", response="second answer"
    ) is None
    store.finish_thread_intervention("intervention-1", thread_id="thread-1")
    store.close()

    reopened = LocalSqliteStore(db_path)
    try:
        saved = reopened.get_thread_intervention("intervention-1")
        assert saved["status"] == "resolved"
        assert saved["response"] == "yes, with the extra check"
        assert reopened.get_latest_active_thread_intervention("thread-1") is None
    finally:
        reopened.close()


def test_runtime_resumes_interrupted_coding_run_instead_of_replanning(tmp_path, monkeypatch):
    store = LocalSqliteStore(tmp_path / "store.sqlite")
    store.upsert_thread(
        thread_id="thread-resume", title="approved task", user_prompt="approved task",
        repo_url="https://github.com/owner/repo.git", repo_owner="owner", repo_name="repo",
        latest_run_status="awaiting_approval",
    )
    store.create_thread_intervention(
        intervention_id="intervention-resume", thread_id="thread-resume", run_id="run-old",
        payload={"question": "May I continue?", "reason": "scope check"},
    )
    captured = {}

    class Lease:
        @contextmanager
        def hold(self, _run_id):
            yield

    monkeypatch.setattr(runtime, "get_store", lambda: store)
    monkeypatch.setattr(runtime, "record_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runtime, "is_workspace_listing_task", lambda _prompt: False)
    monkeypatch.setattr(runtime, "is_pull_only_task", lambda _prompt: False)
    monkeypatch.setattr(
        runtime, "classify_task_kind",
        lambda _prompt: (_ for _ in ()).throw(AssertionError("resume must bypass ordinary intent classification")),
    )
    monkeypatch.setattr(runtime, "_prepare_selected_repository", lambda *_args, **_kwargs: SimpleNamespace(
        directory="repo", current_branch="codex/task"
    ))
    monkeypatch.setattr(runtime, "_build_agent_for_runtime", lambda **_kwargs: object())
    monkeypatch.setattr(runtime, "WorkerLeaseManager", lambda _store: Lease())
    monkeypatch.setattr(runtime, "_detect_current_branch", lambda _repo: "codex/task")
    monkeypatch.setattr(runtime, "run_agent_with_event_stream", lambda **kwargs: (
        captured.update(kwargs) or {"messages": [], "interrupts": []}
    ))

    try:
        result = runtime.run_agent_task(
            repo_url="https://github.com/owner/repo.git",
            prompt="继续，但只执行已经批准的范围",
            thread_id="thread-resume",
            interaction_action="resume_intervention",
            intervention_id="intervention-resume",
        )
        assert result["status"] == "completed"
        assert captured["resume_value"] == {"response": "继续，但只执行已经批准的范围"}
        assert store.get_thread_intervention("intervention-resume")["status"] == "resolved"
    finally:
        store.close()


def test_runtime_rejects_plain_message_while_intervention_is_pending(tmp_path, monkeypatch):
    store = LocalSqliteStore(tmp_path / "store.sqlite")
    store.upsert_thread(
        thread_id="thread-waiting", title="approved task", user_prompt="approved task",
        repo_url="https://github.com/owner/repo.git", repo_owner="owner", repo_name="repo",
        latest_run_status="awaiting_approval",
    )
    store.create_thread_intervention(
        intervention_id="intervention-waiting", thread_id="thread-waiting", run_id="run-old",
        payload={"question": "May I continue?"},
    )
    monkeypatch.setattr(runtime, "get_store", lambda: store)
    monkeypatch.setattr(
        runtime, "classify_task_kind",
        lambda _prompt: (_ for _ in ()).throw(AssertionError("pending message must be rejected before classification")),
    )

    try:
        with pytest.raises(ValueError, match="人工介入答复"):
            runtime.run_agent_task(
                repo_url="https://github.com/owner/repo.git",
                prompt="1", thread_id="thread-waiting",
            )
        assert store.get_latest_active_thread_intervention("thread-waiting")["status"] == "pending"
    finally:
        store.close()


def test_human_intervention_tool_interrupts_and_resumes_same_graph():
    class State(TypedDict, total=False):
        answer: Any

    def ask_user(_state):
        answer = request_human_intervention.invoke(
            {"question": "May I update the deployment config?", "reason": "This is outside the approved scope."}
        )
        return {"answer": answer}

    graph = StateGraph(State)
    graph.add_node("ask_user", ask_user)
    graph.add_edge(START, "ask_user")
    graph.add_edge("ask_user", END)
    app = graph.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "human-intervention-test", "task_kind": "coding"}}

    paused = app.invoke({}, config)
    assert paused["__interrupt__"][0].value["type"] == "human_intervention"
    assert paused["__interrupt__"][0].value["question"] == "May I update the deployment config?"

    resumed = app.invoke(Command(resume={"response": "Yes, include the config change."}), config)
    assert resumed["answer"]["user_response"] == {"response": "Yes, include the config change."}


def test_streaming_runtime_surfaces_interrupts_and_uses_resume_command(monkeypatch):
    payload = {"type": "human_intervention", "question": "Continue?", "reason": "Scope check"}

    class Stream:
        output = {"messages": [], "__interrupt__": [SimpleNamespace(value=payload)]}

        def __iter__(self):
            return iter(())

    class Agent:
        input_value = None

        def stream_events(self, value, **_kwargs):
            self.input_value = value
            return Stream()

    agent = Agent()
    monkeypatch.setattr(streaming_runtime, "record_event", lambda *_args, **_kwargs: None)
    result = streaming_runtime.run_agent_with_event_stream(
        agent=agent, thread_id="thread-stream-resume", run_id="run-stream-resume",
        content="ignored during resume", resume_value={"response": "go ahead"},
    )

    assert result["interrupts"] == [payload]
    assert isinstance(agent.input_value, Command)
    assert agent.input_value.resume == {"response": "go ahead"}
