# Agent Eval report `df50d8a05b3689cd`

- **Result:** 2/2 cases passed
- **Mode:** `real`
- **Created:** `2026-09-26T11:07:44.636671+00:00`
- **Agent source:** `710862e51e382762de1b3cccf63fdf965d369f4e`
- **Target repository:** `test-coding-eval`
- **Model:** `DeepSeek deepseek-flash`
- **Eval source patch:** `e406940e415d`
- **Total latency:** 2.1m
- **Total tokens:** 1,389,779

## Cases

| Case | Result | Target | Regression | Oracle | Retrieval hit@5 | Tokens | Agent time |
| --- | --- | --- | --- | --- | ---: | ---: | ---: |
| `taskboard-status-filter` | **passed** | PASS | PASS | PASS | 1.0 | 604,297 | 55.7s |
| `taskboard-title-search` | **passed** | PASS | PASS | PASS | 1.0 | 785,482 | 69.2s |

## Failure details

All cases passed.
## Artifacts

- `taskboard-status-filter` agent_output: `cases/taskboard-status-filter/artifacts/agent-output.txt`
- `taskboard-status-filter` patch: `cases/taskboard-status-filter/artifacts/patch.diff`
- `taskboard-status-filter` tests: `cases/taskboard-status-filter/artifacts/tests.log`
- `taskboard-status-filter` trace: `cases/taskboard-status-filter/traces/agent-events.jsonl`
- `taskboard-title-search` agent_output: `cases/taskboard-title-search/artifacts/agent-output.txt`
- `taskboard-title-search` patch: `cases/taskboard-title-search/artifacts/patch.diff`
- `taskboard-title-search` tests: `cases/taskboard-title-search/artifacts/tests.log`
- `taskboard-title-search` trace: `cases/taskboard-title-search/traces/agent-events.jsonl`
