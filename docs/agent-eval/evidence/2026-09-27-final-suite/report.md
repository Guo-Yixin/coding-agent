# Agent Eval 评测报告 `d3ae062b594d093d`

- **结果：** 10/10 道通过
- **模式：** `real`
- **生成时间：** `2026-09-27T06:12:20.630571+00:00`
- **Agent 提交：** `逐题记录固定 Agent SHA，见案例详情`
- **目标仓库：** `test-coding-eval`
- **模型：** `DeepSeek deepseek-flash`
- **Agent 适配器：** `none`
- **总耗时：** 10.2m
- **总 Token：** 6,963,895

## 案例结果

| 案例 | 结果 | 目标测试 | 回归测试 | 隐藏验收 | 检索命中@5 | Token | Agent 耗时 |
| --- | --- | --- | --- | --- | ---: | ---: | ---: |
| `taskboard-group-by-status` | **通过** | 通过 | 通过 | 通过 | 1.0 | 370,541 | 45.4s |
| `taskboard-priority-aliases` | **通过** | 通过 | 通过 | 通过 | 1.0 | 1,013,495 | 65.3s |
| `taskboard-select-tasks` | **通过** | 通过 | 通过 | 通过 | 1.0 | 527,872 | 61.1s |
| `taskboard-status-filter` | **通过** | 通过 | 通过 | 通过 | 1.0 | 1,034,896 | 68.1s |
| `taskboard-title-search` | **通过** | 通过 | 通过 | 通过 | 1.0 | 337,771 | 46.6s |
| `taskboard-count-by-status` | **通过** | 通过 | 通过 | 通过 | 1.0 | 787,941 | 66.4s |
| `taskboard-filter-by-priority` | **通过** | 通过 | 通过 | 通过 | 1.0 | 538,069 | 62.3s |
| `taskboard-find-overdue-tasks` | **通过** | 通过 | 通过 | 通过 | 1.0 | 804,570 | 67.7s |
| `taskboard-merge-task-updates` | **通过** | 通过 | 通过 | 通过 | 1.0 | 556,928 | 56.4s |
| `taskboard-paginate-tasks` | **通过** | 通过 | 通过 | 通过 | 1.0 | 991,812 | 74.7s |

## 未通过原因

所有案例均通过。
## 运行产物

