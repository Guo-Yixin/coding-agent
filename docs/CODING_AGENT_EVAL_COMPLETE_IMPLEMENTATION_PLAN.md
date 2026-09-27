# Coding Agent 完整评测体系实施方案

## 目标与范围

本方案把两个相关但不同的目标都做完：

1. **评测 coding-agent 的能力。** 被测 Agent 固定为历史基线 `710862e51e382762de1b3cccf63fdf965d369f4e`，使用独立目标仓库和固定题目；不能把修改 coding-agent 自身仓库的结果当成通用编码能力证据。
2. **验证 coding-agent 自带的 Agent Eval 功能可复用。** 用户能给它一个目标 Git 仓库、基线提交和案例集，使用 real/fake/sandbox 适配器之一，得到隔离副本、可验证评分和完整报告。

评测框架的开发代码基于已同步的 `coding-agent` 提交 `440e70da350820d5988d2c7361d22348ddf40909`，在独立 Codex worktree 中修改。框架版本与被测 Agent 版本是两个输入，分别记录；本方案不因框架更新而自动改变 Agent 基线。最终只提交可审查分支和报告，**用户确认之前不创建或推送 PR**。

## 目录和信任边界

```text
A:\gyx_cv\coding_agent
  用户主工作区；只用于读取同步后的提交，不放评测生成物

C:\Users\ASUS\.codex\worktrees\agent-eval-reliability\coding_agent
  本次 Eval 框架开发 worktree，分支 codex/agent-eval-reliability-440e70d

A:\gyx_cv\coding-agent-eval-runs\runs\<run_id>\
  manifest.json、report.json/.md/.html、固定 Agent 运行快照和证据
  agent-runtime\                         coding-agent @ 固定完整 SHA
  cases\<case_id>\workspace\             目标仓库答题副本
  cases\<case_id>\oracle\repo\           独立验收副本
  cases\<case_id>\db\                    此案例独立 SQLite 文件
  cases\<case_id>\artifacts\             patch、测试日志和 Agent 输出
  cases\<case_id>\traces\                检索、工具、状态和模型用量轨迹

A:\gyx_cv\test-coding-eval\
  独立目标题库；每个案例固定目标仓库完整 SHA
```

主工作区当前有用户自有未跟踪资料。实施必须只修改本 worktree 中的代码和文档；评测只能读取 `.env` 中的模型配置，不能复制 `.env` 到 Agent 快照、目标仓库副本、报告或 Git。评测生成物一律写到独立 run 目录。Agent 子进程的代码快照和答题仓库副本要互相分离；每个案例的答题副本、oracle 副本和 SQLite 文件也互相分离。

本地路径隔离是防止误覆盖和串数据的工程措施，不等同于操作系统级安全沙箱。面向不可信代码的安全结论必须由实际 OpenSandbox/容器专项测试支持。

## 统一运行流程

```text
固定案例清单 + 固定 Agent SHA + 固定目标仓库 SHA
  -> 生成 run manifest 并校验所有 SHA
  -> 物化 Agent runtime 快照、每题 workspace、oracle 和独立 DB
  -> 构建目标仓库 CodeGraph 索引
  -> 启动真实 Agent 子进程，或应用/API/browser adapter
  -> 采集结构化事件、模型 usage、输出、耗时和改动
  -> 生成补丁并应用到干净 oracle
  -> 执行 target、regression、hidden oracle 和专项评分器
  -> 生成 JSON、Markdown、自包含 HTML 和可公开脱敏证据包
```

每个评分器提供通用字段加类型专属字段。硬门槛与诊断指标分开，不合成没有解释力的总分。缺少证据时写 `null`/`not_applicable` 并降低证据完整度，不能猜测为通过。

## 实施阶段与验收门

### 阶段 0：基线锁定和工作树检查

- 确认主项目 `main` 与远端同步提交为 `440e70d…`；保护已有个人文件。
- 固定被测 Agent 完整提交 `710862e…`，报告记录 Agent SHA、dirty patch 指纹、模型/provider 和运行器版本。
- 固定独立题库提交。`test-coding-eval` 当前已同步远端：题库 PR 合并提交为 `d650477…`，三个案例仍锁定其祖先提交 `d19ddda0ac269adf1e68d7d2840968527b313bc4`，且该对象存在。
- 每次报告通过 manifest 记录 Agent SHA、目标仓库 URL/SHA、案例 JSON 哈希、代码图版本、Python 版本、模型名、限制和时间。
- 被测提交 `710862e…` 本身不含当前 `scripts/run_eval_agent.py` 和 Eval telemetry 文件。真实运行必须把 Agent 原始 Git archive 与单独 hash 的 Eval adapter/telemetry overlay 组合，明确记录两者；不得把 adapter overlay 谎报为 Agent commit 内容。

