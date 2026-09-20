# CODING

> 面向大型代码仓库的本地优先 AI Coding Agent：支持仓库感知检索、受控执行、可恢复任务、可复现评测与交付闭环。

CODING 将“理解仓库 → 制定计划 → 修改代码 → 执行验证 → 生成补丁 → 交付审计”组织为一条可追踪的 Agent 工作流。当前版本重点补齐了持久化、检索、运行隔离、Worker 恢复和 Agent Eval 基础设施，适合本地开发、团队协作和面试演示。

## 当前能力

| 能力 | 当前实现 | 解决的业务问题 |
| --- | --- | --- |
| PostgreSQL 持久化 | Checkpoint、LangGraph Store、业务 Store 可切换 PostgreSQL | 多用户、多 Worker、重启恢复和审计 |
| SQLite → PostgreSQL | 迁移脚本、幂等导入、报告和事件审计 | 从单机原型平滑升级到共享数据库 |
| CodeGraph + grep | CodeGraph 结构化检索与 grep 文本检索并行融合 | 大型仓库中快速定位符号、调用链和配置引用 |
| Agent Eval | fake、real、sandbox 三种执行模式，JSON 报告和聚合汇总 | 用补丁、测试、检索、恢复、Token、延迟指标驱动迭代 |
| OpenSandbox | 健康检查、上传仓库、受控命令执行和结果回收 | 在隔离环境中运行测试、构建和评测任务 |
| Worker 租约 | acquire、renew、release、过期恢复和审计事件 | Worker 崩溃或重启后恢复未完成任务 |
| Git 交付闭环 | 分支、补丁、测试和 Gitee 交付信息可追踪 | 让 Agent 产物进入可审查的研发流程 |
| Issue Writer Skill | 从代码、检索结果、日志和截图生成可复现 Issue 草稿 | 将问题沉淀为可排重、可验证的开源 Issue |

## 架构概览

```mermaid
flowchart LR
    U[用户请求] --> O[Agent Orchestrator]
    O --> R[CodeGraph + grep 混合检索]
    O --> P[Plan / Patch]
    P --> X[Runtime 受控执行]
    X --> S{执行后端}
    S --> L[本地进程]
    S --> B[OpenSandbox]
    O --> D[(PostgreSQL)]
    D --> C[Checkpoint]
    D --> T[Store / 业务状态]
    X --> A[审计事件]
    A --> E[Agent Eval 报告]
    P --> G[Git 分支 / 补丁 / 交付]
```

代码入口主要位于：

| 目录 | 作用 |
| --- | --- |
| `agent/core/` | Agent 状态、持久化、检索、运行时、租约和审计 |
| `agent/evals/` | Eval 数据模型、运行器、聚合报告和沙箱适配 |
| `agent/integrations/` | OpenSandbox、模型和外部服务适配 |
| `scripts/` | 迁移、评测、恢复、健康检查和验证脚本 |
| `evals/` | 可复现评测样例、断言和数据说明 |
| `.agents/skills/` | 项目专用 Agent Skill，包括 Issue Writer |
| `docs/` | 架构、部署、运行时、Eval 和面试说明 |

## 快速开始

### 1. 安装依赖

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

需要使用 OpenSandbox 适配器时安装可选依赖：

```powershell
pip install -e ".[sandbox]"
```

### 2. 配置环境变量

复制 `.env.example` 为 `.env`，至少配置模型和仓库信息。使用 PostgreSQL 时，将 DSN 指向自己的业务数据库，例如：

```dotenv
POSTGRES_DSN=postgresql://user:password@127.0.0.1:5432/coding_agent_db
PERSISTENCE_BACKEND=postgres
```

PostgreSQL 只需准备 `coding_agent_db` 数据库；应用启动时会按当前后端初始化所需表。没有 PostgreSQL 时可不配置 DSN，程序会回退到本地 SQLite，适合离线开发和单元测试。

### 3. 启动应用

```powershell
python -m agent
```

启动前可以检查环境：

```powershell
python scripts/check_env.py
```

## PostgreSQL 持久化与迁移

### 为什么使用 PostgreSQL

