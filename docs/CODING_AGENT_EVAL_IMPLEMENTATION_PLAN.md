# CODING Agent Eval implementation plan

This is the implementation checklist for the first usable Agent Eval release. The user confirmed this scope on 2026-09-26. Keep the eval implementation, task benchmark, and per-run artifacts in their assigned locations. Do not describe three smoke cases as complete project coverage.

## 1. Accepted first-version scope

- Use the production CODING Agent runtime and the configured DeepSeek model in `real` mode.
- The initial Agent source baseline is the user's confirmed `coding-agent` commit `710862e51e382762de1b3cccf63fdf965d369f4e`; every run must record the full source SHA and any dirty source patch fingerprint.
- Use the independent public `test-coding-eval` repository as the task project, not the coding-agent source repository.
- Pin each case to target baseline `d19ddda0ac269adf1e68d7d2840968527b313bc4` until an intentional benchmark update changes it.
- Prepare a fresh case workspace and a separate clean oracle workspace for every case.
- First suite: case-insensitive status filtering, case-insensitive title search, and priority aliases/stable ordering.
- Score Agent execution, patch scope/application, required test-file edits, target tests, regression tests, independent oracle checks, observed retrieval, observed tools, Token usage, and latency.
- Generate `report.json`, `report.md`, and self-contained `report.html` from the same report object.
- Keep runtime artifacts under `A:\gyx_cv\coding-agent-eval-runs\runs\<run_id>` and do not add them to Git.
- Do not push, create a PR, or publish report evidence without a separate user request. Local commits used to pin the benchmark baseline are acceptable and must be disclosed.

## 2. Repository and data boundaries

| Path | Role | Git policy |
| --- | --- | --- |
| `A:\gyx_cv\coding_agent` | Main project checkout; at start it is `710862e` and matches `origin/main` | Do not modify or clean the user's existing local changes |
| `C:\Users\ASUS\.codex\worktrees\agent-eval-implementation\coding_agent` | Eval implementation worktree | Framework source, tests, docs; candidate PR 1 |
| `A:\gyx_cv\test-coding-eval` | Independent benchmark repo | Fixture app and case manifests; candidate PR 2 |
| `A:\gyx_cv\coding-agent-eval-runs\runs\<run_id>` | Per-run durable output | Never commit `.env`, DBs, traces, patches, reports, indexes, or workspaces by default |

