from __future__ import annotations

from agent.core import events


class FakeStore:
    def __init__(self) -> None:
        self.run_events: list[dict[str, str]] = []
        self.audit_events: list[dict[str, object]] = []

    def add_run_event(self, **kwargs: str) -> None:
        self.run_events.append(kwargs)

    def append_audit_event(self, **kwargs: object) -> None:
        self.audit_events.append(kwargs)


def test_record_event_writes_business_event_and_audit(monkeypatch) -> None:
    store = FakeStore()
    monkeypatch.setattr(events, "_event_store", store)

    events.record_event("thread-1", "agent", "Agent started", status="completed")

    assert store.run_events[0]["event_id"] == "thread-1:agent"
    assert store.run_events[0]["status"] == "completed"
    assert store.audit_events[0]["event_type"] == "run_event"
    assert store.audit_events[0]["thread_id"] == "thread-1"
