from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SearchHit:
    path: str
    line: int | None
    end_line: int | None
    text: str
    source: str
    score: float
    symbol: str | None = None
    kind: str | None = None
    signature: str | None = None
    context: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SearchTrace:
    query: str
    codegraph_attempted: bool = False
    codegraph_succeeded: bool = False
    grep_attempted: bool = False
    fallback_reason: str | None = None
    codegraph_count: int = 0
    grep_count: int = 0
    merged_count: int = 0
    context_chars: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class HybridSearchResult:
    hits: list[SearchHit]
    trace: SearchTrace

    def to_dict(self) -> dict[str, Any]:
        return {"hits": [hit.to_dict() for hit in self.hits], "trace": self.trace.to_dict()}


_SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", ".codegraph"}
_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.:-]{2,}")


def _codegraph_command() -> str | None:
    return shutil.which(os.environ.get("CODEGRAPH_BIN", "codegraph"))


def _run_codegraph(query: str, repo_root: Path, *, limit: int, timeout: float, trace: SearchTrace) -> list[SearchHit]:
    trace.codegraph_attempted = True
    binary = _codegraph_command()
    if binary is None:
        trace.fallback_reason = "codegraph binary not found"
        return []
    command = [binary, "query", "--json", "--limit", str(limit), "-p", str(repo_root), query]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False, shell=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        trace.fallback_reason = f"codegraph execution failed: {type(exc).__name__}"
        trace.errors.append(str(exc))
        return []
    if completed.returncode != 0:
        trace.fallback_reason = f"codegraph exit code {completed.returncode}"
        trace.errors.append(completed.stderr.strip() or completed.stdout.strip())
        return []
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        trace.fallback_reason = "codegraph returned invalid JSON"
        trace.errors.append(str(exc))
        return []
    hits: list[SearchHit] = []
    for item in payload if isinstance(payload, list) else []:
        node = item.get("node", {}) if isinstance(item, dict) else {}
        path = str(node.get("filePath") or "")
        if not path:
            continue
        try:
            path = str(Path(path).resolve().relative_to(repo_root.resolve())).replace("\\", "/")
        except ValueError:
            path = path.replace("\\", "/")
        hits.append(
            SearchHit(
                path=path,
                line=node.get("startLine"),
                end_line=node.get("endLine"),
                text=str(node.get("name") or node.get("signature") or ""),
                source="codegraph",
                score=0.7 + min(float(item.get("score", 0) or 0) / 1000, 0.25),
                symbol=node.get("qualifiedName") or node.get("name"),
                kind=node.get("kind"),
                signature=node.get("signature"),
            )
        )
    trace.codegraph_succeeded = True
    trace.codegraph_count = len(hits)
    return hits


def _grep_patterns(query: str) -> list[str]:
    quoted = re.findall(r"[`\"']([^`\"']+)[`\"']", query)
    tokens = _TOKEN_RE.findall(query)
    values: list[str] = []
    for value in [*quoted, *tokens, query.strip()]:
        value = value.strip()
        if value and value not in values:
            values.append(value)
    return values[:8]


def _grep_files(repo_root: Path, query: str, *, max_files: int, max_matches: int, trace: SearchTrace) -> list[SearchHit]:
    trace.grep_attempted = True
    patterns = _grep_patterns(query)
    hits: list[SearchHit] = []
    visited_files = 0
    for file in repo_root.rglob("*"):
        if len(hits) >= max_matches or visited_files >= max_files:
            break
        if not file.is_file() or any(part in _SKIP_DIRS for part in file.parts):
            continue
        visited_files += 1
        try:
            relative = file.relative_to(repo_root)
            lines = file.read_text(encoding="utf-8", errors="ignore").splitlines()
        except (OSError, UnicodeError):
            continue
        for line_no, line in enumerate(lines, 1):
            matching = next((pattern for pattern in patterns if pattern.lower() in line.lower()), None)
            if matching is None:
                continue
            start = max(0, line_no - 2)
            end = min(len(lines), line_no + 1)
            hits.append(
                SearchHit(
                    path=str(relative).replace("\\", "/"),
                    line=line_no,
                    end_line=line_no,
                    text=line.strip(),
                    source="grep",
                    score=0.35 + (0.1 if matching == query.strip() else 0),
                    context="\n".join(lines[start:end]),
                )
            )
            if len(hits) >= max_matches:
                break
    trace.grep_count = len(hits)
    return hits


def _same_location(left: SearchHit, right: SearchHit) -> bool:
    return left.path.replace("\\", "/") == right.path.replace("\\", "/") and left.line == right.line


def hybrid_search(
    query: str,
    repo_root: str | Path,
    *,
    limit: int = 20,
    context_budget_chars: int = 24000,
    codegraph_timeout: float = 8.0,
) -> HybridSearchResult:
    """Search a repository through CodeGraph first and grep as lexical fallback."""
    root = Path(repo_root).expanduser().resolve()
    trace = SearchTrace(query=query)
    graph_hits = _run_codegraph(query, root, limit=limit, timeout=codegraph_timeout, trace=trace)
    grep_hits = _grep_files(root, query, max_files=limit * 100, max_matches=limit * 3, trace=trace)

    merged: list[SearchHit] = []
    for hit in graph_hits + grep_hits:
        duplicate_index = next((idx for idx, existing in enumerate(merged) if _same_location(existing, hit)), None)
        if duplicate_index is None:
            merged.append(hit)
        else:
            existing = merged[duplicate_index]
            merged[duplicate_index] = SearchHit(
                **{
                    **existing.to_dict(),
                    "source": "codegraph+grep",
                    "score": min(existing.score + hit.score * 0.35, 1.5),
                    "context": existing.context or hit.context,
                }
            )
    merged.sort(key=lambda item: (-item.score, item.path, item.line or 0))
    selected: list[SearchHit] = []
    used_chars = 0
    for hit in merged[:limit]:
        cost = len(hit.context or hit.text)
        if used_chars + cost > context_budget_chars and selected:
            continue
        selected.append(hit)
        used_chars += cost
    trace.merged_count = len(selected)
    trace.context_chars = used_chars
    return HybridSearchResult(hits=selected, trace=trace)


def hybrid_code_search(query: str, repo_path: str, limit: int = 20) -> dict[str, Any]:
    """Agent tool wrapper with a JSON-serializable result."""
    return hybrid_search(query, repo_path, limit=limit).to_dict()
