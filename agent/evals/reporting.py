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
    database_mode = data.get("mode") == "database"
    source_label = "组件源码 SHA" if database_mode else "Agent 提交"
    source_sha = data.get("config", {}).get("framework_source_sha") if database_mode else data.get("config", {}).get("agent_source_sha")
    total_tokens = "不适用（未调用模型）" if database_mode else _number(summary.get("total_tokens"))
    lines = [
        f"# Agent Eval 评测报告 `{data.get('report_id', 'unknown')}`",
        "",
        f"- **结果：** {summary.get('passed_count', 0)}/{summary.get('case_count', len(cases))} 道通过",
        f"- **模式：** `{data.get('mode', 'unknown')}`",
        f"- **生成时间：** `{data.get('created_at', 'unknown')}`",
        f"- **{source_label}：** `{source_sha or 'unknown'}`",
        f"- **目标仓库：** `{_repo_label(str(data.get('repository', 'unknown')))}`",
        f"- **模型：** `{_model_label(cases)}`",
        f"- **Agent 适配器：** `{_short_hash(data.get('config', {}).get('agent_adapter_sha256'))}`",
        f"- **总耗时：** {_duration(summary.get('total_latency_ms'))}",
        f"- **总 Token：** {total_tokens}",
        "",
        "## 案例结果",
        "",
    ]
    if database_mode:
        lines.extend([
            "| 案例 | 结果 | 业务 Store | LangGraph Store | Checkpointer | 本机绑定 | 一次性实例 | 清理 | 测试耗时 |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | ---: |",
        ])
    else:
        lines.extend([
            "| 案例 | 结果 | 目标测试 | 回归测试 | 隐藏验收 | 检索命中@5 | Token | Agent 耗时 |",
            "| --- | --- | --- | --- | --- | ---: | ---: | ---: |",
        ])
    for case in cases:
        if database_mode:
            evaluation = case.get("metadata", {}).get("database_evaluation", {})
            components = evaluation.get("component_results", {})
            lines.append(
                "| `{case_id}` | **{status}** | {business} | {store} | {checkpointer} | {localhost} | {ephemeral} | {cleanup} | {latency} |".format(
                    case_id=case.get("case_id", "unknown"),
                    status={"passed": "通过", "failed": "未通过"}.get(str(case.get("status", "unknown")), case.get("status", "unknown")),
                    business=_check(components.get("business_store")),
                    store=_check(components.get("langgraph_store")),
                    checkpointer=_check(components.get("checkpointer")),
                    localhost=_check(evaluation.get("localhost_only")),
                    ephemeral=_check(evaluation.get("ephemeral_instance")),
                    cleanup=_check(evaluation.get("cleanup_succeeded")),
                    latency=_duration(case.get("agent_latency_ms")),
                )
            )
            continue
        lines.append(
            "| `{case_id}` | **{status}** | {target} | {regression} | {oracle} | {retrieval} | {tokens} | {latency} |".format(
                case_id=case.get("case_id", "unknown"),
                status={"passed": "通过", "failed": "未通过"}.get(str(case.get("status", "unknown")), case.get("status", "unknown")),
                target=_check(case.get("target_tests_passed")),
                regression=_check(case.get("regression_tests_passed")),
                oracle=_check(case.get("oracle_tests_passed")),
                retrieval=_number(case.get("retrieval_hit_at_k")),
                tokens=_number(case.get("total_tokens")),
                latency=_duration(case.get("agent_latency_ms")),
            )
        )
    lines.extend(["", "## 未通过原因", ""])
    failures = [case for case in cases if case.get("status") != "passed"]
    if not failures:
        lines.append("所有案例均通过。")
    for case in failures:
        lines.append(f"### `{case.get('case_id', 'unknown')}`")
        lines.append("")
        for error in case.get("errors", []):
            lines.append(f"- {error}")
        lines.append("")
    lines.extend(["## 运行产物", ""])
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
    config = data.get("config", {})
    repo_label = _repo_label(str(data.get("repository", "unknown")))
    database_mode = data.get("mode") == "database"
    if database_mode:
        identity_meta = (
            f"<span>持久化组件 SHA：{html.escape(str(config.get('framework_source_sha') or 'unknown'))}</span>"
            f"<span>数据库镜像：{html.escape(str(config.get('database_image') or 'unknown'))}</span>"
            f"<span>Runner：{html.escape(str(config.get('runner_version', 'unknown')))}</span>"
        )
        component_checks = [item for case in cases for item in case.get("metadata", {}).get("database_evaluation", {}).get("component_results", {}).values()]
        checked = sum(value is True for value in component_checks)
        component_summary = f"{checked}/{len(component_checks)}" if component_checks else "不适用"
        metrics = "\n".join([
            _metric("通过案例", f"{passed} / {count}"),
            _metric("未通过案例", str(failed)),
            _metric("持久化组件", component_summary),
            _metric("总 Token", "不适用"),
            _metric("总耗时", _duration(summary.get("total_latency_ms"))),
        ])
        foot = "本报告通过一次性 PostgreSQL 实例验证项目持久化组件；容器在评测后销毁，未使用开发数据库。"
    else:
        identity_meta = (
            f"<span>Agent 提交：{html.escape(str(config.get('agent_source_sha') or 'unknown'))}</span>"
            f"<span>目标仓库：{html.escape(repo_label)}</span><span>Runner：{html.escape(str(config.get('runner_version', 'unknown')))}</span>"
            f"<span>模型：{html.escape(_model_label(cases))}</span>"
        )
        identity_meta += f"<div class=\"meta\"><span>Agent SHA：{html.escape(str(config.get('agent_source_sha') or 'unknown'))}</span><span>适配器 SHA：{html.escape(_short_hash(config.get('agent_adapter_sha256')))}</span></div>"
        metrics = "\n".join([
            _metric('通过案例', f'{passed} / {count}'),
            _metric('未通过案例', str(failed)),
            _metric('补丁应用率', _percent(summary.get('patch_apply_rate'))),
            _metric('总 Token', _number(summary.get('total_tokens'))),
            _metric('总耗时', _duration(summary.get('total_latency_ms'))),
        ])
        foot = "本页面由 report.json 生成。Token 使用模型服务返回的用量；没有证据时显示为不适用，不会估算。"
    rows = "\n".join(_case_card(case, database_mode=database_mode) for case in cases) or '<p class="empty">No cases were recorded.</p>'
    return f"""<!doctype html>
<html lang="zh-CN">
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
    <div class="eyebrow">CODING Agent · 评测报告</div>
    <h1>{html.escape(str(data.get('report_id', 'Evaluation run')))}</h1>
    <p>每道题都关联明确的验收结果、版本信息和可打开的运行产物。</p>
    <div class="meta"><span class="badge {result_class}">{'全部通过' if passed == count and count else '存在未通过项'} · {passed}/{count}</span><span>模式：{html.escape(str(data.get('mode', 'unknown')))}</span><span>生成时间：{html.escape(str(data.get('created_at', 'unknown')))}</span></div>
    <div class="meta">{identity_meta}</div>
  </header>
  <section class="grid" aria-label="Run summary">
    {metrics}
  </section>
  <h2>案例结果</h2>
  {rows}
  <p class="foot">{html.escape(foot)}</p>
</main></body></html>
"""


