from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any


def render_comparison(reports: list[dict[str, Any]]) -> str:
    """Render multiple run reports as a portable, self-contained Chinese HTML page."""

    if not reports:
        raise ValueError("At least one report is required")
    normalized = [_validate_report(report) for report in reports]
    runs = [_run_summary(report) for report in normalized]
    case_ids = sorted({str(case.get("case_id", "unknown")) for report in normalized for case in report.get("cases", [])})
    cells = []
    for case_id in case_ids:
        by_run = []
        for report in normalized:
            case = next((item for item in report.get("cases", []) if str(item.get("case_id", "unknown")) == case_id), None)
            by_run.append(_case_cell(case))
        cells.append(f"<tr><th>{html.escape(case_id)}</th>{''.join(by_run)}</tr>")
    headers = "".join(f"<th>{html.escape(run['label'])}<small>{html.escape(run['agent_sha'])}</small></th>" for run in runs)
    metric_rows = []
    for label, key, formatter in (
        ("通过题目", "pass_ratio", lambda value: value),
        ("补丁应用率", "patch_rate", lambda value: value),
        ("目标测试通过率", "target_rate", lambda value: value),
        ("回归测试通过率", "regression_rate", lambda value: value),
        ("隐藏验收通过率", "oracle_rate", lambda value: value),
        ("总 Token", "tokens", _number),
        ("Agent 总耗时", "latency", _duration),
    ):
        metric_rows.append(f"<tr><th>{label}</th>{''.join(f'<td>{formatter(run[key])}</td>' for run in runs)}</tr>")
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Agent Eval 多轮对比</title><style>
:root{{--ink:#172033;--muted:#65718a;--line:#e3e8f0;--bg:#f4f7fb;--blue:#3157d5;--green:#16845b;--red:#bd3f45}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 Inter,ui-sans-serif,system-ui,"Segoe UI",sans-serif}}
main{{max-width:1180px;margin:34px auto;padding:0 20px 48px}}header{{padding:28px 32px;border-radius:18px;color:white;background:linear-gradient(125deg,#17264d,#314fc1);box-shadow:0 18px 44px #253b7526}}
h1{{margin:0 0 6px;font-size:clamp(26px,4vw,38px)}}header p{{margin:0;color:#e0e7ff}}section{{margin-top:22px;padding:20px;background:white;border:1px solid var(--line);border-radius:14px;box-shadow:0 3px 10px #1b2b4a08}}
h2{{margin:0 0 14px;font-size:20px}}.scroll{{overflow:auto}}table{{width:100%;border-collapse:collapse;min-width:680px}}th,td{{padding:12px 14px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}thead th{{color:white;background:#263e85}}thead th:first-child{{border-radius:8px 0 0 0}}thead th:last-child{{border-radius:0 8px 0 0}}td{{font-variant-numeric:tabular-nums}}small{{display:block;color:#d1daf9;font-weight:400;margin-top:3px}}.pass{{color:var(--green);font-weight:700}}.fail{{color:var(--red);font-weight:700}}.na{{color:var(--muted)}}.case-detail{{color:var(--muted);font-size:12px;display:block;margin-top:4px;max-width:260px;overflow-wrap:anywhere}}
footer{{padding:18px 2px;color:var(--muted);font-size:12px}}@media print{{body{{background:white}}main{{margin:0 auto}}header,section{{box-shadow:none;break-inside:avoid}}}}
</style></head><body><main><header><h1>Agent Eval 多轮对比</h1><p>按固定案例对照 Agent 版本、验收结果、Token 与运行时间。</p></header>
<section><h2>运行概览</h2><div class="scroll"><table><thead><tr><th>指标</th>{headers}</tr></thead><tbody>{''.join(metric_rows)}</tbody></table></div></section>
<section><h2>逐题结果</h2><div class="scroll"><table><thead><tr><th>固定案例</th>{headers}</tr></thead><tbody>{''.join(cells) or '<tr><td colspan="100%">报告中没有案例。</td></tr>'}</tbody></table></div></section>
<footer>由 report.json 生成的本地单文件报告。不同版本或不同案例集合之间的对比应结合报告中的 Agent 提交号与目标仓库提交号解读。</footer></main></body></html>"""


def compare_report_files(paths: list[Path], output: Path) -> Path:
    reports = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_comparison(reports), encoding="utf-8")
    return output


def _validate_report(report: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(report, dict) or not isinstance(report.get("cases", []), list):
        raise ValueError("Each report must be a JSON object with a cases list")
    return report


def _run_summary(report: dict[str, Any]) -> dict[str, Any]:
    cases = report.get("cases", [])
    summary = report.get("summary", {})
    count = int(summary.get("case_count", len(cases)) or 0)
    passed = int(summary.get("passed_count", sum(case.get("status") == "passed" for case in cases)) or 0)
    config = report.get("config", {})
    report_id = str(report.get("report_id", "unknown"))
    return {
        "label": report_id,
        "agent_sha": str(config.get("agent_source_sha", "unknown"))[:12],
        "pass_ratio": f"{passed}/{count}",
        "patch_rate": _rate(summary.get("patch_apply_rate")),
        "target_rate": _rate(summary.get("target_test_pass_rate")),
        "regression_rate": _rate(summary.get("regression_test_pass_rate")),
        "oracle_rate": _rate(summary.get("oracle_test_pass_rate")),
        "tokens": summary.get("total_tokens"),
        "latency": summary.get("total_latency_ms"),
    }


def _case_cell(case: dict[str, Any] | None) -> str:
    if case is None:
        return '<td class="na">未运行</td>'
    status = str(case.get("status", "unknown"))
    label = {"passed": "通过", "failed": "未通过"}.get(status, status)
    css = "pass" if status == "passed" else "fail" if status == "failed" else "na"
    detail = f"{_number(case.get('total_tokens'))} Token · {_duration(case.get('agent_latency_ms'))}"
    return f'<td><span class="{css}">{html.escape(label)}</span><span class="case-detail">{html.escape(detail)}</span></td>'


def _rate(value: Any) -> str:
    return "不适用" if value is None else f"{float(value) * 100:.1f}%"


def _number(value: Any) -> str:
    return "不适用" if value is None else f"{int(value):,}"


def _duration(value: Any) -> str:
    return "不适用" if value is None else f"{max(0, int(value)) / 1000:.1f} 秒"