For a run, distinguish `agent_source_sha` (the Agent being tested) from `target_repo_sha` (the task project's starting commit). They can be the same only in an explicitly labeled self-modification case.

Suggested run layout:

```text
<run_id>/
  run.json
  report.json
  report.md
  report.html
  cases/<case_id>/
    workspace/projects/<owner-repo>/   # Agent may modify this copy
    oracle/repo/                       # Evaluator applies patch and scores here
    state/*.sqlite                     # Per-case application persistence only
    traces/agent-events.jsonl
    artifacts/agent-output.txt
    artifacts/patch.diff
    artifacts/tests.log
    artifacts/report.json
```

The oracle checkout must be inaccessible through the Agent's file tools and must never be included in its `AI_WORKSPACE_ROOT`. Local process guards are a development isolation layer, not a substitute for an OS/container sandbox against hostile prompts.

## 3. Scoring contract

### Hard gates

An implementation case passes only if all required conditions hold:

1. Real Agent adapter starts and returns the expected runtime status before timeout/limits.
2. A patch exists, obeys `allowed_files`, touches `required_changed_files`, and applies to a clean oracle baseline.
3. Target tests pass.
4. Declared regression tests pass.
5. Evaluator-side oracle checks pass.
6. If `gold_files` are configured, a real retrieval event is recorded and a relevant file is returned.

Missing required evidence is a failure or `null` as appropriate; it is never silently counted as success. Read-only cases are explicitly marked and must have no changed files. Test-file edits prove that the Agent touched requested tests, not that those tests are high quality; mutation testing is a later suite.

### Diagnostic metrics

- Retrieval hit@k only uses results recorded from the Agent's actual retrieval calls and case-labeled paths.
- Tool metrics count observed calls and lifecycle results. Recovery rate remains null unless the trace explicitly identifies a failure and subsequent recovery.
- Token counts come from provider/SDK usage when available. Missing values stay null with a reason; do not estimate exact usage from prompt length.
- Latency separates Agent time, target tests, regression tests, oracle checks, and case total where present.
- Report denominator counts next to pass rates. Do not merge unlike metrics into one score.

## 4. Human-readable report requirements

The same report data must drive JSON, Markdown, and HTML. The HTML page must:

- work offline with embedded CSS and no remote fonts/scripts;
- show run result, case count, Agent SHA, target repository, and creation time;
- show per-case Agent, patch, target, regression, oracle, retrieval, and tool checks;
- show Token usage, elapsed time, changed files, failure explanations, and relative artifact links;
- use responsive layout and print styles;
- escape untrusted Agent output, error text, case ids, and paths before rendering;
- display unavailable metrics as `N/A`, not zero or success.

README evidence is added only after a real run. Publish a reviewed/sanitized report snapshot with the exact Agent SHA, benchmark SHA, model, case count, run count, and actual pass/fail results. Never turn a fake-mode or failed run into a success claim. The public benchmark is not a secret benchmark; label evaluator-side checks accurately.

## 5. Implementation order and acceptance

### Stage A: runner and report correctness

- Validate case JSON and target commits; create unique run/case directories; reject overwrites.
- Keep target and oracle copies separate and record their paths/SHAs.
- Preserve fake mode as an explicit unit-test path; real mode must fail closed if the Agent adapter or required index is unavailable.
- Add report denominator/tool metrics and JSON/Markdown/HTML generation.
- Unit-test report escaping, relative artifact links, unavailable values, isolation behavior, scorer gates, and real-mode failure behavior.

**Accept when:** relevant Eval unit tests pass; HTML is readable offline; report artifacts agree; paths and secrets are not exposed; fake mode cannot satisfy real-mode gates.

### Stage B: independent target benchmark

- Create and pin the `taskboard` fixture in `test-coding-eval`.
- Add three case JSON files using the fixed baseline SHA.
- Add evaluator-side oracle scripts in `coding-agent/agent/evals/oracles/`, outside target copies.
- Verify the unmodified benchmark baseline passes its regression tests and fails each task-specific acceptance test for the intended reason.

**Accept when:** cases resolve target commits, each target test has a meaningful red baseline, each regression suite has a green baseline, and oracle scripts are not copied into workspaces.

### Stage C: real Agent smoke and evidence

- Use the project's existing DeepSeek configuration through the explicit `--env-file` option.
- Run cases individually first; inspect source/target SHA, case repo binding, CodeGraph index, event files, SQLite paths, patch, and report before scaling to all cases.
- Run the initial three cases at most once each for smoke evidence. Do not call one run a statistical benchmark.
- Record actual model/usage fields; if the provider omits usage, leave it unavailable.
- Inspect reports for secret redaction and verify the main checkout's files and data were not modified.

**Accept when:** each case has a truthful passed/failed report with logs and patch; all three run directories are distinct; the Agent changed only the benchmark copy; model credentials are absent from output; report HTML opens offline.

### Stage D: documentation and PR preparation

- Document architecture, command, scorer behavior, report files, limits, and next suites in `README.md` and `docs/AGENT_EVAL.md`.
- Candidate PR 1: framework/runtime integration, scorers/report renderer, tests, and project documentation.
- Candidate PR 2: benchmark fixture, public tests, case configs, and benchmark README.
- Exclude run output, `.env`, SQLite files, `.codegraph`, Python caches, and existing user files.
- Do not push or create PRs during implementation; return exact file lists and local branch/commit status.

**Accept when:** both candidate diffs are reviewable and separated by purpose; README claims match real evidence; no credentials or runtime artifacts are tracked.

## 6. Later evaluation suites

After the first coding benchmark is stable, add separate case types and evaluators for planning/HITL/resume, injected tool errors, repository operations, test quality/mutation, API and browser E2E, SQLite persistence, disposable PostgreSQL, and OpenSandbox. Maintain a feature coverage map that labels each product area as tested, partially tested, or not yet covered. A handful of cases never establishes complete project coverage.
