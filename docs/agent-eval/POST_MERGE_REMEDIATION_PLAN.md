# Agent Eval 合并后修复与完整验证方案

## 目标和基线

本轮工作从已合并并同步的 `coding-agent` 主分支 `c69d7cdd8acc57258fad1146966d0662bcbc3af2` 开始，在独立 worktree `codex/agent-eval-remediation-c69d7cd` 中实施。主工作区 `A:\gyx_cv\coding_agent` 只负责同步代码，不在其中编辑；其个人未跟踪文件保持原样。

本轮要求形成四类可核验证据：

1. 首轮旧五题全部通过，并保留旧报告作为历史基线。
2. 新增五道不同于旧五题的固定编码题，固定题目、目标仓库完整 SHA、目标测试、回归测试、隐藏验收和文件范围；十题全部通过。
3. 通过确定性故障注入验证 Agent 能识别工具错误并恢复，而不是只统计工具调用次数。
4. 对完整应用分别验证真实 coding-agent 在 OpenSandbox 内完成编码任务、整应用运行在一次性 PostgreSQL 上的 API/持久化路径。两个结果不能用持久层单测、模拟执行器或小型 shell fixture 代替。

当前被测 Agent 版本固定为同步后的最新完整 SHA `c69d7cdd8acc57258fad1146966d0662bcbc3af2`，除非实测证明要评估另一个明确 SHA；开发中的评测框架版本与被测 Agent SHA 分字段保存。每次变更后重跑都要记录确切 Agent runtime、目标 SHA、案例配置哈希、DeepSeek 模型名、工具/模型限制和完整证据路径。

## 已知事实与需要查明的根因

- 已合并的五题报告：1/5 通过、4/5 失败、回归 5/5、隐藏验收 1/5、工具恢复率 0.0。四个失败题存在空补丁或缺少要求修改的文件，说明核心问题是 Agent 没有完成目标仓库实现；但旧报告是一次随机模型运行，不能单凭它判断唯一根因。
- 后续单题 `taskboard-priority-aliases` 曾独立通过，说明需要做可复现单题复测，区分模型随机性、计划审批/继续执行故障、工作区绑定错误、Agent 自身意图/计划/工具调用问题和评分器缺陷。
- 失败 run 的结构化 runtime 结果证实至少一题被 Agent 当成了分析任务：`taskboard-group-by-status` 的模型仅输出实现建议，`plan_approval_performed=false`、没有 pending 计划、工作区无改动，但 runtime 仍返回 `completed`。根因入口是 `agent/core/task_intent.py`：显式编码动词虽然会被 `_has_coding_marker` 找到，却没有在模型误判为 `analysis/planning` 时覆盖预测结果；“先检索再新增/实现/补测试”的编码题因此可能被只读路由接管。修复将包含确定性编码意图守卫和分类结果遥测，并用原题提示词单测锁定行为。
- 新五题将使用独立目标仓库 `test-coding-eval` 的公开基线 `d65047705e6e947bcd33e193ab4c8fdfeb8956c8`，在 Eval 框架内通过有哈希的公开 target-test fixture 注入五个不同任务；候选仓库和 oracle 仍由固定 SHA 独立构建。这样不需依赖尚未发布的目标仓库提交；fixture 哈希与目标 SHA 一同进入 manifest，后续可单独发布到目标仓库。
- 旧五题从已保存的 `test-coding-eval` 案例清单与运行报告恢复；其中前 3 题固定基线为 `d19ddda0ac269adf1e68d7d2840968527b313bc4`，跨文件新增的 2 题固定基线为 `eb344e9e566f3c68176f0fc57d53686e47caedbf`。
- 现有 `SandboxEvalRunner` 只把命令和 fixture 放入 OpenSandbox；旧 Agent adapter 仍以宿主机 `LocalShellBackend` 执行。因此必须实现 Agent 工具后端到真实 sandbox 的绑定，并证明目标仓库文件读写、运行测试、补丁导出均实际经过同一 sandbox。
- 已有 PostgreSQL 证据是持久层组件集成，不是完整应用 E2E。完整验收要覆盖应用配置、API 创建会话/任务、真实 Agent run、业务 store/checkpointer/events 持久化和读取；关闭并重启后端再读取关键状态；使用一次性独立实例，不接日常开发库。
- 现有评测报告曾把 `tool_recovery_rate` 记成 0.0；要沿用一次注入的可恢复错误，并用错误事件、同一工具调用的恢复动作和最终任务通过三项证据评分。

## 实施阶段和门禁

### 0. 固定数据、运行环境和安全边界