**验收：** 版本字段来自 Git/实际 runtime，而不是手写短 SHA；缺提交、脏工作树策略不明确、SHA 不可解析时 fail closed。

### 阶段 1：Runner 可靠性

- 离线集成测试覆盖每题独立 workspace/oracle/DB、源仓库不变、跨案例无污染、未跟踪补丁捕获与 oracle 应用。
- 注入 Agent 非零退出、target/regression/oracle 失败、超时、缺 trace/usage 等故障；报告显示精确阶段、命令、退出码、有限长度 stdout/stderr 和 artifact 链接。
- 核对 retrieval/tool/token/latency/patch 字段对 trace 与 usage 原始证据；校验 `total_tokens` 有 provider total 时使用 provider 值，否则仅在 input/output 都有时相加。
- 相同配置重复运行可核对 Agent SHA、目标 SHA 和案例清单哈希一致；不要求耗时、Token、模型输出完全一样。
- 在整个真实 Agent run 开始前制作固定的 `agent-runtime` 快照并从快照启动 adapter。SHA 在启动前锁定，run 完成后再校验快照未变化。

**验收：** 所有 Runner 单元/离线集成测试通过；无模型 API 调用的故障注入覆盖可复现；source、其他 case 和 oracle 之间无非预期写入。

### 阶段 2：独立仓库编码能力题库（5～10 题）

- 沿用已有 3 道 Taskboard 题及其隐藏验收，确认其目标 SHA 为固定题库提交并保存原有报告。
- 补足到至少 5 道，目标为 8 道：至少覆盖 Bug 修复、功能增加、跨文件改动、补充有效测试、边界条件/兼容性；每题有明确需求条目、allowed files、target/regression/oracle 测试、超时和模型/工具上限。
- 每题起始仓库由固定完整 SHA 的独立目标仓库生成，不使用 coding-agent 自己作为目标仓库。
- 运行固定 Agent `710862e…`；保留原始 JSON/trace/patch/log。真实模型评测按案例和 suite 记录模型名、Token、运行时间及失败原因。
- 结果说明能力用结构化对照表评分：Agent 声明的改动和测试结果逐项与 patch/test log 比对；初期人工抽查，不把模型裁判作为唯一门槛。

**验收：** 题目 5～10 道，所有配置和 SHA 锁定；报告逐题可重跑；能力指标有证据来源；不得把一次通过写成普遍能力保证。

### 阶段 3：交互与运行能力题

- 多要求任务：每项需求有单独验收，输出需求覆盖率及未满足项。
- 计划与审批：验证计划结构、状态为 pending、未审批前没有代码写入；批准后恢复同一 run 并完成；拒绝后状态和写入边界正确。
- 工具错误恢复：确定性注入一次可恢复错误，检查失败事件、重试/替代动作和最终结果关联同一 `tool_call_id`。
- 测试行为：要求 Agent 补测试，确认允许路径中的测试文件发生变化、测试真实运行；可增加 mutation probe 验证测试能发现预设错误。
- 评分分为硬门槛和诊断指标，保留人工 review 表格用于计划与结果说明。

**验收：** 每种情景至少一个固定案例；无事件数据时不计算通过率；HITL 检查需要持久化状态和恢复链路，而非只对文本做断言。

### 阶段 4：应用端到端 adapter

- 从 Agent 固定版本 `710862e…` 创建运行快照；以独立 `CODING_DATA_DIR`、checkpoint/store SQLite、随机可用端口启动后端。
- 加 health check、ready timeout、日志收集、启动失败诊断、进程树关闭和异常清理。
- 先用 API 创建 session/提交任务/读取流式事件和最终状态；再用浏览器 E2E 覆盖真实前端。
- 验证需求消息、计划状态、确认/拒绝、运行状态、Agent 输出、事件、数据库行与文件改动；不只检查 HTTP 200。
- 每次 run 记录服务版本、配置名（不含秘密）、绑定端口、数据库路径、请求/响应摘要和日志 artifact。

**验收：** API 端到端通过且无共享端口/DB；至少覆盖一条前端浏览器路径和一条失败清理路径。测试结束无残留服务进程。

