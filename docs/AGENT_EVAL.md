# Coding Agent 的 Agent Eval

Agent Eval 是一套可复跑的评测工具：从固定 Git 提交准备答题副本，启动真实 Agent 或应用 API，收集运行证据，再由测试和评分器判定结果。评测框架是否可靠与 Agent 是否答对是两件事；一次真实运行只能说明这批固定题目的结果。

## 两个被区分的版本

| 版本 | 本轮值 | 用途 |
| --- | --- | --- |
| Eval 框架源码 | `coding-agent@440e70da350820d5988d2c7361d22348ddf40909` | Runner、适配器、隔离、评分和报告 |
| 被测 Agent | `coding-agent@710862e51e382762de1b3cccf63fdf965d369f4e` | 固定的 Agent 实现快照 |
| 独立目标仓库 | `test-coding-eval` | Agent 接到题目后实际修改的项目 |

旧 Agent 提交本身不含后来增加的 Eval telemetry。Runner 会从该提交物化 Agent 运行快照，再叠加单独哈希并记录的 Eval adapter/telemetry 文件。报告分别写出 Agent SHA、框架 SHA 和 adapter SHA，不能把 adapter overlay 说成 Agent 提交的一部分。

## 一次运行做什么

```text
固定 case JSON + 固定 Agent SHA + 固定目标仓库 SHA
  -> 为每道题复制目标仓库并准备独立 SQLite 状态
  -> 在目标副本建立 CodeGraph 索引
  -> 运行真实 Agent adapter，或启动应用后走 HTTP/SSE API
  -> 记录 Agent 工具、检索、事件、Token、耗时、计划和数据库路径
  -> 从 Agent diff 提取补丁并应用到独立验收副本
  -> 运行目标测试、回归测试和隐藏验收
  -> 输出 JSON、Markdown、自包含 HTML 和脱敏公开报告包
```

Agent 只操作 `A:\gyx_cv\coding-agent-eval-runs\runs\<run_id>\cases\<case_id>\workspace` 下的目标副本。主项目源码、其他案例、oracle 副本和 `.env` 不属于答题工作区。这个路径隔离本身不等同于操作系统安全沙箱。

## 固定题目

外部题库位于 `https://github.com/Guo-Yixin/test-coding-eval`，本地工作副本默认是 `A:\gyx_cv\test-coding-eval`。每个 JSON 固定目标 `base_ref`、题面、允许改动文件、目标测试、回归测试、隐藏验收、时限和调用上限。

当前 5 道编码题覆盖状态筛选、标题搜索、优先级别名、按状态分组和组合筛选。题库有意包含未实现功能桩，目标测试失败是 Agent 需要解决的任务。隐藏 oracle 放在被测 coding-agent 的 Eval 目录，不会复制给 Agent。

## 评分字段

| 评分项 | 证据 |
| --- | --- |
| 执行与退出 | 适配器退出码、运行状态、超时和调用上限 |
| 补丁 | 独立 diff、oracle 副本补丁应用、允许文件与必需文件 |
| 行为正确性 | 题目测试、回归测试、评测侧隐藏 oracle |
| 代码检索 | Agent trace 中真实 `hybrid_code_search` 事件及 gold 文件命中位置 |
| 工具使用与恢复 | 工具调用/结果生命周期、确定性注入的一次超时和后续恢复证据 |
| 计划与审批 | 持久化 pending 计划、审批前副本干净、同一线程恢复及计划检查项 |
| 测试习惯 | 要求修改的测试文件是否有补丁，目标测试是否真正执行 |
| 成本和速度 | Provider 返回的输入/输出/总 Token、Agent 时间、各组测试时间 |
| API 端到端 | 健康检查、持久化线程、SSE、审批 API、独立 SQLite 文件、最终状态 |

缺失证据保持 `null`/“不适用”。一项证据缺失不能当成通过。报告不把所有维度塞进一个解释不清的总分。

## 执行命令

真实 Agent 编码题：

```powershell
Set-Location 'C:\Users\ASUS\.codex\worktrees\agent-eval-reliability\coding_agent'
& 'A:\gyx_cv\coding_agent\.venv\Scripts\python.exe' scripts\run_eval.py `
  --dataset 'A:\gyx_cv\test-coding-eval\cases' `
  --repo 'A:\gyx_cv\test-coding-eval' `
  --mode real `
  --env-file 'A:\gyx_cv\coding_agent\.env' `
  --agent-ref 710862e51e382762de1b3cccf63fdf965d369f4e
```

Runner 读取 `.env`，只把模型连接所需变量传给隔离的 Agent 子进程；不会复制或打印该文件。每次运行创建新目录，不能复用旧答题副本。

运行器隔离和计分自身的离线测试：

```powershell
& 'A:\gyx_cv\coding_agent\.venv\Scripts\python.exe' -m pytest `
  tests/unit/test_eval_runner_reliability.py `
  tests/unit/test_eval_agent_adapter.py `
  tests/unit/test_eval_app_adapter.py `
  tests/unit/test_eval_comparison.py `
  tests/unit/test_eval_reporting.py `
  tests/unit/test_eval_public_export.py -q
