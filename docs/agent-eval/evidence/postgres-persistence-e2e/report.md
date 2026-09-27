# Agent Eval 评测报告 `70aa97e37c6c4a72`

- **结果：** 1/1 道通过
- **模式：** `database`
- **生成时间：** `2026-09-27T03:02:44.982385+00:00`
- **组件源码 SHA：** `440e70da350820d5988d2c7361d22348ddf40909`
- **目标仓库：** `coding-agent`
- **模型：** `N/A`
- **Agent 适配器：** `none`
- **总耗时：** 6.5s
- **总 Token：** 不适用（未调用模型）

## 案例结果

| 案例 | 结果 | 业务 Store | LangGraph Store | Checkpointer | 本机绑定 | 一次性实例 | 清理 | 测试耗时 |
| --- | --- | --- | --- | --- | --- | --- | --- | ---: |
| `postgres-persistence-smoke` | **通过** | 通过 | 通过 | 通过 | 通过 | 通过 | 通过 | 1.7s |

## 未通过原因

所有案例均通过。
## 运行产物

- `postgres-persistence-smoke` tests: `cases/postgres-persistence-smoke/tests.log`