- `taskboard-group-by-status` agent_output: `cases/taskboard-group-by-status/remediation-old-five-a6941fb/artifacts/agent-output.txt`
- `taskboard-group-by-status` manual_review: `cases/taskboard-group-by-status/remediation-old-five-a6941fb/artifacts/manual-review.md`
- `taskboard-group-by-status` patch: `cases/taskboard-group-by-status/remediation-old-five-a6941fb/artifacts/patch.diff`
- `taskboard-group-by-status` tests: `cases/taskboard-group-by-status/remediation-old-five-a6941fb/artifacts/tests.log`
- `taskboard-group-by-status` trace: `cases/taskboard-group-by-status/remediation-old-five-a6941fb/traces/agent-events.jsonl`
- `taskboard-priority-aliases` agent_output: `cases/taskboard-priority-aliases/remediation-old-five-a6941fb/artifacts/agent-output.txt`
- `taskboard-priority-aliases` manual_review: `cases/taskboard-priority-aliases/remediation-old-five-a6941fb/artifacts/manual-review.md`
- `taskboard-priority-aliases` patch: `cases/taskboard-priority-aliases/remediation-old-five-a6941fb/artifacts/patch.diff`
- `taskboard-priority-aliases` tests: `cases/taskboard-priority-aliases/remediation-old-five-a6941fb/artifacts/tests.log`
- `taskboard-priority-aliases` trace: `cases/taskboard-priority-aliases/remediation-old-five-a6941fb/traces/agent-events.jsonl`
- `taskboard-select-tasks` agent_output: `cases/taskboard-select-tasks/remediation-old-five-a6941fb/artifacts/agent-output.txt`
- `taskboard-select-tasks` manual_review: `cases/taskboard-select-tasks/remediation-old-five-a6941fb/artifacts/manual-review.md`
- `taskboard-select-tasks` patch: `cases/taskboard-select-tasks/remediation-old-five-a6941fb/artifacts/patch.diff`
- `taskboard-select-tasks` tests: `cases/taskboard-select-tasks/remediation-old-five-a6941fb/artifacts/tests.log`
- `taskboard-select-tasks` trace: `cases/taskboard-select-tasks/remediation-old-five-a6941fb/traces/agent-events.jsonl`
- `taskboard-status-filter` agent_output: `cases/taskboard-status-filter/remediation-old-status-filter-8c467aa/artifacts/agent-output.txt`
- `taskboard-status-filter` manual_review: `cases/taskboard-status-filter/remediation-old-status-filter-8c467aa/artifacts/manual-review.md`
- `taskboard-status-filter` patch: `cases/taskboard-status-filter/remediation-old-status-filter-8c467aa/artifacts/patch.diff`
- `taskboard-status-filter` tests: `cases/taskboard-status-filter/remediation-old-status-filter-8c467aa/artifacts/tests.log`
- `taskboard-status-filter` trace: `cases/taskboard-status-filter/remediation-old-status-filter-8c467aa/traces/agent-events.jsonl`
- `taskboard-title-search` agent_output: `cases/taskboard-title-search/remediation-old-five-a6941fb/artifacts/agent-output.txt`
- `taskboard-title-search` manual_review: `cases/taskboard-title-search/remediation-old-five-a6941fb/artifacts/manual-review.md`
- `taskboard-title-search` patch: `cases/taskboard-title-search/remediation-old-five-a6941fb/artifacts/patch.diff`
- `taskboard-title-search` tests: `cases/taskboard-title-search/remediation-old-five-a6941fb/artifacts/tests.log`
- `taskboard-title-search` trace: `cases/taskboard-title-search/remediation-old-five-a6941fb/traces/agent-events.jsonl`
- `taskboard-count-by-status` agent_output: `cases/taskboard-count-by-status/remediation-new-five-139e970/artifacts/agent-output.txt`
- `taskboard-count-by-status` manual_review: `cases/taskboard-count-by-status/remediation-new-five-139e970/artifacts/manual-review.md`
- `taskboard-count-by-status` patch: `cases/taskboard-count-by-status/remediation-new-five-139e970/artifacts/patch.diff`
- `taskboard-count-by-status` tests: `cases/taskboard-count-by-status/remediation-new-five-139e970/artifacts/tests.log`
- `taskboard-count-by-status` trace: `cases/taskboard-count-by-status/remediation-new-five-139e970/traces/agent-events.jsonl`
- `taskboard-filter-by-priority` agent_output: `cases/taskboard-filter-by-priority/remediation-new-priority-oracle-rescore-9b07905/artifacts/agent-output.txt`
- `taskboard-filter-by-priority` manual_review: `cases/taskboard-filter-by-priority/remediation-new-priority-oracle-rescore-9b07905/artifacts/manual-review.md`
- `taskboard-filter-by-priority` patch: `cases/taskboard-filter-by-priority/remediation-new-priority-oracle-rescore-9b07905/artifacts/patch.diff`
- `taskboard-filter-by-priority` tests: `cases/taskboard-filter-by-priority/remediation-new-priority-oracle-rescore-9b07905/artifacts/tests.log`
- `taskboard-find-overdue-tasks` agent_output: `cases/taskboard-find-overdue-tasks/remediation-new-five-139e970/artifacts/agent-output.txt`
- `taskboard-find-overdue-tasks` manual_review: `cases/taskboard-find-overdue-tasks/remediation-new-five-139e970/artifacts/manual-review.md`
- `taskboard-find-overdue-tasks` patch: `cases/taskboard-find-overdue-tasks/remediation-new-five-139e970/artifacts/patch.diff`
- `taskboard-find-overdue-tasks` tests: `cases/taskboard-find-overdue-tasks/remediation-new-five-139e970/artifacts/tests.log`
- `taskboard-find-overdue-tasks` trace: `cases/taskboard-find-overdue-tasks/remediation-new-five-139e970/traces/agent-events.jsonl`
- `taskboard-merge-task-updates` agent_output: `cases/taskboard-merge-task-updates/remediation-new-five-139e970/artifacts/agent-output.txt`
- `taskboard-merge-task-updates` manual_review: `cases/taskboard-merge-task-updates/remediation-new-five-139e970/artifacts/manual-review.md`
- `taskboard-merge-task-updates` patch: `cases/taskboard-merge-task-updates/remediation-new-five-139e970/artifacts/patch.diff`
- `taskboard-merge-task-updates` tests: `cases/taskboard-merge-task-updates/remediation-new-five-139e970/artifacts/tests.log`
- `taskboard-merge-task-updates` trace: `cases/taskboard-merge-task-updates/remediation-new-five-139e970/traces/agent-events.jsonl`
- `taskboard-paginate-tasks` agent_output: `cases/taskboard-paginate-tasks/remediation-new-five-139e970/artifacts/agent-output.txt`
- `taskboard-paginate-tasks` manual_review: `cases/taskboard-paginate-tasks/remediation-new-five-139e970/artifacts/manual-review.md`
- `taskboard-paginate-tasks` patch: `cases/taskboard-paginate-tasks/remediation-new-five-139e970/artifacts/patch.diff`
- `taskboard-paginate-tasks` tests: `cases/taskboard-paginate-tasks/remediation-new-five-139e970/artifacts/tests.log`
- `taskboard-paginate-tasks` trace: `cases/taskboard-paginate-tasks/remediation-new-five-139e970/traces/agent-events.jsonl`
