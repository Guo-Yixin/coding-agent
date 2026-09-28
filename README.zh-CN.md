<div align="center">

# CODING

### 面向真实 Git 仓库、可追踪且可复跑的 AI 编码 Agent

从需求理解、代码检索、计划审批，到修改、测试、审查与交付；支持持久化会话和可复现的 Agent Eval。

[English](README.md) · [简体中文](README.zh-CN.md) · [快速开始](#快速开始) · [系统架构](#系统架构) · [Agent Eval](#agent-eval)

[![Python](https://img.shields.io/badge/Python-3.14%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Vue](https://img.shields.io/badge/Vue-3-42B883?logo=vuedotjs&logoColor=white)](https://vuejs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-API-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-5b7fff.svg)](LICENSE)

</div>

<p align="center">
  <a href="assets/demo/coding-agent-demo.mp4">
    <img src="assets/demo/coding-agent-demo-poster.png" alt="点击观看 CODING 1080p 演示：检索仓库、修改代码、运行检查并交付 Pull Request" width="100%">
  </a>
</p>
<p align="center">▶ <a href="assets/demo/coding-agent-demo.mp4">观看 89 秒 1080p 完整演示</a></p>

## CODING 是什么

CODING 是一个面向真实 Git 仓库的 AI 编码工作台。它把用户需求变成一条可追踪的研发流程：理解任务、检索代码、提出计划、按需等待审批、在仓库工作区修改和测试，最后展示补丁与交付状态。

## 项目亮点

| 能力 | 说明 |
| --- | --- |
| **多 Agent 协作** | 主 Agent 负责任务编排和结果汇总，可按需委派分析或只读代码审查 SubAgent。编码、审查和修复职责分开，支持形成可检查的研发闭环。 |
| **多层意图路由** | 使用结构化 LLM 分类并以关键词规则兜底，识别 planning、coding、review、QA 等入口任务；执行中再委派 SubAgent、拆分任务并决定下一步工具动作。 |
| **仓库级理解** | CodeGraph 与文本混合检索、GitHub/Gitee 上下文工具及仓库长期记忆，帮助 Agent 复用项目结构和历史决策。 |
| **受控执行** | 受控文件后端、路径校验、工具参数检查、可理解的工具错误和运行上限约束 Agent 操作。OpenSandbox 可用于隔离的 Eval 执行。 |
| **流式与恢复** | FastAPI 通过稳定事件协议向 Vue 工作台流式推送过程；LangGraph checkpoint 与持久化任务状态支持会话恢复。 |
| **SQLite 与 PostgreSQL** | SQLite 是本地默认选项；PostgreSQL 可用于共享部署中的业务状态和 checkpoint 持久化。 |
| **Agent Eval** | 固定 Agent 和目标版本，在隔离副本中执行真实编码题、目标/回归/隐藏验收，记录检索、工具轨迹、Token、耗时、补丁并生成 HTML 报告。 |

## 系统架构

实线表示当前应用和 Eval 的运行路径；虚线区域表示文档中的横向扩容目标，并非默认运行拓扑。

<p align="center"><a href="assets/architecture-zh.svg"><img src="assets/architecture-flow-zh.gif" alt="CODING 动态架构图：需求路由、Agent 执行、隔离评测与报告反馈" width="100%"></a></p>
<p align="center">动态流程图 · <a href="assets/architecture-zh.svg">打开可缩放 SVG 源图</a></p>

部署设计描述了 **3 个 Agent Worker 和 2 个 ASGI 节点**，并给出约 **170 峰值并发请求、20–30 个 coding/review 并发任务**的容量估算。仓库目前没有包含验证这些数字的压测报告，因此应视为设计容量估算。图中的 Redis 队列、仓库锁和事件流是目标组件，不是当前应用服务。

## Agent Eval

最近一次固定题库评测使用独立的 [`test-coding-eval`](https://github.com/Guo-Yixin/test-coding-eval) 仓库。各案例记录了对应的 Agent 版本；本次使用 DeepSeek `deepseek-flash` 和 runner v4。

<p align="center">
  <a href="docs/agent-eval/evidence/2026-09-27-final-suite/report.html">
    <img src="assets/eval/final-suite-summary.png" alt="Agent Eval 报告：10 道编码题全部通过，两个端到端门禁通过" width="100%">
  </a>
</p>

| 固定题库指标 | 结果 |
| --- | ---: |
| 编码题 | **10 / 10 通过** |
| 目标、回归、隐藏验收 | **各 10 / 10 通过** |
| 补丁应用 / 检索 hit@k / 工具恢复 | **100% / 1.0 / 100%** |
| Provider Token / Agent 累计耗时 | **6,963,895 / 10.2 分钟** |
| 应用与沙箱端到端门禁 | **2 / 2 通过** |

查看[完整编码题报告](docs/agent-eval/evidence/2026-09-27-final-suite/report.html)、[逐题 Agent/目标仓库 SHA](docs/agent-eval/evidence/2026-09-27-final-suite/provenance.md)、[真实 Agent + OpenSandbox 报告](docs/agent-eval/evidence/2026-09-27-final-suite/opensandbox-agent/report.html)，或 [PostgreSQL 应用端到端报告](docs/agent-eval/evidence/2026-09-27-final-suite/application-postgres-e2e/report.html)。该成绩只代表这组固定案例、记录的 Agent 版本、模型和运行配置，不代表 Agent 在任意项目上的通用成功率。

## 快速开始

### 环境要求

- Python **3.14+**
- Node.js 与 Corepack（Yarn Classic 1.22）
- DeepSeek API Key

### 安装并配置

```powershell
git clone https://github.com/Guo-Yixin/coding-agent.git
cd coding-agent
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e . "deepagents==0.6.11"
corepack prepare yarn@1.22.22 --activate
Set-Location ui
yarn install --frozen-lockfile
Set-Location ..
Copy-Item .env.example .env
```

编辑 `.env`，至少填写：

```dotenv
DEEPSEEK_API_KEY=your-deepseek-api-key
MAIN_MODEL=deepseek-flash
AI_WORKSPACE_ROOT=C:\coding-agent-workspace
DASHBOARD_JWT_SECRET=替换为足够长的随机密钥
```

`.env` 只保存在本机。只有需要访问私有仓库或执行平台写操作时，才配置 `GITHUB_TOKEN` 或 `GITEE_TOKEN`；不要把真实密钥提交到 Git。

### 启动前后端

在仓库根目录运行：

```powershell
python scripts/start_all.py
```

打开 <http://127.0.0.1:3000>；后端 API 文档位于 <http://127.0.0.1:2024/docs>。按 `Ctrl+C` 同时停止前后端。

## 数据库与沙箱

- **SQLite（默认）：** 本地开发无需单独启动数据库服务，项目数据保存在 `data/`。
- **PostgreSQL（可选）：** 准备独立数据库，并在 `.env` 中配置：

  ```dotenv
  PERSISTENCE_BACKEND=postgres
  POSTGRES_DSN=postgresql://user:password@127.0.0.1:5432/coding_agent_db
  ```

  共享部署请参考[部署设计](docs/CODING_CLOUD_DOCKER_DEPLOYMENT.md)。
- **OpenSandbox（可选）：** 安装 `python -m pip install -e ".[sandbox]"`，启动 OpenSandbox 服务后配置：

  ```dotenv
  OPEN_SANDBOX_DOMAIN=https://your-opensandbox-service
  OPEN_SANDBOX_API_KEY=your-opensandbox-key
  ```

  当前 OpenSandbox 适配器用于隔离的 Eval 执行；常规本地应用使用受控本地工作区后端。

完整变量见 [`.env.example`](.env.example)；更多内容见 [Linux 部署手册](docs/CODING_LINUX_DEPLOYMENT_RUNBOOK.md)、[云端部署设计](docs/CODING_CLOUD_DOCKER_DEPLOYMENT.md)和 [Agent Eval 指南](docs/AGENT_EVAL.md)。

## 参与贡献

欢迎提交 Issue 和 Pull Request。请说明问题、改动目的和验证方式。涉及 Agent 行为、工具权限、持久化或评测的改动，请附上针对性测试或 Eval 案例。可先阅读[项目文档](docs/)，需要讨论方案时先开 Issue。

## 许可证

CODING 使用 [MIT License](LICENSE) 发布。