SQLite 适合单机原型和快速测试，但多用户、多 Worker 同时写入、任务租约、审计查询和重启恢复需要共享数据库。PostgreSQL 后端将三类状态统一纳入可配置的持久化层：

- LangGraph checkpoint：保存线程、节点状态和中断恢复点。
- LangGraph store：保存跨会话的长期 Agent 状态。
- Business store：保存任务、运行、租约和审计事件。

配置 `POSTGRES_DSN` 后，`agent/core/persistence.py` 会构造 PostgreSQL 实现；保留 SQLite 适配器用于本地回退和迁移前验证。密码只放在 `.env`，不要提交到仓库。

### SQLite 迁移

迁移前先备份本地数据库，再执行：

```powershell
python scripts/migrate_sqlite_to_postgres.py `
  --dsn "$env:POSTGRES_DSN" `
  --report data/migration-report.json
```

脚本会迁移业务状态、checkpoint 和 store 数据，输出行数、跳过项、错误和审计信息。重复执行时应保持幂等；迁移完成后重新运行应用并检查 PostgreSQL 中的任务、线程和审计记录。

## CodeGraph + grep 混合检索

`agent/core/hybrid_search.py` 对每次代码问题同时执行：

1. CodeGraph：优先返回符号定义、引用关系和调用路径，适合回答“谁调用了它”和“修改影响什么”。
2. grep：补充字符串、配置键、错误信息、模板和未被图索引的文件。
3. 融合排序：按路径和行号去重，结合结构化结果、文本命中和上下文预算输出统一结果。
4. 可观测回退：记录 CodeGraph 不可用、超时或无命中时的 grep 回退原因。

仓库根目录存在 `.codegraph/` 时，优先使用 CodeGraph；没有索引时仍可使用 grep，保证新仓库和增量文件可检索。

## Agent Eval

Eval 以一个案例目录描述用户任务、目标补丁、目标测试和回归测试，运行器记录每次工具调用和最终结果，生成可复现 JSON 报告。当前指标包括：

- 补丁是否应用成功，以及变更文件和差异摘要。
- 目标测试、回归测试是否通过。
- CodeGraph、grep 和混合检索的命中情况。
- 工具失败后的重试、恢复和最终状态。
- 输入输出 Token、工具调用数和端到端延迟。
- 运行环境、模型配置、Git revision 和报告 schema 版本。

### 三种执行模式

```powershell
# 不依赖外部模型和沙箱的确定性冒烟评测
python scripts/run_eval.py --mode fake --case-dir evals/smoke

# 使用真实 Agent 配置运行
python scripts/run_eval.py --mode real --case-dir evals/smoke

# 在 OpenSandbox 中运行
python scripts/run_eval.py --mode sandbox --case-dir evals/smoke
```

报告默认写入 `eval_runs/`，可以提交到 CI 或作为 Prompt、检索策略和运行策略迭代的比较基线。案例建议至少包含：

```text
evals/smoke/cases/<case-id>/task.md
evals/smoke/cases/<case-id>/expected.patch
evals/smoke/cases/<case-id>/target-tests.txt
evals/smoke/cases/<case-id>/regression-tests.txt
```

更多案例格式和指标说明见 [`evals/README.md`](evals/README.md)。

## OpenSandbox 轻量隔离执行

OpenSandbox 是可选执行后端，不是应用启动的硬依赖。配置示例：

```dotenv
OPEN_SANDBOX_DOMAIN=http://127.0.0.1:8080
OPEN_SANDBOX_API_KEY=
OPEN_SANDBOX_IMAGE=python:3.11-slim
OPEN_SANDBOX_TIMEOUT_SECONDS=300
OPEN_SANDBOX_KEEP=false
```

启动 OpenSandbox Server 后验证连接：

```powershell
python scripts/verify_opensandbox.py --domain "$env:OPEN_SANDBOX_DOMAIN"
```

健康检查成功只代表服务端可达，不代表节点能够拉取指定镜像。若创建沙箱时出现镜像仓库 DNS、网络或权限错误，应先在 OpenSandbox 所在节点验证镜像拉取，再运行 sandbox Eval。生产环境应配置 API Key、资源上限、命令超时和允许的工作目录，并避免把真实密钥上传到沙箱。

