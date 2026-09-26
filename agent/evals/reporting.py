from __future__ import annotations

import html
from pathlib import Path, PurePosixPath
from typing import Any

from agent.evals.schemas import EvalReport


def write_report_artifacts(report: EvalReport, output_dir: Path) -> dict[str, str]:
    """Write portable Markdown and self-contained HTML views of an Eval report."""

    return write_report_data(report.to_dict(), output_dir)


def write_report_data(data: dict[str, Any], output_dir: Path) -> dict[str, str]:
    """Render views from an already-normalized report dictionary."""

    output_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = output_dir / "report.md"
    html_path = output_dir / "report.html"
    markdown_path.write_text(_markdown(data), encoding="utf-8")
    html_path.write_text(_html(data), encoding="utf-8")
    return {"markdown": markdown_path.name, "html": html_path.name}


def _markdown(data: dict[str, Any]) -> str:
    summary = data.get("summary", {})
    cases = data.get("cases", [])
    lines = [
        f"# Agent Eval report `{data.get('report_id', 'unknown')}`",
        "",
        f"- **Result:** {summary.get('passed_count', 0)}/{summary.get('case_count', len(cases))} cases passed",
        f"- **Mode:** `{data.get('mode', 'unknown')}`",
        f"- **Created:** `{data.get('created_at', 'unknown')}`",
        f"- **Agent source:** `{data.get('config', {}).get('agent_source_sha', 'unknown')}`",
        f"- **Target repository:** `{_repo_label(str(data.get('repository', 'unknown')))}`",
        f"- **Model:** `{_model_label(cases)}`",
        f"- **Eval source patch:** `{_short_hash(data.get('config', {}).get('agent_source_dirty_patch_sha256'))}`",
        f"- **Total latency:** {_duration(summary.get('total_latency_ms'))}",
        f"- **Total tokens:** {_number(summary.get('total_tokens'))}",
        "",
        "## Cases",
        "",
        "| Case | Result | Target | Regression | Oracle | Retrieval hit@5 | Tokens | Agent time |",
        "| --- | --- | --- | --- | --- | ---: | ---: | ---: |",
    ]
    for case in cases:
        lines.append(
            "| `{case_id}` | **{status}** | {target} | {regression} | {oracle} | {retrieval} | {tokens} | {latency} |".format(
                case_id=case.get("case_id", "unknown"),
                status=case.get("status", "unknown"),
                target=_check(case.get("target_tests_passed")),
                regression=_check(case.get("regression_tests_passed")),
                oracle=_check(case.get("oracle_tests_passed")),
                retrieval=_number(case.get("retrieval_hit_at_k")),
                tokens=_number(case.get("total_tokens")),
                latency=_duration(case.get("agent_latency_ms")),
            )
        )
    lines.extend(["", "## Failure details", ""])
    failures = [case for case in cases if case.get("status") != "passed"]
    if not failures:
        lines.append("All cases passed.")
    for case in failures:
        lines.append(f"### `{case.get('case_id', 'unknown')}`")
        lines.append("")
        for error in case.get("errors", []):
            lines.append(f"- {error}")
        lines.append("")
    lines.extend(["## Artifacts", ""])
    for case in cases:
        for label, artifact in case.get("artifacts", {}).items():
            lines.append(f"- `{case.get('case_id', 'unknown')}` {label}: `{artifact}`")
    lines.append("")
    return "\n".join(lines)


