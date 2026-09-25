import pytest
from fastapi import HTTPException

import agent.api.dashboard_routes as dashboard_routes
import agent.core.model as model
import agent.core.runtime as runtime
import agent.core.streaming_runtime as streaming_runtime


def test_dashboard_model_defaults_to_configured_model(monkeypatch):
    monkeypatch.setattr(dashboard_routes, "get_env", lambda _name, default: "deepseek-flash")

    assert dashboard_routes._normalize_dashboard_model_id(None) == "deepseek-flash"
    assert dashboard_routes._normalize_dashboard_model_id("deepseek-flash") == "deepseek-flash"


def test_dashboard_rejects_model_not_exposed_by_configuration(monkeypatch):
    monkeypatch.setattr(dashboard_routes, "get_env", lambda _name, default: "deepseek-flash")

    with pytest.raises(HTTPException) as exc_info:
        dashboard_routes._normalize_dashboard_model_id("deepseek-v4-pro")

    assert exc_info.value.status_code == 422


def test_main_model_factory_uses_validated_selected_model(monkeypatch):
    calls = {}
    monkeypatch.setattr(model, "get_env", lambda _name, default: "deepseek-flash")
    monkeypatch.setattr(model, "require_env", lambda _name: "configured")
    monkeypatch.setattr(model, "init_chat_model", lambda **kwargs: calls.update(kwargs) or object())

    model.make_main_model("deepseek-flash")

    assert calls["model"] == "deepseek-flash"


def test_main_model_factory_rejects_unconfigured_model(monkeypatch):
    monkeypatch.setattr(model, "get_env", lambda _name, default: "deepseek-flash")
    monkeypatch.setattr(model, "init_chat_model", lambda **_kwargs: pytest.fail("must not initialize"))

    with pytest.raises(ValueError, match="MAIN_MODEL"):
        model.make_main_model("unconfigured-model")


def test_runtime_passes_model_id_to_agent_config(monkeypatch):
    observed = {}
    monkeypatch.setattr(runtime, "get_agent", lambda config: observed.update(config) or "agent")

    assert runtime._build_agent_for_runtime(
        thread_id="thread-1", task_kind="qa", model_id="deepseek-flash"
    ) == "agent"
    assert observed["configurable"]["model_id"] == "deepseek-flash"


def test_streaming_activity_uses_actual_model_name(monkeypatch):
    recorded = []

    class FakeStream:
        output = {"messages": []}

    class FakeAgent:
        def stream_events(self, *_args, **_kwargs):
            return FakeStream()

    monkeypatch.setattr(streaming_runtime, "record_event", lambda *_args, **_kwargs: recorded.append(_args[2]))
    monkeypatch.setattr(streaming_runtime, "_consume_raw_event_stream", lambda **_kwargs: (0, 0))

    streaming_runtime.run_agent_with_event_stream(
        agent=FakeAgent(), thread_id="thread-1", run_id="run-1", content="test", model_id="deepseek-flash"
    )

    assert recorded == ["调用 deepseek-flash", "调用 deepseek-flash"]
