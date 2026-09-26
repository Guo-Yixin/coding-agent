# Agent Eval

Agent Eval runs the production CODING Agent against a version-pinned task repository and grades the resulting behavior with repeatable checks. It is a harness and a benchmark suite; having the harness does not by itself prove high Agent capability.

## Roles

| Item | First-version location | Meaning |
| --- | --- | --- |
| Agent implementation | `coding-agent` at the SHA recorded in the run manifest | The system being evaluated |
| Eval implementation | `coding-agent/agent/evals/` and `coding-agent/scripts/` | Prepares cases, starts the Agent, collects evidence, scores, and renders reports |
| Task repository | `test-coding-eval` at each case's `base_ref` | The independent repository the Agent is asked to change |
| Run output | `A:\gyx_cv\coding-agent-eval-runs\runs\<run_id>` by default | Durable workspaces, isolated state, patches, traces, logs, and reports |

The Agent runtime and the task workspace are separate. Each case starts from its pinned task commit in a new workspace. The Agent's file and shell tools are bound to that workspace. The main source checkout and remote repository are not the answer sheet.

## First-version flow

```text
case JSON + pinned task commit
  -> make per-case workspace and clean oracle workspace
  -> build CodeGraph index for the task copy
  -> start the real Agent runtime in a child process
  -> capture model usage, retrieval, tool events, output, and elapsed time
  -> collect the patch and apply it to the clean oracle copy
  -> run target tests, regression tests, and independent oracle checks
  -> write report.json, report.md, and self-contained report.html
```

The runtime receives a case-specific SQLite configuration. PostgreSQL is explicitly disabled in this first version. Shell commands cannot push or issue remote write actions in Eval mode. The local execution guard limits workspace paths and command/environment access, but this is not an operating-system container boundary; do not use it as a security sandbox for untrusted prompts.

## First benchmark cases

The independent [`test-coding-eval`](https://github.com/Guo-Yixin/test-coding-eval) repository contains a small Python `taskboard` project and three focused cases:

1. `taskboard-status-filter`: case-insensitive status filtering without mutating input data.
2. `taskboard-title-search`: case-insensitive title search with stable order and missing-title safety.
3. `taskboard-priority-aliases`: priority aliases, case handling, stable ordering, and tests for edge cases.

Each case asks the Agent to use `hybrid_code_search`, update its focused test file, and modify only the declared files. Visible target tests and regression tests run after the Agent. Separate evaluator-side oracle checks verify behavior on edge inputs. Oracle files are not copied into the Agent workspace. The benchmark repositories are public, so this version's oracles are independent checks, not secret benchmark material.

## Scoring

The report distinguishes hard pass gates from diagnostic metrics.

| Gate or metric | Evidence |
| --- | --- |
| Agent execution | Child exit code, runtime status, timeout, configured call limits |
| Patch | Git diff against the fresh baseline; clean-baseline apply check; allowed and required file checks |
| Functional behavior | Target tests, regression tests, and evaluator-side oracle checks |
| Test behavior | Whether each case's required test file was changed; the tests themselves are run against the patched code |
| Retrieval | Real `hybrid_code_search` event and whether a case-labeled relevant file appears in the returned results |
| Tool use | Tool calls, available lifecycle results, and calls grouped by tool name |
| Cost and speed | Provider-reported input/output/total tokens when present, Agent latency, and test latency |

Unavailable evidence remains `null`/`N/A`; it is not scored as success or guessed. A tool-recovery rate is only meaningful when the trace includes explicit failure and recovery evidence. First-version report totals are descriptive and must not be read as a broad statistical benchmark; one run per case is a smoke-sized sample.

## Reports

Every run emits:

- `report.json`: complete machine-readable results, case metrics, environment metadata, and artifact paths.
- `report.md`: compact review summary suitable for a PR or issue.
- `report.html`: responsive, self-contained page with run metadata, summary cards, per-case checks, failure details, changed files, and relative artifact links. It has no external CSS or JavaScript dependency and can be opened locally or printed to PDF.
- Per-case `agent-output.txt`, `patch.diff`, `tests.log`, `traces/agent-events.jsonl`, SQLite state files, and a case-level JSON report.

To make a public evidence bundle, use `python scripts/export_eval_report.py <run_dir> <output_dir>`. It allowlists the report and text artifacts, drops machine-specific configuration and SQLite/workspace contents, and redacts local absolute paths and common secret-shaped values. Inspect the bundle before committing it; automated redaction is a safety aid, not a substitute for review. The priority case report is under `docs/agent-eval/evidence/taskboard-priority-rerun/`; the status-filter and title-search reports are under `docs/agent-eval/evidence/status-search-rerun/`. All three cases passed after the retrieval and Windows encoding fixes, across two separate runs. The Eval source changed between runs, so treat them as functional evidence, not a same-build comparison.

The run output is outside the source repository by default. Keep API keys, `.env`, SQLite files, CodeGraph indexes, and full run directories out of Git. For public README evidence, publish a reviewed, sanitized report snapshot after a real run and state the exact Agent SHA, benchmark SHA, model, case count, and pass/fail result. Do not publish an empty, fake-mode, or selectively edited result as real Agent evidence.

## Run

From the `coding-agent` repository with the project virtual environment active:

```powershell
python scripts/run_eval.py `
  --dataset 'A:\gyx_cv\test-coding-eval\cases' `
  --repo 'A:\gyx_cv\test-coding-eval' `
  --mode real `
  --env-file 'A:\gyx_cv\coding_agent\.env'
```

The target repository must be a local Git checkout containing each case's `base_ref`. The `.env` path is read only; model credentials are made available to the Agent child and excluded from the task workspace and report. Each invocation creates a unique run directory. To rerun a case, start a new run rather than reusing its workspace.

## Scope and next suites

Passing these three cases demonstrates a working real-Agent evaluation path on a narrow Python benchmark. It does not establish complete coding-agent correctness, frontend behavior, PostgreSQL compatibility, sandbox security, or performance stability. Those require additional suites:

- Planning, approval/HITL, interruption and resume, and tool-failure recovery scenarios.
- Repository acquisition, diff behavior, denied writes, and workspace-boundary checks.
- Application E2E through the actual API and browser with isolated ports and state.
- SQLite and disposable PostgreSQL persistence checks.
- OpenSandbox isolation tests where an OS/container boundary is required.
- A feature inventory mapping each important product flow to tests and evaluation cases.

Repeat expensive model cases before comparing rates or latency. Reports should include run count and should compare the same model, prompts, task commit, Agent commit, concurrency, and machine environment.
