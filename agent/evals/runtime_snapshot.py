from __future__ import annotations

import hashlib
import shutil
import subprocess
import tarfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath


@dataclass(frozen=True)
class AgentRuntimeSnapshot:
    source_dir: Path
    commit: str
    fingerprint: str
    adapter_sha256: str
    overlay_files: dict[str, str]


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        shell=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {(completed.stderr or completed.stdout)[-1000:]}")
    return completed.stdout.strip()


def _extract_commit(root: Path, commit: str, destination: Path) -> None:
    completed = subprocess.run(
        ["git", "archive", "--format=tar", commit],
        cwd=root,
        capture_output=True,
        check=False,
        shell=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Could not archive Agent commit {commit}")
    destination.mkdir(parents=True, exist_ok=False)
    with tarfile.open(fileobj=BytesIO(completed.stdout), mode="r:") as archive:
        members = archive.getmembers()
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts:
                raise RuntimeError(f"Agent archive contains an unsafe path: {member.name}")
            if member.issym() or member.islnk():
                link = PurePosixPath(member.linkname)
                target = link if link.is_absolute() else path.parent / link
                stack: list[str] = []
                for part in target.parts:
                    if part in {"", "."}:
                        continue
                    if part == "..":
                        if not stack:
                            raise RuntimeError(f"Agent archive contains an escaping link: {member.name}")
                        stack.pop()
                    else:
                        stack.append(part)
        archive.extractall(destination, members=members)


def _tree_fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if any(part in {"__pycache__", ".pytest_cache", ".codegraph"} for part in Path(relative).parts):
            continue
        if path.name.endswith((".pyc", ".sqlite", ".db")):
            continue
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def prepare_agent_runtime_snapshot(
    *,
    source_root: Path,
    revision: str | None,
    destination: Path,
    adapter_source_root: Path,
) -> AgentRuntimeSnapshot:
    """Materialize one exact Git revision and add only missing Eval bootstrap files.

    The bootstrap overlay is hashed separately because a historical Agent commit may
    predate Eval's child-process adapter and telemetry module.
    """

    source_root = source_root.expanduser().resolve()
    adapter_source_root = adapter_source_root.expanduser().resolve()
    destination = destination.expanduser().resolve()
    commit_ref = revision or "HEAD"
    commit = _git(source_root, "rev-parse", "--verify", f"{commit_ref}^{{commit}}")
    if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit.lower()):
        raise RuntimeError(f"Agent revision did not resolve to a full Git commit SHA: {commit_ref}")

    _extract_commit(source_root, commit, destination)
    overlay_files: dict[str, str] = {}
    required = ("scripts/run_eval_agent.py", "scripts/run_eval_app.py", "agent/evals/telemetry.py")
    for relative in required:
        target = destination / relative
        if target.is_file():
            continue
        source = adapter_source_root / relative
        if not source.is_file():
            raise FileNotFoundError(f"Required Agent Eval bootstrap file is missing: {source}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        overlay_files[relative] = hashlib.sha256(target.read_bytes()).hexdigest()

    eval_init = destination / "agent/evals/__init__.py"
    if not eval_init.exists():
        eval_init.parent.mkdir(parents=True, exist_ok=True)
        payload = '"""Eval-only bootstrap namespace for pinned Agent runtimes."""\n'
        eval_init.write_text(payload, encoding="utf-8")
        overlay_files["agent/evals/__init__.py"] = hashlib.sha256(eval_init.read_bytes()).hexdigest()

    forbidden = [
        path.relative_to(destination).as_posix()
        for path in destination.rglob("*")
        if path.is_file() and (path.name == ".env" or (path.name.startswith(".env.") and path.name != ".env.example"))
    ]
    if forbidden:
        raise RuntimeError("Refusing Agent runtime snapshot containing environment secrets: " + ", ".join(forbidden))

    adapter_path = destination / "scripts/run_eval_agent.py"
    if not adapter_path.is_file():
        raise FileNotFoundError(f"Agent Eval adapter was not materialized: {adapter_path}")
    return AgentRuntimeSnapshot(
        source_dir=destination,
        commit=commit,
        fingerprint=_tree_fingerprint(destination),
        adapter_sha256=hashlib.sha256(adapter_path.read_bytes()).hexdigest(),
        overlay_files=overlay_files,
    )


def verify_agent_runtime_snapshot(snapshot: AgentRuntimeSnapshot) -> bool:
    return _tree_fingerprint(snapshot.source_dir) == snapshot.fingerprint