### 阶段 5：数据库和沙箱专项

- SQLite：每个 run/case 使用 `cases/<case_id>/db/` 下独立文件，检查迁移、重启恢复、跨 case/run 无数据泄漏。
- PostgreSQL：仅连接一次性容器/临时实例或专门测试 DSN；启动前校验 DB 名/主机与显式测试标识，禁止连接开发库；测试迁移、事务回滚、重连和审计记录。
- OpenSandbox：真实服务不可用时测试标记为 `not_run`，不能用 FakeExecutor 结果冒充；对真实 sandbox 检查隔离、凭证/数据库排除、路径越界拒绝、网络/命令限制、超时、上传大小、清理与生命周期。

**验收：** 每种数据库独立数据目录/实例；sandbox 的通过证据来自真实隔离执行器；失败时资源清理有日志证据。

### 阶段 6：可视化报告与公开证据

- 提供自包含、响应式、可打印的 HTML 报告：总体通过数、硬门槛结果、各指标及分母、版本/模型信息、耗时与 Token、按案例展开、改动文件、失败原因及相对路径 artifact。
- 多轮比较显示同一案例在不同 Agent SHA 上的通过变化、测试和检索变化、Token/耗时；版本/模型/题目不一致时醒目标注不可直接比较。
- 不显示机器绝对路径、秘密、完整环境变量、数据库文件、内部密钥或未经审查的 prompt 内容。
- 生成经过 allowlist 和脱敏的公共报告 bundle，并更新 `test-coding-eval` README 示例；coding-agent README 只展示简明截图/数字和报告链接，标明 Agent SHA、target SHA、模型、运行次数和范围。
- 先本地渲染检查 HTML 外观、中文、窄屏、长报错和无 JS 场景；报告结果不靠颜色单独表达。

**验收：** 可在无网络环境打开 HTML；JSON 可由脚本读取；每个指标点回原始证据；公共 bundle 通过秘密与本地路径扫描及人工检查。

## 运行策略和成本控制

- 单元测试和故障注入默认离线；不调用模型。
- DeepSeek 真实案例使用用户已指定的项目 `.env`，通过只读环境文件注入子进程；从不输出或复制密钥。
- 真实模型 suite 分批运行：先 1 道 canary 校验流程，再全量 5～10 题；超时/限制/Token 用量进入报告。用户此前允许使用该 DeepSeek 配置进行评测，本轮在该既定授权内执行。
- 现有历史三题报告记录了 Agent SHA `710862e…` 和 DeepSeek，但没有 `agent_source_root`、完整运行 manifest 或 adapter hash；作为历史结果保留，完成运行快照与 manifest 后重新生成可验证的三题基线报告。
- 不将 fake/simulated run 标为真实 Agent 结果。失败项保留原始失败，不挑选性删除。

## 已知起点与当前进度

- 框架开发基线：`440e70da350820d5988d2c7361d22348ddf40909`。
- 被测 Agent 固定基线：`710862e51e382762de1b3cccf63fdf965d369f4e`。
- 独立 Taskboard 历史目标基线：`d19ddda0ac269adf1e68d7d2840968527b313bc4`。
- 旧真实 DeepSeek 报告：3 道 Taskboard 题通过；原始报告在 `docs/agent-eval/evidence/first-suite-combined/`。该报告 Agent SHA 是 `710862e…`，未记录完整 adapter/runtime provenance，只能作为历史记录。
- 本轮真实 5 题编码 suite 的 run `20260926T125344Z-d11cef80`，报告位于 `A:\gyx_cv\coding-agent-eval-runs\runs\20260926T125344Z-d11cef80\report.json`：1/5 通过，5/5 回归通过，目标/隐藏验收/补丁各 1/5，检索命中 1.0，3,511,041 Token，279,942 ms。真实 Agent 失败是结果本身，不能靠改 oracle 掩盖。
- 本轮 API 应用 E2E 的成功 run `20260926T130348Z-fdae224c`：固定 Agent `710862e` 通过 HTTP/SSE 创建线程、计划审批和恢复，独立 SQLite 检查通过；补丁、target/regression/oracle 全过，675,853 Token，69,080 ms。此前 `20260926T130005Z-9dbe3477` 因 40 次工具上限失败，且暴露 SQLite 懒初始化检查时机错误；修复后将隔离检查移到请求完成后，并把题目上限调为 64。
- Runner 有固定 Agent runtime 快照、独立 oracle/答题副本/SQLite，source/case 隔离、测试失败/超时诊断、SHA/manifest、Token/tool/retrieval 证据测试。当前全量单元测试通过 `105 passed, 1 skipped`，另有 1 条上游弃用警告。
- 五道固定 Taskboard 题可重复运行，新增组合筛选题会注入一次 CodeGraph 超时；本轮恢复率为 0，明确证明旧 Agent 未能恢复。状态筛选题能修改实现和测试并通过隐藏验收；其它 4 题的实际失败保留在原始日志。
- 中文报告支持自包含 HTML、Markdown、脱敏公共导出和多轮对比。编码 suite、API E2E、浏览器 E2E、计划拒绝、PostgreSQL 和 OpenSandbox 的 HTML/JSON/Markdown 证据已导出；公开证据共扫描 89 个文件，未发现本地绝对路径或 API Token/Bearer 格式。新增报告复用已做过视觉核验的自包含模板；本轮无法通过桌面浏览器接口截图核验新报告，已记录为视觉 QA 限制。