def _case_card(case: dict[str, Any], *, database_mode: bool = False) -> str:
    status = str(case.get("status", "unknown"))
    database_evaluation = case.get("metadata", {}).get("database_evaluation", {})
    if database_mode:
        components = database_evaluation.get("component_results", {})
        checks = [
            ("业务 Store", _check(components.get("business_store"))),
            ("LangGraph Store", _check(components.get("langgraph_store"))),
            ("Checkpointer", _check(components.get("checkpointer"))),
            ("本机绑定", _check(database_evaluation.get("localhost_only"))),
            ("一次性数据库", _check(database_evaluation.get("ephemeral_instance"))),
            ("实例清理", _check(database_evaluation.get("cleanup_succeeded"))),
            ("测试进程", _number(case.get("agent_exit_code"))),
        ]
    else:
        checks = [
            ("Agent 退出码", "0" if case.get("agent_exit_code") == 0 else _number(case.get("agent_exit_code"))),
            ("补丁应用", _check(case.get("patch_apply"))),
            ("目标测试", _check(case.get("target_tests_passed"))),
            ("回归测试", _check(case.get("regression_tests_passed"))),
            ("隐藏验收", _check(case.get("oracle_tests_passed"))),
            ("检索命中@5", _number(case.get("retrieval_hit_at_k"))),
            ("工具调用数", _number(case.get("metadata", {}).get("tool_usage", {}).get("call_count"))),
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
    if database_mode and database_evaluation:
        details.append(
            "<p><strong>数据库</strong>："
            + html.escape(f"{database_evaluation.get('image', 'unknown')} · {database_evaluation.get('database_version', 'unknown')} · {database_evaluation.get('database_name', 'unknown')} · {database_evaluation.get('user', 'unknown')}")
            + "</p>"
        )
    if metadata.get("model_provider") or metadata.get("model_name"):
        details.append(
            "<p><strong>模型</strong>："
            + html.escape(" ".join(str(value) for value in (metadata.get("model_provider"), metadata.get("model_name")) if value))
            + "</p>"
        )
    test_behavior = metadata.get("test_behavior", {})
    if test_behavior:
        details.append(
            "<p><strong>要求修改的测试文件</strong>："
            + html.escape(_check(test_behavior.get("required_test_files_modified")))
            + "</p>"
        )
    tool_usage = metadata.get("tool_usage", {})
    if tool_usage:
        calls_by_tool = tool_usage.get("calls_by_tool", {})
        tools = ", ".join(f"{name}: {count}" for name, count in calls_by_tool.items()) or "none recorded"
        details.append(
            "<p><strong>工具结果</strong>："
            + html.escape(f"{tool_usage.get('success_count', 0)} 成功，{tool_usage.get('failure_count', 0)} 失败；{tools}")
            + "</p>"
        )
    api_e2e = metadata.get("api_e2e", {})
    if api_e2e:
        checks = [
            ("服务健康", api_e2e.get("health_passed")),
            ("线程持久化", api_e2e.get("thread_created")),
            ("SSE 消息流", api_e2e.get("sse_received")),
        ]
        if api_e2e.get("rejection_posted") is not None:
            checks.extend([
                ("拒绝计划", api_e2e.get("rejection_posted")),
                ("拒绝后无改动", api_e2e.get("workspace_clean_after_rejection")),
                ("计划状态 rejected", api_e2e.get("final_plan_status") == "rejected"),
            ])
        else:
            checks.append(("计划审批", api_e2e.get("approval_posted")))
        backend = api_e2e.get("persistence_backend", "sqlite")
        if backend == "postgres":
            postgres = api_e2e.get("postgres_e2e", {})
            checks.extend([
                ("一次性 PostgreSQL 身份", postgres.get("identity_verified")),
                ("业务数据和检查点写入", postgres.get("records_persisted")),
                ("服务重启后恢复", postgres.get("reconnect_verified")),
                ("后端重启验证", postgres.get("backend_restarted")),
            ])
        else:
            checks.append(("SQLite 隔离", api_e2e.get("sqlite_isolated")))
        browser = api_e2e.get("browser", {})
        if browser:
            checks.extend([
                ("浏览器提交任务", browser.get("task_submitted")),
                ("浏览器展示待批计划", browser.get("pending_plan_displayed")),
                ("浏览器点击审批", browser.get("approval_clicked")),
                ("浏览器展示完成状态", browser.get("completion_displayed")),
            ])
        summary = "，".join(f"{label}：{_check(value)}" for label, value in checks)
        details.append("<p><strong>应用端到端</strong>：" + html.escape(summary) + "</p>")
    plan_rubric = metadata.get("plan_rubric", [])
    if plan_rubric:
        passed = sum(bool(item.get("passed")) for item in plan_rubric if isinstance(item, dict))
        total = sum(isinstance(item, dict) for item in plan_rubric)
        detail = "；".join(
            f"{' / '.join(map(str, item.get('accepted_terms', [])))}：{_check(item.get('passed'))}"
            for item in plan_rubric
            if isinstance(item, dict)
        )
        details.append(
            "<p><strong>计划质量</strong>："
            + html.escape(f"{passed}/{total} 项通过；{detail}")
            + "</p>"
        )
    sandbox = metadata.get("sandbox", {})
    if sandbox:
        sandbox_text = (
            f"镜像 {sandbox.get('image', 'unknown')}；上传 {sandbox.get('uploaded_file_count', 0)} 个文件；"
            f"服务端代理 {'开启' if sandbox.get('use_server_proxy') else '关闭'}；"
            f"资源清理 {_check(sandbox.get('cleanup_succeeded'))}"
        )
        details.append("<p><strong>OpenSandbox</strong>：" + html.escape(sandbox_text) + "</p>")
        safety = sandbox.get("safety_probes", {})
        if safety:
            safety_text = "，".join(
                f"{label}：{_check(safety.get(key))}"
                for key, label in (
                    ("path_traversal_rejected", "路径穿越拒绝"),
                    ("timeout_enforced", "命令超时"),
                    ("cleanup_succeeded", "探针资源清理"),
                )
            )
            details.append("<p><strong>沙箱安全探针</strong>：" + html.escape(safety_text) + "</p>")
    if errors:
        details.append("<strong>失败原因</strong><ul>" + "".join(f"<li>{html.escape(str(error))}</li>" for error in errors) + "</ul>")
    if changed:
        details.append("<strong>改动文件</strong><ul>" + "".join(f"<li><code>{html.escape(str(path))}</code></li>" for path in changed) + "</ul>")
    if artifacts:
        links = []
        for label, artifact in artifacts.items():
            href = _relative_href(str(artifact))
            links.append(f'<li><a href="{html.escape(href, quote=True)}">{html.escape(str(label))}</a></li>')
        details.append("<strong>运行产物</strong><ul>" + "".join(links) + "</ul>")
    detail_html = "".join(details) or "<p>没有额外说明。</p>"
    status_label = {"passed": "通过", "failed": "未通过"}.get(status, status)
    duration_label = "专项测试耗时" if database_mode else "Agent"
    token_label = "Token 不适用" if database_mode else f"{_number(case.get('total_tokens'))} Token"
    return f"""<article class="case">
    <div class="case-head"><div class="case-title">{html.escape(str(case.get('case_id', 'unknown')))}</div><span class="status {html.escape(status)}">{html.escape(status_label)}</span></div>
    <div class="checks">{check_html}</div>
    <details><summary>详细信息 · {duration_label} {_duration(case.get('agent_latency_ms'))} · {token_label}</summary><div class="details">{detail_html}</div></details>
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
        return "通过"
    if value is False:
        return "未通过"
    return "不适用"


def _check_class(value: str) -> str:
    return {"通过": "yes", "未通过": "no"}.get(value, "na")


def _number(value: Any) -> str:
    return f"{value:,}" if isinstance(value, int) else ("N/A" if value is None else str(value))


def _percent(value: Any) -> str:
    return "N/A" if value is None else f"{float(value) * 100:.0f}%"


def _duration(value: Any) -> str:
    if value is None:
        return "N/A"
    milliseconds = max(0, int(value))
    return f"{milliseconds / 1000:.1f}s" if milliseconds < 120_000 else f"{milliseconds / 60_000:.1f}m"
