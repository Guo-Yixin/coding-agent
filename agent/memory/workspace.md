# 本地工作区记忆

CODING 使用受控本地工作区执行 Agent 任务。工作区真实路径由环境变量 `AI_WORKSPACE_ROOT` 决定：

- Windows 本地开发通常使用 `B:\ai_workspace`。
- Linux 或 Docker 部署建议使用 `/opt/coding/workspace`。

模型和工具对外统一使用虚拟路径，不应依赖宿主机真实绝对路径。这个目录来自 open-swe 的本地 workspace 设计，里面包含若干固定用途的子目录。
本文件只记录工作区事实，不承载强制行为规则；具体工具权限、读写边界和执行规范由系统提示词与后端权限控制。

## 目录语义

- `projects/`：GitHub/Gitee 仓库 checkout 根目录。每轮任务的真实仓库目录由运行时根据所选 provider、owner 和 repo 解析，并在 Agent 启动前校验 `origin`；不要根据仓库名猜测目录，也不要复用其它仓库 checkout。
- `skills/`：DeepAgents 原生 skill 目录，Agent 运行时通过 `/skills` 虚拟路径读取。
- `runtimes/`：共享运行环境目录，例如 Python 虚拟环境、Node 或其它项目运行时。
- `policies/`：编码规范、审查规范、安全规范目录。
- `reviews/`：代码审查、分析结果、历史评审资料目录。
- `logs/`：工作区级运行日志目录，用于排查 Agent 或项目运行过程。
- `tmp/`：临时文件目录，用于短期中间产物。
- `.secrets/`：敏感凭据辅助目录。
- `.ai_coding_workspace.json`：工作区元信息文件，用于识别本地工作区状态。

具体仓库路径以本轮 Agent 运行上下文提供的“仓库专属工作目录”为准。若该目录的 Git `origin` 与本轮所选仓库不符，任务必须停止并报告，不得通过改写 `origin` 来复用旧提交历史。