实施时每完成一个阶段，在下表记录代码、测试、真实/模拟运行证据和剩余限制。若验收不满足，修复后再进入下一阶段。

| 阶段 | 状态 | 验收证据 / 剩余工作 |
| --- | --- | --- |
| 0 基线 | 完成 | 框架源 `440e70d`、被测 Agent `710862e`、题库远端 main `d650477` 和每题完整 SHA 都已写入 manifest；外部 `.env` 未复制到 run |
| 1 Runner 可靠性 | 完成（离线契约） | 独立副本/DB、源码不变、失败/超时诊断、patch/oracle、usage/events 与版本重现测试；全量 `tests/unit` 为 105 passed、1 skipped |
| 2 编码题 | 完成首批评测，结果未达标 | 5 道固定独立题全部真实运行；`710862e` 通过 1/5。可继续扩充到 8 题及增加重复抽样，不影响这批首测已完成 |
| 3 交互能力 | 完成首轮覆盖，部分能力成绩未通过 | 计划/审批恢复、真实计划拒绝、计划结构和必需文件名评分、补测试文件行为均有案例；注入 CodeGraph 超时后的真实 Agent 恢复率为 0.0，这是 Agent 的实测未通过项，不是 Runner 故障。Agent 输出准确性由每题的人工复核表检查 |
| 4 应用 E2E | API 与一条浏览器路径完成 | `run_eval_app.py` 启动固定版 FastAPI；API/SSE 路径和 Chromium/Vue 前端路径都完成真实任务、计划审批、Agent 恢复、SQLite 隔离和补丁验收。浏览器 run `20260926T134606Z-6666c872` 通过；单元测试注入页面启动失败，验证 Vite 子进程由 `finally` 回收 |
| 5 DB/沙箱 | PostgreSQL 持久层专项通过；OpenSandbox 隔离探针通过；完整 Agent-in-sandbox 和网络边界未验证 | PostgreSQL 最新 run `20260927T030238Z-a711c4ca` 使用 `postgres:18` 一次性本机容器，业务 Store/LangGraph Store/Checkpointer、幂等 schema、事务回滚、重连与审计集成测试通过且容器已销毁。OpenSandbox run `20260927T024816Z-37ead2d0` 真实执行安全文件上传、Git 补丁、target/regression/oracle、路径穿越拒绝、命令超时和两个 sandbox 的清理；假 `.env`/SQLite 未上传。尚未在沙箱中启动完整 coding-agent、未验证网络边界/上传大小限制，也未在 PostgreSQL 部署上跑全应用 E2E |
| 6 可视化/公开证据 | 报告与对比页已导出；新报告复用模板但未做桌面截图 QA | 中文自包含 HTML/MD、公共脱敏包和多 run 比较 CLI 已有；5 题、API、浏览器、计划拒绝、PostgreSQL、OpenSandbox 结果均已导出。每道 Agent 案例附带待填写的人工复核表，对照 Agent 答复、补丁和测试日志；89 个公开证据文件扫描未发现本地绝对路径或 API Token/Bearer 格式。旧报告已有视觉检查，新报告通过桌面浏览器截图复核受当前 UI 自动化接口限制 |

### 本轮新增的浏览器验证记录

