<div align="center">

# CODING

### A repository-aware coding agent with a reviewable engineering loop.

Plan, search, implement, test, review, and deliver changes through a streaming workspace—with persistent sessions and reproducible agent evaluations.

[简体中文](README.md) · [English](README.en.md) · [Quick start](#quick-start) · [Architecture](#architecture) · [Agent Eval](#agent-eval)

[![Python](https://img.shields.io/badge/Python-3.14%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Vue](https://img.shields.io/badge/Vue-3-42B883?logo=vuedotjs&logoColor=white)](https://vuejs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-API-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-5b7fff.svg)](LICENSE)

</div>

<p align="center">
  <a href="assets/demo/coding-agent-demo.mp4">
    <img src="assets/demo/coding-agent-demo-autoplay.webp" alt="Autoplaying full HD CODING demo: repository search, code edits, checks, and pull request delivery" width="100%">
  </a>
</p>
<p align="center">▶ Full 89-second 1080p preview · <a href="assets/demo/coding-agent-demo.mp4">Open the HD video with playback controls</a></p>

## What is CODING?

CODING is a web-based AI coding agent for real Git repositories. It turns a request into a traceable workflow: understand the task, inspect the code, propose a plan, wait for approval when needed, edit and test in a repository workspace, then present the diff and delivery status.

## Highlights

| Capability | What it does |
| --- | --- |
| **Multi-agent workflow** | A primary agent coordinates work and can delegate analysis or read-only code review to specialist subagents. The review-to-fix loop keeps implementation and review responsibilities distinct. |
| **Multi-layer intent routing** | Structured LLM classification with a keyword-rule fallback routes planning, coding, review, QA, and related tasks; execution can then delegate subagents and choose tools for the next action. |
| **Repository intelligence** | Hybrid CodeGraph and text search, GitHub/Gitee context tools, and repository-scoped memory help the agent reuse project structure and decisions across sessions. |
| **Guarded execution** | A controlled file backend, path validation, tool-input checks, normalized tool errors, and run limits constrain agent actions. OpenSandbox is available for isolated Eval execution. |
| **Streaming and recovery** | FastAPI streams a stable event protocol to the Vue workspace; LangGraph checkpoints and persistent task state support session recovery. |
| **SQLite and PostgreSQL** | SQLite is the local default. PostgreSQL can persist application state and checkpoints for shared deployments. |
| **Agent Eval** | Fixed agent and target revisions, isolated candidate workspaces, target/regression/oracle checks, retrieval and tool traces, token/latency metrics, patches, and HTML reports. |

## Workspace Preview

<p align="center"><img src="assets/demo/workspace-home.png" alt="CODING workspace home with recent chats, repository projects, and model selection" width="100%"></p>
<p align="center"><em>Workspace home with recent chats, project groups, and the active conversation.</em></p>

<p align="center"><img src="assets/demo/create-project-dialog.png" alt="CODING create-project dialog with project name, Git provider, and repository URL" width="100%"></p>
<p align="center"><em>Create a project by setting its name, GitHub or Gitee provider, and repository URL.</em></p>

## Architecture

The vector SVG stays sharp when zoomed. Solid arrows show the current application and Eval paths.

<p align="center"><a href="assets/architecture-en.svg"><img src="assets/architecture-en.svg" alt="High-resolution CODING vector architecture: asynchronous task scheduling, agent execution, persistence, and isolated evaluation" width="100%"></a></p>
<p align="center">High-resolution vector diagram · <a href="assets/architecture-en.svg">Open the full-size SVG</a></p>

The deployment design describes **3 Agent Workers and 2 ASGI nodes**, with estimates of about **170 peak concurrent requests** and **20–30 concurrent coding/review tasks**. Treat these as design capacity estimates: this repository does not include a load-test report validating those figures. The Redis queue, repository lock, and event stream are shown as target components, not current application services.

## Agent Eval

The latest fixed suite evaluated CODING against the independent [`test-coding-eval`](https://github.com/Guo-Yixin/test-coding-eval) task repository. Agent revisions are recorded per case; the report uses DeepSeek `deepseek-flash` and runner v4.

<p align="center">
  <a href="docs/agent-eval/evidence/2026-09-27-final-suite/report.html">
    <img src="assets/eval/final-suite-summary.png" alt="Agent Eval report: 10 of 10 cases passed and both end-to-end gates passed" width="100%">
  </a>
</p>

| Fixed-suite measure | Result |
| --- | ---: |
| Coding cases | **10 / 10 passed** |
| Target, regression, and oracle tests | **10 / 10 passed each** |
| Patch application / retrieval hit@k / tool recovery | **100% / 1.0 / 100%** |
| Provider tokens / summed agent latency | **6,963,895 / 10.2 min** |
| Application and sandbox end-to-end gates | **2 / 2 passed** |

Open the [full coding-suite report](docs/agent-eval/evidence/2026-09-27-final-suite/report.html), [per-case Agent and target SHAs](docs/agent-eval/evidence/2026-09-27-final-suite/provenance.md), [OpenSandbox real-agent report](docs/agent-eval/evidence/2026-09-27-final-suite/opensandbox-agent/report.html), or [PostgreSQL application E2E report](docs/agent-eval/evidence/2026-09-27-final-suite/application-postgres-e2e/report.html). The score describes this fixed benchmark, agent revisions, model, and run configuration; it is not a universal coding-success guarantee.

## Quick start

### Requirements

- Python **3.14+**
- Node.js and Corepack (Yarn Classic 1.22)
- A DeepSeek API key

### Install and configure

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

Edit `.env` and set at least:

```dotenv
DEEPSEEK_API_KEY=your-deepseek-api-key
MAIN_MODEL=deepseek-flash
AI_WORKSPACE_ROOT=C:\coding-agent-workspace
DASHBOARD_JWT_SECRET=replace-with-a-long-random-secret
```

Keep `.env` local. Add `GITHUB_TOKEN` or `GITEE_TOKEN` only if you need authenticated access or write operations on those providers. Never commit real keys.

### Start the app

From the repository root, run:

```powershell
python scripts/start_all.py
```

Open <http://127.0.0.1:3000>. The API is at <http://127.0.0.1:2024/docs>. Press `Ctrl+C` to stop both services.

## Database and sandbox

- **SQLite (default):** no extra service is needed for local development; project data is stored under `data/`.
- **PostgreSQL (optional):** provision a dedicated database and add this to `.env`:

  ```dotenv
  PERSISTENCE_BACKEND=postgres
  POSTGRES_DSN=postgresql://user:password@127.0.0.1:5432/coding_agent_db
  ```

  Follow the [deployment guide](docs/CODING_CLOUD_DOCKER_DEPLOYMENT.md) for shared deployments.
- **OpenSandbox (optional):** install `python -m pip install -e ".[sandbox]"`, start an OpenSandbox service, then configure:

  ```dotenv
  OPEN_SANDBOX_DOMAIN=https://your-opensandbox-service
  OPEN_SANDBOX_API_KEY=your-opensandbox-key
  ```

  The current OpenSandbox adapter is used by isolated Eval paths; the regular local app uses its controlled local workspace backend.

See [`.env.example`](.env.example), [Linux deployment](docs/CODING_LINUX_DEPLOYMENT_RUNBOOK.md), [cloud deployment design](docs/CODING_CLOUD_DOCKER_DEPLOYMENT.md), and [Agent Eval guide](docs/AGENT_EVAL.md) for the complete configuration and operating boundaries.

## Contributing

Issues and pull requests are welcome. Describe the problem, the proposed change, and how you verified it. Changes to agent behavior, tools, permissions, persistence, or evaluation should include focused tests or an Eval case. Start with the [project docs](docs/) and open an Issue when the intended behavior needs discussion.

## License

CODING is released under the [MIT License](LICENSE).