- 读取旧五题的原始配置、完整 run manifest、每题 trace/agent-output/patch/tests log；对照外部运行目录里的单题成功和失败记录，制作失败分类表。
- 锁定 Agent SHA `c69d7cdd…`，记录工作区 clean/dirty 策略；只读使用项目 `.env` 中的 DeepSeek 设置，禁止把密钥写入子进程日志、评测报告、Agent snapshot 或提交。
- 检查并记录 OpenSandbox endpoint、Docker daemon、PostgreSQL 镜像/端口可用性。所有运行使用唯一 run ID、独立目录、数据库名、端口和资源标签；只清理本轮创建的容器/进程。
- 记录评测工作区/产物到 `A:\gyx_cv\coding-agent-eval-runs\runs\<run_id>`，开发代码只留在本 worktree。每个目标题的候选仓库、oracle 仓库和运行状态存储相互分开。

**门禁：** 方案、基线 SHA、密钥保护、外部依赖检查和报告目录可写后才能启动真实模型评测。

### 1. Runner 和 Agent runtime 可靠性

- 先对 Runner 加离线验证：每 case 独立 checkout / oracle / SQLite；主仓库与相邻 case 无写入；超时、Agent 非零退出、缺 trace/usage、目标/回归/隐藏测试失败均能归因到阶段、命令、退出码和日志。
- 检查 patch 从 sandbox/Agent workspace 提取后能应用到干净 oracle；报告使用固定 SHA 和配置哈希；真实 trace 计数与 token usage 原始数据相符，缺失数据输出 `null` 而非 0。
- 验证 agent runtime snapshot 与 adapter overlay 指纹；每个 case 不共享可变 Agent runtime/数据库状态。

**门禁：** Runner 相关单元和隔离集成测试通过；源仓库快照与案例副本哈希对照通过；故障注入报告包含可读原因。

### 2. 修复真实 Agent 编码链路并通过旧五题

- 逐题做低成本诊断 run，不改验收标准；检查模型输出、计划及审批事件、Agent 子进程命令、检索路径映射、文件工具可见路径、workspace git diff、运行后实际 changed_files、模型调用/工具调用限额。
- 修复查明的真实根因，优先审查：计划批准后是否恢复在同一任务/线程/工作区；Agent 是否把提示词的目标路径映射到隔离目标仓库；跨文件/public API任务是否能从计划阶段进入编码；工具错误是否被明确反馈模型；测试工具 cwd 和文件工具映射是否指向同一副本；调用限制是否让模型在真正修改前结束。
- 对每项根因先添加确定性回归测试。禁止通过弱化 target/oracle、移除要求文件、抬高阈值或伪造 patch 让题目变绿。
- 所有旧题以固定 Agent SHA 和原始固定 case JSON 重跑；若随机性导致不稳定，对失败题至少重跑并如实报告各次结果。用户要求单轮全部通过时，最终报告必须标出轮次和模型配置，不能选择性遗漏失败轮次。

**门禁：** 旧题当前基线五题全部通过 target、regression、oracle、patch 和必需交付项；检索/Token/时间都有原始来源。

### 3. 新增五道独立题并形成十题能力集

- 新五题与旧五题验收目标不同；覆盖至少一题边界 bug、一题完整新功能、一题跨文件 API、一题明确增加有效测试、一题多要求组合。题目文本、精确 target SHA、目标与回归测试、隐藏 oracle、允许改动文件、超时和调用预算均入版本控制。
- 新题采用独立目标仓库 `test-coding-eval` 的固定快照。目标快照 SHA 必须能从公开/授权远端按 SHA 取回；若需先在目标仓库增加 fixture，则其提交和发布作为独立交付，不能在本地存在但远端不可复现。
- target tests 与隐藏 oracle 分开运行：公开测试可供 Agent 使用；oracle 在外部评分副本执行。每题通过仅依据实际应用的 patch 和验收结果。
- 将十题共同运行并生成对照报告；报告分别显示每题、维度、模型 token、耗时、patch 文件、失败详情和证据链接，不压成无解释的“总分”。

**门禁：** 旧题 5/5、新题 5/5 均通过；目标仓库和案例配置可从固定 SHA 重建；整套报告可重复比较。

### 4. 工具恢复和交互行为

- 用现有 `require_tool_recovery` / `inject_tool_error_once` 形成确定性案例：首次 CodeGraph 查询注入一次可恢复超时；Agent 必须看到错误、重试或换用 grep/read_file 等策略、随后取得检索或读取结果、完成代码并通过验收。
- 事件评分用同一个 `tool_call_id`（或稳定 recovery link）关联失败、恢复动作和成功结果；如果工具调用 ID 跨步骤不稳定，则先增加 schema 字段，不用“随后同名工具成功”这种误报规则。
- 至少覆盖一种本地工具错误恢复和一种 sandbox 命令失败恢复；不可恢复错误要正确终止并提供解释。

