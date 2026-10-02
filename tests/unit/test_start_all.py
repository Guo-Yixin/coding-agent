from __future__ import annotations

from unittest.mock import Mock

import pytest

from scripts import start_all


@pytest.fixture
def services(monkeypatch: pytest.MonkeyPatch) -> tuple[Mock, Mock, Mock]:
    backend, frontend = Mock(), Mock()
    backend.poll.return_value = None
    frontend.poll.return_value = None
    processes = iter((backend, frontend))
    monkeypatch.setattr(start_all, "start_process", lambda *args, **kwargs: next(processes))
    stop_ports = Mock(return_value=[])
    monkeypatch.setattr(start_all, "stop_ports", stop_ports)
    # Interrupt the monitoring loop instead of sleeping or starting real services.
    monkeypatch.setattr(start_all.time, "sleep", Mock(side_effect=KeyboardInterrupt))
    return backend, frontend, stop_ports


@pytest.mark.parametrize("failed_service,return_code", [("backend", 1), ("frontend", 2)])
def test_service_failure_preserves_error_after_cleanup(
    services: tuple[Mock, Mock, Mock], failed_service: str, return_code: int
) -> None:
    backend, frontend, stop_ports = services
    failed, remaining = (backend, frontend) if failed_service == "backend" else (frontend, backend)
    failed.poll.return_value = return_code

    with pytest.raises(SystemExit) as raised:
        start_all.main()

    # A SystemExit message produces status 1 and identifies the failed service.
    assert raised.value.code == f"{failed_service} exited: {return_code}"
    failed.terminate.assert_not_called()
    remaining.terminate.assert_called_once_with()
    backend.wait.assert_called_once_with(timeout=5)
    frontend.wait.assert_called_once_with(timeout=5)
    stop_ports.assert_called_once_with((2024, 3000))


def test_keyboard_interrupt_still_stops_services_successfully(
    services: tuple[Mock, Mock, Mock], capsys: pytest.CaptureFixture[str]
) -> None:
    backend, frontend, stop_ports = services

    with pytest.raises(SystemExit) as raised:
        start_all.main()

    assert raised.value.code == 0
    assert "正在停止服务..." in capsys.readouterr().out
    for process in (backend, frontend):
        process.terminate.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=5)
    stop_ports.assert_called_once_with((2024, 3000))
