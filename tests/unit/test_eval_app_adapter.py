from __future__ import annotations

import json

import httpx
import pytest

from scripts.run_eval_app import _latest_plan, _run_browser_task, _sse_post, _submit_plan_decision, _thread_text


def test_app_adapter_parses_real_sse_event_framing():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text='event: user_message\ndata: {"thread_id":"thread-1"}\n\nevent: done\ndata: {"status":"completed"}\n\n',
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        events = _sse_post(client, "http://example.test/stream", {"content": "hello"}, 5)

    assert events == [
        {"event": "user_message", "data": {"thread_id": "thread-1"}},
        {"event": "done", "data": {"status": "completed"}},
    ]


def test_app_adapter_reads_pending_plan_and_user_visible_text():
    thread = {
        "latestPlan": {"plan_id": "plan-1", "status": "pending", "plan_text": "方案"},
        "messages": [{"chunks": [{"content": "已完成"}, {"content": "测试通过"}]}],
    }
    assert _latest_plan(thread) == thread["latestPlan"]
    assert _thread_text(thread) == "已完成\n\n测试通过"


def test_app_adapter_can_reject_pending_plan_through_sse():
    received = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received.update(json.loads(request.content))
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text='event: done\ndata: {"status":"completed","decision":"rejected"}\n\n',
        )

    plan = {"plan_id": "plan-reject-1", "status": "pending", "plan_text": "方案"}
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        events = _submit_plan_decision(client, "http://example.test/thread-1", plan, "reject", 5)

    assert received["interaction_action"] == "reject_plan"
    assert received["plan_id"] == "plan-reject-1"
    assert events[0]["data"]["decision"] == "rejected"


def test_browser_adapter_stops_frontend_when_page_start_fails(tmp_path, monkeypatch):
    import subprocess
    import sys
    import types
    from contextlib import contextmanager
    from pathlib import Path
    from types import SimpleNamespace

    from scripts import run_eval_app

    source_root = tmp_path / "source"
    (source_root / "ui").mkdir(parents=True)
    (source_root / "ui" / "index.html").write_text("<main>test</main>", encoding="utf-8")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    npm_cli = tmp_path / "node_modules" / "npm" / "bin" / "npm-cli.js"
    npm_cli.parent.mkdir(parents=True)
    npm_cli.write_text("", encoding="utf-8")
    # Point npm's sibling lookup at a real temporary npm-cli.js file.
    npm_path = tmp_path / "npm.exe"
    npm_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(run_eval_app.shutil, "which", lambda name: str(tmp_path / "node.exe") if name == "node" else str(npm_path))

    process_state = {"terminated": False}

    class FakeProcess:
        stdout = None

        def poll(self):
            return None

        def terminate(self):
            process_state["terminated"] = True

        def wait(self, timeout=None):
            return 0

    def fake_run(command, cwd, **kwargs):
        vite = Path(cwd) / "node_modules" / "vite" / "bin" / "vite.js"
        vite.parent.mkdir(parents=True)
        vite.write_text("", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, *_args, **_kwargs):
            return SimpleNamespace(status_code=200)

    class FakePage:
        def set_default_timeout(self, _timeout):
            pass

        def goto(self, *_args, **_kwargs):
            raise RuntimeError("injected browser navigation failure")

    class FakeBrowser:
        def new_page(self):
            return FakePage()

        def close(self):
            pass

    class FakeChromium:
        def launch(self, **_kwargs):
            return FakeBrowser()

    @contextmanager
    def fake_playwright():
        yield SimpleNamespace(chromium=FakeChromium())

    playwright_module = types.ModuleType("playwright.sync_api")
    playwright_module.sync_playwright = fake_playwright
    monkeypatch.setitem(sys.modules, "playwright.sync_api", playwright_module)
    monkeypatch.setattr(run_eval_app.subprocess, "run", fake_run)
    monkeypatch.setattr(run_eval_app.subprocess, "Popen", lambda *_args, **_kwargs: FakeProcess())
    monkeypatch.setattr(run_eval_app.httpx, "Client", FakeClient)

    with pytest.raises(RuntimeError, match="injected browser navigation failure"):
        _run_browser_task(source_root, "http://127.0.0.1:8000", "https://example.test/repo", "task", run_dir, workspace, 10)

    assert process_state["terminated"] is True
