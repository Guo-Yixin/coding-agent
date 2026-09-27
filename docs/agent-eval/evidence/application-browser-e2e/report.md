# Agent Eval 评测报告 `f495c092cb011578`

- **结果：** 1/1 道通过
- **模式：** `real`
- **生成时间：** `2026-09-26T13:47:53.147967+00:00`
- **Agent 提交：** `710862e51e382762de1b3cccf63fdf965d369f4e`
- **目标仓库：** `test-coding-eval`
- **模型：** `DeepSeek deepseek-flash`
- **Agent 适配器：** `1559b837ac41`
- **总耗时：** 98.7s
- **总 Token：** 1,813,740

## 案例结果

| 案例 | 结果 | 目标测试 | 回归测试 | 隐藏验收 | 检索命中@5 | Token | Agent 耗时 |
| --- | --- | --- | --- | --- | ---: | ---: | ---: |
| `app-api-taskboard-status` | **通过** | 通过 | 通过 | 通过 | 1.0 | 1,813,740 | 98.7s |

## 未通过原因

所有案例均通过。
## 运行产物

- `app-api-taskboard-status` agent_output: `cases/app-api-taskboard-status/artifacts/agent-output.txt`
- `app-api-taskboard-status` patch: `cases/app-api-taskboard-status/artifacts/patch.diff`
- `app-api-taskboard-status` tests: `cases/app-api-taskboard-status/artifacts/tests.log`
- `app-api-taskboard-status` trace: `cases/app-api-taskboard-status/traces/agent-events.jsonl`
