# Agent Eval 评测报告 `845f5b4b8a849a69`

- **结果：** 1/1 道通过
- **模式：** `real`
- **生成时间：** `2026-09-27T03:16:39.274488+00:00`
- **Agent 提交：** `710862e51e382762de1b3cccf63fdf965d369f4e`
- **目标仓库：** `test-coding-eval`
- **模型：** `DeepSeek deepseek-flash`
- **Agent 适配器：** `1559b837ac41`
- **总耗时：** 33.2s
- **总 Token：** 163,761

## 案例结果

| 案例 | 结果 | 目标测试 | 回归测试 | 隐藏验收 | 检索命中@5 | Token | Agent 耗时 |
| --- | --- | --- | --- | --- | ---: | ---: | ---: |
| `app-api-plan-rejection` | **通过** | 通过 | 通过 | 不适用 | N/A | 163,761 | 33.2s |

## 未通过原因

所有案例均通过。
## 运行产物

- `app-api-plan-rejection` agent_output: `cases/app-api-plan-rejection/artifacts/agent-output.txt`
- `app-api-plan-rejection` manual_review: `cases/app-api-plan-rejection/artifacts/manual-review.md`
- `app-api-plan-rejection` patch: `cases/app-api-plan-rejection/artifacts/patch.diff`
- `app-api-plan-rejection` tests: `cases/app-api-plan-rejection/artifacts/tests.log`
- `app-api-plan-rejection` trace: `cases/app-api-plan-rejection/traces/agent-events.jsonl`