## 多 Worker、租约与重启恢复

业务任务通过租约避免多个 Worker 重复执行：

```text
acquire → renew heartbeat → execute → release
                     └───── worker 崩溃后由 recover 接管过期任务
```

`WorkerLeaseManager` 会记录租约获取、续租、释放、恢复和失败事件。Worker 重启后运行：

```powershell
python scripts/recover_stale_runs.py
```

恢复动作必须结合幂等任务 ID、最大重试次数和审计事件使用；对外部副作用操作仍应设计 outbox 或人工确认流程。

## Git 交付与 Issue Writer

Agent 的交付边界是“可审查的补丁”，推荐流程如下：

```text
需求 → 检索 → 计划 → 小步修改 → 目标/回归测试 → Eval 报告 → Git commit → PR/Issue
```

`.agents/skills/coding-agent-issue-writer/SKILL.md` 用于把代码、CodeGraph/grep 结果、运行日志和截图整理成 Issue 草稿。它负责结构化和验证信息，不会在缺少标题、正文、标签或目标仓库确认时直接创建 Issue。

## 关键配置

| 配置 | 说明 |
| --- | --- |
| `MODEL_PROVIDER` / `MODEL_NAME` | 模型提供商和模型名 |
| `REPO_PATH` | Agent 操作的仓库路径 |
| `POSTGRES_DSN` | PostgreSQL 连接串，目标数据库为用户自己的 `coding_agent_db` |
| `PERSISTENCE_BACKEND` | `postgres` 或 `sqlite`；留空时按 DSN 自动选择 |
| `CHECKPOINT_DB_PATH` | SQLite checkpoint 文件路径 |
| `STORE_DB_PATH` | SQLite 业务 Store 文件路径 |
| `LANGGRAPH_STORE_DB_PATH` | SQLite LangGraph Store 文件路径 |
| `OPEN_SANDBOX_DOMAIN` | OpenSandbox 服务地址 |
| `OPEN_SANDBOX_API_KEY` | OpenSandbox API Key |
| `OPEN_SANDBOX_IMAGE` | 沙箱基础镜像 |
| `OPEN_SANDBOX_TIMEOUT_SECONDS` | 沙箱任务总超时 |

完整变量和默认值以 [`.env.example`](.env.example) 为准。

## 测试与验证

运行单元测试：

```powershell
python -m pytest tests/unit -q
```

运行 PostgreSQL 集成测试前，确保 PostgreSQL 服务可连接：

```powershell
python -m pytest tests/integration -q
```

验证迁移、Eval 和 OpenSandbox：

```powershell
python scripts/migrate_sqlite_to_postgres.py --help
python scripts/run_eval.py --mode fake --case-dir evals/smoke
python scripts/verify_opensandbox.py --help
```

## 安全边界与当前限制

- `.env`、模型密钥、数据库密码和沙箱 API Key 不应提交到 Git。
- Agent 默认只应操作显式授权的仓库路径；生产部署需要额外的权限、网络和资源限制。
- OpenSandbox 服务健康不等于沙箱任务成功，镜像拉取和节点网络需要单独验证。
- PostgreSQL 迁移前应备份 SQLite 文件，并在业务低峰期执行；迁移报告应保留用于审计。
- Eval 报告是决策依据，不等于业务正确性证明；高风险变更仍需人工 Review。

## 文档索引

- [核心架构](docs/CODING_AGENT_CORE.md)
- [运行时与流式执行](docs/CODING_AGENT_RUNTIME_STREAMING.md)
- [Harness 与 Agent Eval](docs/CODING_HARNESS_AGENT_EVAL_INTERVIEW_QA.md)
- [重建与演进计划](docs/CODING_REBUILD_PLAN.md)
- [云端 Docker 部署](docs/CODING_CLOUD_DOCKER_DEPLOYMENT.md)
- [GitHub Token 与 Provider](docs/GITHUB_TOKEN_AND_PROVIDER.md)
- [Issue Writer Skill](.agents/skills/coding-agent-issue-writer/SKILL.md)

## License

MIT
