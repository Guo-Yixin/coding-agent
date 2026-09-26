# Agent Eval report `06a5ab49fdc98d4f`

- **Result:** 1/1 cases passed
- **Mode:** `real`
- **Created:** `2026-09-26T10:07:22.844319+00:00`
- **Agent source:** `710862e51e382762de1b3cccf63fdf965d369f4e`
- **Target repository:** `test-coding-eval`
- **Model:** `DeepSeek deepseek-flash`
- **Eval source patch:** `3616ef5b16e6`
- **Total latency:** 71.3s
- **Total tokens:** 1,008,033

## Cases

| Case | Result | Target | Regression | Oracle | Retrieval hit@5 | Tokens | Agent time |
| --- | --- | --- | --- | --- | ---: | ---: | ---: |
| `taskboard-priority-aliases` | **passed** | PASS | PASS | PASS | 1.0 | 1,008,033 | 71.3s |

## Failure details

All cases passed.
## Artifacts

- `taskboard-priority-aliases` agent_output: `cases/taskboard-priority-aliases/artifacts/agent-output.txt`
- `taskboard-priority-aliases` patch: `cases/taskboard-priority-aliases/artifacts/patch.diff`
- `taskboard-priority-aliases` tests: `cases/taskboard-priority-aliases/artifacts/tests.log`
- `taskboard-priority-aliases` trace: `cases/taskboard-priority-aliases/traces/agent-events.jsonl`
