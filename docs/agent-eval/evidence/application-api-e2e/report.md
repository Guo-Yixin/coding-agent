# Agent Eval 评测报告 `be71ddb4cf48650b`

- **结果：** 1/1 道通过
- **模式：** `real`
- **生成时间：** `2026-09-26T13:05:04.802695+00:00`
- **Agent 提交：** `710862e51e382762de1b3cccf63fdf965d369f4e`
- **目标仓库：** `test-coding-eval`
- **模型：** `DeepSeek deepseek-flash`
- **Agent 适配器：** `none`
- **总耗时：** 69.1s
- **总 Token：** 675,853

## 案例结果

| 案例 | 结果 | 目标测试 | 回归测试 | 隐藏验收 | 检索命中@5 | Token | Agent 耗时 |
| --- | --- | --- | --- | --- | ---: | ---: | ---: |
| `app-api-taskboard-status` | **通过** | 通过 | 通过 | 通过 | 1.0 | 675,853 | 69.1s |

## 未通过原因

所有案例均通过。
## 运行产物

- `app-api-taskboard-status` agent_output: `cases/app-api-taskboard-status/artifacts/agent-output.txt`
- `app-api-taskboard-status` patch: `cases/app-api-taskboard-status/artifacts/patch.diff`
- `app-api-taskboard-status` tests: `cases/app-api-taskboard-status/artifacts/tests.log`
- `app-api-taskboard-status` trace: `cases/app-api-taskboard-status/traces/agent-events.jsonl`