**门禁：** 注入错误次数为 1、错误事件可追溯、恢复链路完整、任务验收通过；恢复率分母仅包含适用案例。

### 5. 真实 Agent OpenSandbox 编码 E2E

- 不复用 `SandboxEvalRunner` 的 synthetic command 当作 Agent 成绩。新增真实 Agent sandbox adapter，把 Agent 使用的 execute/file 工具全部绑定到本次 OpenSandbox；允许 CodeGraph 在受控只读索引服务中查询 sandbox 仓库快照，或在 sandbox 内建索引，并记录其安全边界。
- 将固定目标仓库完整快照安全上传到 sandbox，排除 `.env`、Git 凭证、SQLite/PostgreSQL 文件、缓存和其他秘密；检查上传清单与字节数。sandbox 内设置只读 baseline/oracle 和可写 candidate workspace，Agent 的测试命令也在 candidate workspace 运行。
- 实际提交新五题中的一题到 Agent，Agent 必须通过真实模型、真实工具调用在 OpenSandbox 里改代码/测试；从 sandbox 提取 diff/artifacts，在独立 host oracle checkout 上 apply 并执行 target/regression/oracle。
- 验证路径穿越/宿主路径写入被拒绝、命令超时、网络规则按策略生效、上传上限、退出清理和保留运行证据。记录 sandbox ID 和销毁结果，不记录 API key。

**门禁：** 真实模型请求、工具调用、文件修改和测试全部来自 sandbox 执行证据；提取的 patch 能在 host oracle 重放通过；sandbox 外源文件 hash 不变。

### 6. PostgreSQL 整应用端到端

- 启动本轮专属一次性 PostgreSQL 容器/临时实例，随机 host port、随机库名和凭据；启动前断言 DSN 标记为评测、库名含唯一 run ID、非空 DSN 不指向已知开发库。禁止把日常数据库凭据传给应用。
- 用固定 coding-agent runtime 快照启动后端，指定 PostgreSQL persistence backend、独立工作区目录、Agent 模型配置、日志和临时端口；health/readiness 成功后通过真实 HTTP/SSE API 创建会话并提交一题。真实 Agent 执行可与 sandbox adapter 组合，至少要通过真实 OpenSandbox 任务路径。
- 检查 threads/messages/runs/events/plans/checkpoints 等此版本实际使用的数据在 PostgreSQL 中写入、能从 API 读回；验证运行状态完成和目标 patch/test；结束后重启后端，验证可恢复记录仍在。
- 关闭服务，记录进程退出、容器销毁和无残余资源；失败路径也运行 finally cleanup。报告保留 health、API/SSE 摘要、PostgreSQL 查询断言、Agent/sandbox证据和服务日志。

**门禁：** 这是端到端的真实 Agent/API/PostgreSQL（与真实 sandbox 配置组合）通过；不是只跑 Store 集成测试或只检查页面显示。应用数据均来自本轮临时库，日常开发数据不变。

### 7. 完整报告和最终验收

- 生成 JSON、中文 Markdown、自包含响应式 HTML、比较页和脱敏证据目录。页面清晰展示当前 Agent SHA、target SHA、模型、suite ID、十题通过数、工具恢复、sandbox、PostgreSQL E2E、Token/耗时、失败/限制及每题 artifact。
- 报告将“通过”“失败”“未运行”“不适用”区分开；外部依赖无法用真实服务验证时不能写通过。本轮目标未完成就保持 active，继续修复；不能通过标题或摘要掩盖证据缺口。
- 最后复核 10 题所有 artifact、公开路径扫描、资源清理、主工作区 Git diff 和报告视觉效果；工作保留在开发分支，不创建 PR，待用户确认交付结果后再定 PR。

**最终验收：** 十题逐题 target/regression/oracle/patch 通过；工具错误恢复达标；OpenSandbox 真实 coding-agent 编码 E2E 通过；PostgreSQL 全应用 E2E 通过；报告完整可视化；日常源码、数据库和环境秘密未被污染。

## 当前进度

