from __future__ import annotations

import subprocess
import sys
import re
import os
import signal
from collections.abc import Iterable


DEFAULT_PORTS = (2024, 3000)


def _run_powershell(command: str) -> subprocess.CompletedProcess[str]:
    """执行一段只用于进程查询/停止的 PowerShell 命令。

    这里不用 shell=True，避免命令被额外解释；所有动态值只来自固定端口数字。
    """

    return subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
    )


def find_pids_by_ports(ports: Iterable[int] = DEFAULT_PORTS) -> list[int]:
    """根据端口查找监听进程 PID。

    start_all.py 默认占用：
    - 2024：FastAPI/Uvicorn 后端
    - 3000：Vite 前端
    """

    if os.name != "nt":
        return _find_pids_by_ports_unix(ports)

    port_list = ",".join(str(port) for port in ports)
    command = (
        f"Get-NetTCPConnection -LocalPort {port_list} -ErrorAction SilentlyContinue "
        "| Where-Object { $_.State -eq 'Listen' } "
        "| Select-Object -ExpandProperty OwningProcess -Unique"
    )
    result = _run_powershell(command)

    pids: list[int] = []
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                pids.append(int(line))
            except ValueError:
                continue
    if pids:
        return sorted(set(pids))

    # 某些 Windows/PyCharm 组合下 Get-NetTCPConnection 可能查不到，
    # 但 netstat 仍然能看到 LISTENING 记录，所以这里做一次兜底解析。
    netstat = subprocess.run(
        ["netstat", "-ano"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
    )
    if netstat.returncode != 0:
        return []
    port_set = {int(port) for port in ports}
    for line in netstat.stdout.splitlines():
        if "LISTENING" not in line:
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        local_address = parts[1]
        pid_text = parts[-1]
        match = re.search(r":(\d+)$", local_address)
        if not match:
            continue
        if int(match.group(1)) not in port_set:
            continue
        try:
            pids.append(int(pid_text))
        except ValueError:
            continue
    return sorted(set(pids))


def _find_pids_by_ports_unix(ports: Iterable[int]) -> list[int]:
    """Linux/macOS 下根据端口查找监听进程 PID。"""

    pids: list[int] = []
    for port in ports:
        try:
            lsof = subprocess.run(
                ["lsof", "-ti", f"tcp:{int(port)}"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError:
            lsof = None
        if lsof is not None and lsof.returncode == 0:
            for line in lsof.stdout.splitlines():
                try:
                    pids.append(int(line.strip()))
                except ValueError:
                    continue
    if pids:
        return sorted(set(pids))

    try:
        ss = subprocess.run(
            ["ss", "-ltnp"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        return []
    if ss.returncode != 0:
        return []
    port_set = {int(port) for port in ports}
    for line in ss.stdout.splitlines():
        match_port = re.search(r":(\d+)\s", line)
        match_pid = re.search(r"pid=(\d+)", line)
        if not match_port or not match_pid:
            continue
        if int(match_port.group(1)) not in port_set:
            continue
        pids.append(int(match_pid.group(1)))
    return sorted(set(pids))


def stop_pids(pids: Iterable[int]) -> list[int]:
    """停止指定 PID，并返回实际发出停止命令的 PID 列表。"""

    stopped: list[int] = []
    for pid in sorted(set(pids)):
        if pid <= 0:
            continue
        if os.name == "nt":
            command = f"Stop-Process -Id {pid} -Force -ErrorAction SilentlyContinue"
            _run_powershell(command)
        else:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                continue
        stopped.append(pid)
    return stopped


def stop_ports(ports: Iterable[int] = DEFAULT_PORTS) -> list[int]:
    """停止指定端口上的监听进程。"""

    pids = find_pids_by_ports(ports)
    return stop_pids(pids)


def main() -> None:
    """清理项目常用的后端和前端服务端口。"""

    ports = DEFAULT_PORTS
    stopped = stop_ports(ports)
    if stopped:
        print(f"已停止端口 {ports} 对应进程：{stopped}")
    else:
        print(f"端口 {ports} 当前没有监听进程。")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