```

生成公开报告包和多轮比较页：

```powershell
python scripts\export_eval_report.py '<run目录>' 'docs\agent-eval\evidence\<名称>'
python scripts\compare_eval_reports.py `
  --reports '<run1>\report.json' '<run2>\report.json' `
  --output 'docs\agent-eval\evidence\comparison.html'
```

公开导出会按 allowlist 排除数据库和工作区状态，去除机器本地路径并遮盖常见密钥格式；提交前仍需要检查报告内容。

## 本轮真实证据

- 独立编码题真实 suite：`710862e` 在 5 题中通过 **1/5**。5/5 回归测试通过；目标测试、隐藏验收、补丁应用各 1/5；CodeGraph 检索命中率为 1.0；Token 3,511,041；Agent 总耗时 279,942 ms。四道未通过保留完整失败日志，不从汇总中删掉。
- 应用 API 真实案例：固定 Agent 通过本地后端 HTTP/SSE 创建线程、生成并审批计划、恢复同一线程，使用独立 SQLite；目标、回归、隐藏验收通过，生成限定文件补丁。总 Token 675,853，Agent 时间 69,080 ms。
- 应用浏览器真实案例：固定 Agent 通过真实 Chromium/Vue 页面提交同一类编码任务，浏览器展示待批计划、点击审批并显示完成；后端线程、独立 SQLite、代码检索、目标/回归/隐藏验收与两文件补丁均通过。总 Token 1,813,740，Agent 时间 98,709 ms。安全拦截阻止了 Agent 在答题副本提交或推送 Git 变更。
- 合并解读：五题 suite 检验稳定的直接 Agent 路径；API 题检验应用接口到真实 Agent 的一条端到端路径。二者的耗时和 Token 环境不同，不应混作同分布统计。

运行产物保存在 `A:\gyx_cv\coding-agent-eval-runs\runs\<run_id>`。公开 HTML 报告没有外部 CSS/JS，可离线打开和打印。

## 当前覆盖边界

已实现并实跑直接 Agent adapter、计划审批与恢复、计划拒绝、CodeGraph 检索和工具轨迹、独立 SQLite、多题固定题库、隐藏验收、API/SSE 与浏览器应用 adapter、PostgreSQL 持久化组件评测、OpenSandbox 隔离冒烟、中文 HTML/Markdown 报告、脱敏导出和跨报告比较。Runner 自身的全量单元测试为 **105 passed, 1 skipped**，覆盖隔离、补丁、失败诊断、超时和版本指纹。

浏览器端到端已验证一条完整编码路径；API 另有一条真实计划拒绝路径：评分器检查计划中的需求、目标文件、测试文件和验证命令，Runner 拒绝 pending 计划后确认最终状态为 `rejected`，答题副本没有被修改。每道 Agent 案例都会生成 `manual-review.md`，供人工对照最终答复、实际补丁与测试日志，三项结论初始均为“待复核”，不计入自动通过率。报告见 [计划拒绝 HTML](agent-eval/evidence/application-plan-rejection-e2e/report.html)。另有 PostgreSQL 一次性容器专项和真实 OpenSandbox 隔离冒烟案例：前者检查业务 Store、LangGraph Store、Checkpointer、幂等 schema、事务回滚、重连和审计；后者验证安全文件上传、补丁采集、测试、路径穿越拒绝、命令超时和销毁。它们分别是组件级和微型 fixture 证据，不代表整个应用已在 PostgreSQL 上端到端运行，也不代表真实 coding-agent 已在沙箱内完成编码题。报告见 [PostgreSQL HTML](agent-eval/evidence/postgres-persistence-e2e/report.html) 和 [OpenSandbox HTML](agent-eval/evidence/opensandbox-isolation-smoke/report.html)。OpenSandbox 网络边界、上传大小限制和真实 Agent-in-sandbox 路径仍待专门案例验证。

PostgreSQL 专项命令（使用临时容器，结束后自动删除；需要 Docker daemon 和 `postgres:18` 镜像）：

```powershell
python scripts/run_eval_postgres.py
```

OpenSandbox 冒烟命令（需要可用 OpenSandbox Server、Docker Engine，并先构建包含 Git 的小镜像）：

```powershell
docker build -f scripts/opensandbox-smoke.Dockerfile -t coding-agent-eval-alpine-git:3.20 .
$env:OPEN_SANDBOX_DOMAIN = 'http://127.0.0.1:8080'
$env:OPEN_SANDBOX_USE_SERVER_PROXY = '1'
python scripts/run_eval_sandbox_smoke.py
```

也可以通过 `--image` 指定其它 Linux 镜像；沙箱评测镜像须含 Git 和 POSIX shell。冒烟脚本只上传无秘密的微型 fixture，特意带有假 `.env` 与假 SQLite 文件来验证它们会被过滤。外部 OpenSandbox Server 的运维由使用者负责；真实评测结束后应停止服务。

## 解释结果时的限制

固定题可以复跑和比较，但模型输出、Token 和耗时存在随机波动。一次 5 题 suite 是小样本，1/5 只描述当前 Agent、模型、提示和环境下的这次结果，不能推导为所有编程任务的成功率。用于 README 或简历时需附上 Agent SHA、题库 SHA、模型、案例数和真实通过数。
