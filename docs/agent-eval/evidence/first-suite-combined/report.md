# Agent Eval · First benchmark suite

- **Result:** 3/3 cases passed across 2 real runs
- **Model:** DeepSeek `deepseek-flash`
- **Agent base SHA:** `710862e51e382762de1b3cccf63fdf965d369f4e`
- **Benchmark baseline:** `d19ddda0ac269adf1e68d7d2840968527b313bc4`
- **Aggregate Agent time:** 196.3s
- **Aggregate provider-reported tokens:** 2,397,812

> Aggregate view only: the three cases passed across two runs. The Eval source dirty fingerprint differs between runs, so these results are not a same-build comparison.

| Case | Result | Target | Regression | Oracle | Retrieval hit@5 | Agent time | Tokens | Source run |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | --- |
| `taskboard-priority-aliases` | **passed** | PASS | PASS | PASS | 1.0 | 71.3s | 1,008,033 | `06a5ab49fdc98d4f` |
| `taskboard-status-filter` | **passed** | PASS | PASS | PASS | 1.0 | 55.7s | 604,297 | `df50d8a05b3689cd` |
| `taskboard-title-search` | **passed** | PASS | PASS | PASS | 1.0 | 69.2s | 785,482 | `df50d8a05b3689cd` |

## Source reports

- `06a5ab49fdc98d4f` · Eval patch fingerprint `3616ef5b16e6` · cases: taskboard-priority-aliases
- `df50d8a05b3689cd` · Eval patch fingerprint `e406940e415d` · cases: taskboard-status-filter, taskboard-title-search

## Artifacts

- `taskboard-priority-aliases` [agent_output](cases/taskboard-priority-aliases/artifacts/agent-output.txt)
- `taskboard-priority-aliases` [patch](cases/taskboard-priority-aliases/artifacts/patch.diff)
- `taskboard-priority-aliases` [tests](cases/taskboard-priority-aliases/artifacts/tests.log)
- `taskboard-priority-aliases` [trace](cases/taskboard-priority-aliases/traces/agent-events.jsonl)
- `taskboard-status-filter` [agent_output](cases/taskboard-status-filter/artifacts/agent-output.txt)
- `taskboard-status-filter` [patch](cases/taskboard-status-filter/artifacts/patch.diff)
- `taskboard-status-filter` [tests](cases/taskboard-status-filter/artifacts/tests.log)
- `taskboard-status-filter` [trace](cases/taskboard-status-filter/traces/agent-events.jsonl)
- `taskboard-title-search` [agent_output](cases/taskboard-title-search/artifacts/agent-output.txt)
- `taskboard-title-search` [patch](cases/taskboard-title-search/artifacts/patch.diff)
- `taskboard-title-search` [tests](cases/taskboard-title-search/artifacts/tests.log)
- `taskboard-title-search` [trace](cases/taskboard-title-search/traces/agent-events.jsonl)
