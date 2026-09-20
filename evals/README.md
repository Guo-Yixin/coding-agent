# Agent Eval 数据集设计

本项目的 Eval 不把“模型回答得像不像”作为唯一指标，而是把一次代码 Agent 运行拆成可复现的工程结果：

1. 补丁是否成功应用；
2. 目标测试是否通过；
3. 原有回归测试是否通过；
4. 检索是否命中 gold 文件；
5. 工具失败后是否恢复；
6. 输入/输出 Token 与端到端延迟。

## 真实基准的借鉴方式

- **SWE-bench**：从真实 GitHub issue、仓库基线和测试结果构造 patch task；本项目的 `EvalCase` 对应 `prompt`、`repo_path`、`target_tests`、`regression_tests` 和 `gold_files`。
- **Terminal-Bench**：强调终端工具链和环境中的真实操作；本项目记录命令退出码、工具错误恢复和沙箱执行耗时。
- **RepoBench**：强调大型仓库中的代码检索；本项目将 CodeGraph、grep 命中路径写入 `.eval/retrieval.json`，以 `retrieval_hit_at_k` 量化。
- **Agent Evals / trace-based evaluation**：把一次运行的 trace、工具事件和 token usage 作为评测输入；本项目使用 `.eval/events.jsonl` 和 `.eval/usage.json`，报告由固定 schema 生成。

## Case 约定

Agent 命令可以在工作区写入：

- `.eval/retrieval.json`：`[{"path": "agent/core/runtime.py", "rank": 1}]`；
- `.eval/events.jsonl`：每行一个事件，工具恢复事件应包含 `recovered: true`；
- `.eval/usage.json`：`{"input_tokens": 100, "output_tokens": 50}`。

`fake` 模式用于 CI 冒烟和报告 schema 验证；`real` 模式用于本机 Agent；`sandbox` 模式上传去除凭据与运行时缓存后的源码快照，在 OpenSandbox 中执行同一 case。报告中的 `report_id` 由数据集内容稳定哈希得到，适合比较 Prompt、检索策略和工具策略迭代。