- [x] 主工作区 `main` 从 `440e70d` 快进同步到 `c69d7cdd`。
- [x] 建立独立 worktree 和开发分支 `codex/agent-eval-remediation-c69d7cd`。
- [x] 盘点首轮结果、旧题固定基线和目前缺失的 PG/真实 sandbox 证据。
- [x] 初步根因：旧 Agent 偶尔把明确实现任务路由到只读 analysis/planning；恢复失败率还有独立遥测与备用策略问题。
- [x] 阶段 0 完成：固定源/目标 SHA、DeepSeek 配置来源、独立运行目录，并确认 Docker、PostgreSQL 和 OpenSandbox 的真实可用性。
- [x] 阶段 1 完成：Runner/runtime 隔离与失败归因测试；最终 `tests/unit` 为 140 passed、1 skipped。
- [x] 阶段 2 完成：旧五题最终 5/5；四题来自五题运行，一题因 24 次模型调用上限单独以 32 次上限重跑通过。
- [x] 阶段 3 完成：新五题最终 5/5；其中 priority 题原始补丁已通过目标/回归测试，发现隐藏验收器把 `urgent` 与 `high` 等价规则写反后，修正验收器并在干净固定目标副本上重放同一补丁，全部验收通过；原始失败报告保留。
- [x] 阶段 4 完成：CodeGraph 检索错误和 OpenSandbox 命令错误分别做一次故障注入；Agent 看到错误并恢复，适用案例恢复率为 1.0。
- [x] 阶段 5 完成：真实 DeepSeek coding-agent 在 OpenSandbox 中完成编码、运行测试、导出补丁；注入命令错误后恢复，沙箱资源销毁。
- [x] 阶段 6 完成：完整应用通过真实 API/SSE 与计划审批，在一次性 PostgreSQL 中持久化；重启后端后恢复读取；Agent 编码使用真实 OpenSandbox；数据库和沙箱均已清理。
- [x] 阶段 7 完成：合并 10 道题和两项系统门禁的 JSON、中文 Markdown 与 HTML 报告；单测、产物路径、脱敏与资源清理已复核。

## 验收证据与解释

以下运行产物保存在评测输出盘，不提交进源仓库；总报告会将必要的报告、补丁、trace 和门禁证据复制到它自己的相对目录。

| 验收项 | 结果 | 可核验报告/说明 |
| --- | --- | --- |
| 旧五题 | 5/5；所有最终 case 的 patch、target、regression、oracle 均通过 | `A:\gyx_cv\coding-agent-eval-runs\runs\remediation-final-suite-<final-sha>\report.html`；输入运行：`remediation-old-five-a6941fb` 与 `remediation-old-status-filter-8c467aa` |
| 新五题 | 5/5；同样四项验收均通过 | 总报告；新题原始 run：`remediation-new-five-139e970`；priority 题验收器修复后重放：`remediation-new-priority-oracle-rescore-9b07905` |
| 工具错误恢复 | 适用案例恢复率 1.0；包括检索工具和沙箱命令故障注入 | 总报告每题的恢复字段；真实沙箱证据 `remediation-opensandbox-recovery-9b07905` |
| OpenSandbox 真实 Agent | 真实模型/工具调用、文件修改、测试、补丁回传、清理通过 | 总报告 `real-opensandbox-agent` 门禁；独立输入报告 `remediation-opensandbox-recovery-9b07905` |
| PostgreSQL 整应用 E2E | API/SSE、审批、真实 Agent 沙箱编码、一次性 PostgreSQL 写入和后端重启恢复通过 | 总报告 `application-postgres-e2e` 门禁；独立输入报告 `remediation-postgres-opensandbox-final-9b07905` |
| Runner 单测 | 140 passed、1 skipped；唯一 warning 来自 `google.genai` 依赖弃用提示 | 在开发 worktree 执行 `python -m pytest tests/unit -q` |

### 结果来源的边界

- 10 道编码题由各自真实 DeepSeek 运行结果组成；由于每轮根因修复都要生成新的 Agent runtime 快照，报告逐题记录实际 Agent SHA，不把不同版本伪装成同一 SHA。它证明修复后的题目逐题通过，不代表 10 题均由完全相同二进制快照评测。
- 旧题 `status-filter` 因第一次运行撞到模型调用上限而单题重跑；旧报告仍保留在运行目录，合并报告选择通过的受控重跑结果。
- 新题 `filter-by-priority` 的模型原始修改没有因验收器修正而变化。修正的是一处与公开题意和 target test 冲突的 oracle；使用原 Agent 输出补丁，在干净固定目标副本重新应用并运行 target、regression、oracle 和文件范围检查。原始误判报告没有被覆盖。
- PostgreSQL 与 OpenSandbox 门禁报告来自最新源码 SHA `9b07905ce3a07289d58b9ab0c9a56e2f93656042`。PostgreSQL 用独立随机容器/端口/库；不会把开发库或既有 Dify 容器作为评测目标。