- 浏览器真实 run `20260926T134606Z-6666c872`：Agent `710862e51e382762de1b3cccf63fdf965d369f4e`，目标提交 `d19ddda0ac269adf1e68d7d2840968527b313bc4`。浏览器页面提交任务并批准计划，Agent 随后修改 `taskboard/tasks.py` 与 `tests/test_filter_by_status.py`；target、regression、hidden oracle、patch、CodeGraph retrieval、独立 SQLite 和前端完成状态全通过。Token 1,813,740，Agent 时间 98,709 ms。
- 首两次浏览器尝试未计入成功结果：一次发现页面状态定位不唯一，另一次暴露审批后再次读取已消失的 pending 元素会无限等待；修复定位和证据采集后以上述新 run 完成验证。错误 run 仍保留在外部运行目录中，不作为成绩展示。
- PostgreSQL 初轮专项：run `20260927T024348Z-002637c2` 在自动生成的用户/库与随机本地端口上运行 `tests/unit/test_persistence_factory.py -m integration`；业务 Store、LangGraph Store 和 PostgreSQL Checkpointer 读写通过，并验证幂等 schema 初始化、事务回滚、连接池关闭后重连、审计事件；`postgres:18` 容器自动删除。测试进程通过，不调用模型，耗时约 6.7 秒。最新复跑记录如下方 `20260927T030238Z-a711c4ca`。报告：[HTML](agent-eval/evidence/postgres-persistence-e2e/report.html) / [JSON](agent-eval/evidence/postgres-persistence-e2e/report.json)。
- 计划拒绝 API E2E：run `20260927T031558Z-e8bd2435`；固定 Agent `710862e51e382762de1b3cccf63fdf965d369f4e`，目标仓库 `test-coding-eval@d19ddda0ac269adf1e68d7d2840968527b313bc4`。真实 DeepSeek Agent 输出包含需求理解、涉及模块、实现文件 `taskboard/tasks.py`、测试文件 `test_count_by_status.py` 和验证命令；Runner 观察到 pending 计划并提交拒绝，最终计划状态为 `rejected`，答题副本前后干净，target/regression 通过，0 源码改动，评分 1/1 通过。共 163,761 Provider Token，Agent 时间 33.2 秒。公开报告带有人工复核表：[HTML](agent-eval/evidence/application-plan-rejection-e2e/report.html) / [JSON](agent-eval/evidence/application-plan-rejection-e2e/report.json)。
- PostgreSQL 复跑：run `20260927T030238Z-a711c4ca`；一次性 `postgres:18` 容器中的持久层集成测试通过，清理通过，耗时 6.49 秒；未调用模型。最新公开证据覆盖此 run：[HTML](agent-eval/evidence/postgres-persistence-e2e/report.html) / [JSON](agent-eval/evidence/postgres-persistence-e2e/report.json)。
- OpenSandbox 隔离冒烟：run `20260927T024816Z-37ead2d0` 通过 localhost OpenSandbox Server 创建真实 sandbox，以包含 Git 的 Alpine 镜像运行微型 fixture；只上传 `baseline.txt`，假 `.env` 和 `store.sqlite` 被过滤。生成的 `result.txt` patch 可读，目标测试/回归测试/隐藏验收全通过；安全探针验证路径穿越拒绝、1 秒命令超时和两个 sandbox 均清理。该题不启动模型或真实 coding-agent，因此不能计入 Agent 编码通过率。报告：[HTML](agent-eval/evidence/opensandbox-isolation-smoke/report.html) / [JSON](agent-eval/evidence/opensandbox-isolation-smoke/report.json)。
- 最后边界：计划拒绝已完成真实 API 评测并导出证据；通用中断后恢复仍缺独立案例。OpenSandbox 尚未用真实 coding-agent 命令完成独立编码题，也未验证网络边界和上传大小限制；PostgreSQL 只完成存储适配器组件级验证，没有全应用 E2E。PostgreSQL 使用一次性本地容器，OpenSandbox 容器在完成后销毁，均未连接日常数据库。

## 最终交付清单

- 实施计划与逐阶段完成记录。
- 稳定 runner、runtime 快照、适配器、评分器、report schema、CLI 和文档。
- 离线测试与真实评测报告；每份报告写明哪些项是模拟、哪些使用真实模型或服务。
- 5～10 道固定独立编码题与隐藏验收，支持从完整 SHA 重跑。
- 交互、应用 E2E、DB、sandbox 专项结果或明确列出无法实际启动的外部依赖和验证缺口。
- 自包含可视化 HTML 和脱敏公开证据包。
- 代码保留在开发分支中向用户完整汇报；未经用户确认，不创建 PR。