def _html(data: dict[str, Any]) -> str:
    summary = data.get("summary", {})
    cases = data.get("cases", [])
    passed = int(summary.get("passed_count", 0) or 0)
    count = int(summary.get("case_count", len(cases)) or 0)
    failed = int(summary.get("failed_count", max(0, count - passed)) or 0)
    result_class = "good" if count > 0 and passed == count else "bad"
    rows = "\n".join(_case_card(case) for case in cases) or '<p class="empty">No cases were recorded.</p>'
    config = data.get("config", {})
    repo_label = _repo_label(str(data.get("repository", "unknown")))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Agent Eval · {html.escape(str(data.get('report_id', 'report')))}</title>
  <style>
    :root {{ color-scheme: light; --ink:#172033; --muted:#65718a; --line:#e3e8f0; --paper:#fff; --bg:#f4f7fb; --blue:#3157d5; --green:#16845b; --red:#bd3f45; --amber:#9a6500; }}
    * {{ box-sizing:border-box }} body {{ margin:0; background:var(--bg); color:var(--ink); font:15px/1.55 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif }}
    .shell {{ max-width:1120px; margin:36px auto; padding:0 20px 48px }}
    .hero {{ padding:30px 34px; border-radius:20px; color:white; background:radial-gradient(circle at 90% 0%,#6c85f4 0,transparent 36%),linear-gradient(125deg,#17264d,#314fc1); box-shadow:0 18px 44px #253b7526 }}
    .eyebrow {{ color:#c6d1ff; font-size:12px; font-weight:750; letter-spacing:.14em; text-transform:uppercase }} h1 {{ margin:8px 0 6px; font-size:clamp(28px,4vw,42px); line-height:1.1 }}
    .hero p {{ margin:0; color:#e0e7ff }} .meta {{ display:flex; gap:12px 26px; flex-wrap:wrap; margin-top:22px; color:#d1daf9; font-size:13px }}
    .badge {{ display:inline-flex; align-items:center; gap:7px; padding:6px 11px; border:1px solid #ffffff45; border-radius:999px; font-size:12px; font-weight:750; text-transform:uppercase; letter-spacing:.06em }} .badge.good {{ background:#16845b30 }} .badge.bad {{ background:#bd3f4530 }}
    .grid {{ display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:14px; margin:18px 0 28px }} .metric {{ background:var(--paper); border:1px solid var(--line); border-radius:14px; padding:17px 18px; box-shadow:0 3px 10px #1b2b4a08 }} .metric span {{ display:block; color:var(--muted); font-size:12px; font-weight:650 }} .metric strong {{ display:block; margin-top:5px; font-size:24px; letter-spacing:-.03em }}
    h2 {{ margin:28px 0 12px; font-size:21px }} .case {{ margin:12px 0; overflow:hidden; background:var(--paper); border:1px solid var(--line); border-radius:15px; box-shadow:0 3px 10px #1b2b4a08 }} .case-head {{ display:flex; align-items:center; justify-content:space-between; gap:14px; padding:17px 20px; border-bottom:1px solid var(--line) }} .case-title {{ font-weight:760; overflow-wrap:anywhere }} .status {{ padding:4px 10px; border-radius:999px; font-size:12px; font-weight:750; text-transform:uppercase }} .status.passed {{ color:#106b49; background:#e4f6ed }} .status.failed {{ color:#a52d35; background:#fdebed }}
    .checks {{ display:grid; grid-template-columns:repeat(7,minmax(0,1fr)); gap:9px; padding:16px 20px }} .check {{ border:1px solid var(--line); border-radius:10px; padding:10px 12px }} .check span {{ display:block; color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.04em }} .check strong {{ display:block; margin-top:3px; font-size:14px }} .yes {{ color:var(--green) }} .no {{ color:var(--red) }} .na {{ color:var(--muted) }}
    details {{ border-top:1px solid var(--line); padding:12px 20px }} summary {{ color:var(--blue); cursor:pointer; font-weight:650 }} .details {{ padding-top:8px; color:#34415b }} ul {{ padding-left:20px }} li {{ margin:4px 0 }} code {{ overflow-wrap:anywhere; color:#273c82; background:#eef2ff; padding:2px 5px; border-radius:5px }} a {{ color:var(--blue); text-decoration:none }} a:hover {{ text-decoration:underline }} .empty {{ padding:20px; color:var(--muted) }} .foot {{ margin-top:26px; color:var(--muted); font-size:12px }}
    @media(max-width:850px) {{ .grid {{ grid-template-columns:repeat(2,minmax(0,1fr)) }} .checks {{ grid-template-columns:repeat(3,minmax(0,1fr)) }} }}
    @media(max-width:520px) {{ .shell {{ margin:16px auto; padding:0 12px 30px }} .hero {{ padding:23px 20px }} .grid {{ gap:8px }} .metric {{ padding:13px }} .metric strong {{ font-size:19px }} .checks {{ grid-template-columns:repeat(2,minmax(0,1fr)); padding:12px }} .case-head {{ padding:14px }} }}
    @media print {{ body {{ background:#fff }} .shell {{ margin:0 auto }} .hero {{ box-shadow:none; print-color-adjust:exact }} .metric,.case {{ box-shadow:none; break-inside:avoid }} details {{ break-inside:avoid }} }}
  </style>
</head>
<body><main class="shell">
  <header class="hero">
    <div class="eyebrow">Coding Agent · Evaluation Report</div>
    <h1>{html.escape(str(data.get('report_id', 'Evaluation run')))}</h1>
    <p>Reproducible task results with linked artifacts and explicit pass criteria.</p>
    <div class="meta"><span class="badge {result_class}">{'Passed' if passed == count and count else 'Needs review'} · {passed}/{count}</span><span>Mode: {html.escape(str(data.get('mode', 'unknown')))}</span><span>Created: {html.escape(str(data.get('created_at', 'unknown')))}</span></div>
    <div class="meta"><span>Agent SHA: {html.escape(str(config.get('agent_source_sha') or 'unknown'))}</span><span>Target: {html.escape(repo_label)}</span><span>Runner: {html.escape(str(config.get('runner_version', 'unknown')))}</span><span>Model: {html.escape(_model_label(cases))}</span></div>
    <div class="meta"><span>Eval source patch: {html.escape(_short_hash(config.get('agent_source_dirty_patch_sha256')))}</span></div>
  </header>
  <section class="grid" aria-label="Run summary">
    {_metric('Cases passed', f'{passed} / {count}')}
    {_metric('Failed cases', str(failed))}
    {_metric('Patch apply', _percent(summary.get('patch_apply_rate')))}
    {_metric('Total tokens', _number(summary.get('total_tokens')))}
    {_metric('Total run time', _duration(summary.get('total_latency_ms')))}
  </section>
  <h2>Case results</h2>
  {rows}
  <p class="foot">Generated from report.json. Token values use provider-reported usage when available; missing values are shown as unavailable, never estimated.</p>
</main></body></html>
"""


def _case_card(case: dict[str, Any]) -> str:
    status = str(case.get("status", "unknown"))
    checks = [
        ("Agent", "exit 0" if case.get("agent_exit_code") == 0 else _number(case.get("agent_exit_code"))),
        ("Patch", _check(case.get("patch_apply"))),
        ("Target tests", _check(case.get("target_tests_passed"))),
        ("Regression", _check(case.get("regression_tests_passed"))),
        ("Oracle", _check(case.get("oracle_tests_passed"))),
        ("Retrieval hit@5", _number(case.get("retrieval_hit_at_k"))),
        ("Tool calls", _number(case.get("metadata", {}).get("tool_usage", {}).get("call_count"))),
    ]
    check_html = "".join(
        f'<div class="check"><span>{html.escape(label)}</span><strong class="{_check_class(value)}">{html.escape(value)}</strong></div>'
        for label, value in checks
    )
    errors = case.get("errors", [])
    changed = case.get("changed_files", [])
    artifacts = case.get("artifacts", {})
    metadata = case.get("metadata", {})
    details: list[str] = []
    if metadata.get("model_provider") or metadata.get("model_name"):
        details.append(
            "<p><strong>Model</strong>: "
            + html.escape(" ".join(str(value) for value in (metadata.get("model_provider"), metadata.get("model_name")) if value))
            + "</p>"
        )
    test_behavior = metadata.get("test_behavior", {})
    if test_behavior:
        details.append(
            "<p><strong>Required test files modified</strong>: "
            + html.escape(_check(test_behavior.get("required_test_files_modified")))
            + "</p>"
        )
    tool_usage = metadata.get("tool_usage", {})
    if tool_usage:
        calls_by_tool = tool_usage.get("calls_by_tool", {})
        tools = ", ".join(f"{name}: {count}" for name, count in calls_by_tool.items()) or "none recorded"
        details.append(
            "<p><strong>Tool results</strong>: "
            + html.escape(f"{tool_usage.get('success_count', 0)} successful, {tool_usage.get('failure_count', 0)} failed; {tools}")
            + "</p>"
        )
    if errors:
        details.append("<strong>Issues</strong><ul>" + "".join(f"<li>{html.escape(str(error))}</li>" for error in errors) + "</ul>")
    if changed:
        details.append("<strong>Changed files</strong><ul>" + "".join(f"<li><code>{html.escape(str(path))}</code></li>" for path in changed) + "</ul>")
    if artifacts:
        links = []
        for label, artifact in artifacts.items():
            href = _relative_href(str(artifact))
            links.append(f'<li><a href="{html.escape(href, quote=True)}">{html.escape(str(label))}</a></li>')
        details.append("<strong>Artifacts</strong><ul>" + "".join(links) + "</ul>")
    detail_html = "".join(details) or "<p>No failure details.</p>"
    return f"""<article class="case">
    <div class="case-head"><div class="case-title">{html.escape(str(case.get('case_id', 'unknown')))}</div><span class="status {html.escape(status)}">{html.escape(status)}</span></div>
    <div class="checks">{check_html}</div>
    <details><summary>Details · {_duration(case.get('agent_latency_ms'))} · {_number(case.get('total_tokens'))} tokens</summary><div class="details">{detail_html}</div></details>
  </article>"""


def _metric(label: str, value: str) -> str:
    return f'<div class="metric"><span>{html.escape(label)}</span><strong>{html.escape(value)}</strong></div>'


def _relative_href(value: str) -> str:
    # Run reports store artifact paths relative to the run root; also accept
    # old absolute paths but do not turn them into clickable local file links.
    path = Path(value)
    if path.is_absolute() or ":" in value:
        return "#"
    return str(PurePosixPath(value.replace("\\", "/")))


def _repo_label(value: str) -> str:
    value = value.rstrip("/\\")
    if "://" in value:
        value = value.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
        return value[:-4] if value.endswith(".git") else value
    return Path(value).name or "unknown"


def _model_label(cases: list[dict[str, Any]]) -> str:
    for case in cases:
        metadata = case.get("metadata", {})
        values = [metadata.get("model_provider"), metadata.get("model_name")]
        label = " ".join(str(value) for value in values if value)
        if label:
            return label
    return "N/A"


def _short_hash(value: Any) -> str:
    if not value:
        return "none"
    return str(value)[:12]


def _check(value: Any) -> str:
    if value is True:
        return "PASS"
    if value is False:
        return "FAIL"
    return "N/A"


def _check_class(value: str) -> str:
    return {"PASS": "yes", "FAIL": "no"}.get(value, "na")


def _number(value: Any) -> str:
    return f"{value:,}" if isinstance(value, int) else ("N/A" if value is None else str(value))


def _percent(value: Any) -> str:
    return "N/A" if value is None else f"{float(value) * 100:.0f}%"


def _duration(value: Any) -> str:
    if value is None:
        return "N/A"
    milliseconds = max(0, int(value))
    return f"{milliseconds / 1000:.1f}s" if milliseconds < 120_000 else f"{milliseconds / 60_000:.1f}m"
