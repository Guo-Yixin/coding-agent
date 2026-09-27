# Agent Eval 阶段 0/1：基线与运行器可靠性

本文记录 Agent Eval 在进入更大规模能力评测前的基线约束和离线验收方法。它评测的是“运行器有没有正确准备、隔离、采集和计分”，不代表 Agent 已通过编码能力评测。

## 阶段 0：锁定基线

本轮从 `coding-agent` 的 `main` 同步提交 `440e70da350820d5988d2c7361d22348ddf40909`（短 SHA：`440e70d`）开始。运行器报告需要能追溯两种版本：

- Agent 源码：`report.json.config.agent_source_sha`，以及未提交 Agent 代码的 `agent_source_dirty_patch_sha256`。
- 题目仓库：每个案例 `metadata.target_repo_sha`，取案例 `base_ref`；没有 `base_ref` 时取目标仓库的 `origin/main`。

后续比较两次运行时，应比较这两个完整 SHA、案例 ID、题目配置、模型和调用限制。运行时间、Token 和模型输出本来就可能波动，不要求两次完全相同。相同案例清单的 `report_id` 是清单指纹；实际运行仍写入各自独立的运行目录。

本轮的自动验收采用本地临时 Git 仓库和可控的模拟 Agent 子进程。它会真实经过 real runner 的工作区准备、补丁提取与应用、测试执行、事件和 Token 采集、报告生成，但不会请求模型，也不会连接 PostgreSQL。

## 阶段 1：运行器可靠性契约

`tests/unit/test_eval_runner_reliability.py` 固定检查以下行为：

1. 一次评测中的两个案例从同一个完整目标提交分别准备工作区；两边路径不同，案例间修改互不可见。
2. Agent 的修改只出现在题目副本和补丁中，目标仓库原文件保持原样。
3. 补丁可应用到独立的 oracle 副本，目标测试、回归测试和 oracle 测试针对应用后的副本运行。
4. 目标测试失败时，案例状态和汇总失败数为失败；报告错误与 `tests.log` 保留退出码、标准输出和标准错误，便于定位。
5. 追踪中的检索命中、工具调用和工具结果，以及输入/输出 Token，按可核对的测试数据写入结果。
6. 相同 Agent 提交和目标仓库提交的重复运行报告记录相同的完整 SHA。耗时、Token 不要求相同。

测试会替换 CodeGraph 索引命令的执行结果，但 real runner 仍实际启动本地模拟 adapter，并实际运行 Git 与测试子进程。这样不需要 CodeGraph 服务或模型凭证，也不会把模拟结果当成真实 Agent 能力证据。

## 运行与验收

在项目虚拟环境中执行：

```powershell
python -m pytest tests/unit/test_eval_runner_reliability.py tests/unit/test_eval_runner.py tests/unit/test_eval_reporting.py tests/unit/test_eval_metrics.py -q
```

阶段 0/1 的完成条件：

- 自动化检查全通过。
- 报告能指出目标测试失败原因。
- 同一轮每题有独立工作区和 oracle 工作区，目标仓库不产生 Agent 改动。
- 报告里的 Agent SHA 和目标 SHA 与临时仓库真实 Git SHA 一致。
- Token、检索、工具事件和补丁与模拟 Agent 实际写出的证据一致。

这些离线验收不测试 DeepSeek 是否正确解题、浏览器/HTTP 前后端链路、生产 SQLite/PostgreSQL 行为或操作系统级沙箱隔离。它们分别属于后续 Agent 能力、应用端到端、数据库和沙箱专项阶段。
