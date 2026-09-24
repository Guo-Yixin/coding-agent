---
name: repo-bootstrap-analysis
description: 面向 GitHub/Gitee 仓库的首次项目分析流程。第一次处理某个仓库、生成技术方案、分析项目结构、确认启动/测试方式或接手陌生项目时使用。
---

# GitHub/Gitee 仓库首次分析

你正在分析一个 Gitee 仓库。目标不是立刻写代码，而是先建立对项目的可靠认知，避免在不了解目录结构、启动方式、测试方式和业务边界的情况下贸然修改文件。

所有面向用户的自然语言输出必须使用中文。代码、路径、命令、配置字段、分支名、文件名和编程标识符可以保持英文。

## 1. 准备 GitHub/Gitee 仓库

当前阶段支持 GitHub.com 和 Gitee Cloud，不考虑 GitHub Enterprise、私有 Gitee 部署、GitLab 或其他代码托管平台。

如果用户提供了 GitHub/Gitee 仓库地址：

1. 先确认地址形如 `https://github.com/<owner>/<repo>`、`https://gitee.com/<owner>/<repo>`，或 `owner/repo` 简写。
2. 使用 `ls("/projects")` 查看本地是否已有同名目录。
3. 如果本地不存在，使用 `execute` 执行普通 Git 命令克隆仓库，例如：
   `git clone https://gitee.com/<owner>/<repo>.git`
4. 如果本地已存在，使用 `execute` 检查状态，例如：
   `git -C <repo> status`
   `git -C <repo> fetch --all`

GitHub/Gitee Token 由 `LocalShellBackend` 通过 Git askpass 自动注入。不要把 token 写进命令、文件、commit message、PR 描述或用户回复。

仓库源码应该位于工作区的 `/projects/` 下，由运行时按平台和仓库名稳定映射。不要把以下目录当作业务源码：

- `/runtimes`：运行环境目录，例如 Python 虚拟环境或 Node 运行时。
- `/skills`：DeepAgents skill 目录，只读。
- `/policies`：规范、策略、约束材料，只读。
- `/reviews`：审查结果或历史资料。
- `/logs`：运行日志目录，只读。
- `/tmp`：临时文件。
- `.secrets`：敏感凭据目录，禁止读取、展示、复制或写入用户可见结果。

## 2. 建立项目基本画像

优先读取这些文件或目录，按实际存在情况选择，不要假设它们一定存在：

| 目标 | 常见文件或目录 | 需要判断的内容 |
|---|---|---|
| 项目说明 | `README.md`、`docs/` | 项目用途、启动方式、部署方式 |
| Python 依赖 | `pyproject.toml`、`requirements.txt`、`setup.py` | Python 版本、依赖、测试命令 |
| Node 依赖 | `package.json`、`pnpm-lock.yaml`、`yarn.lock` | 前端框架、脚本命令、构建方式 |
| 后端入口 | `main.py`、`app.py`、`src/`、`server/` | Web 框架、路由入口、服务启动方式 |
| 前端入口 | `vite.config.*`、`src/`、`pages/`、`components/` | Vite/React/Vue 等框架和页面结构 |
| 测试目录 | `tests/`、`test/`、`pytest.ini` | 测试框架、可运行的最小测试 |
| 数据层 | `models/`、`db.py`、`database.py`、`migrations/` | 数据存储方式、迁移风险 |
| 配置 | `.env.example`、`config/`、`settings.py` | 环境变量、敏感配置边界 |

读取目录前先用 `ls`，读取文件时只对具体文件使用 `read_file`。路径必须使用 DeepAgents 虚拟路径，例如 `/projects/ai_coding/README.md`。

执行命令时要注意：DeepAgents 原生 `execute` 默认已经在 `/projects` 对应的本地目录下执行，所以命令中的仓库路径直接写 `<repo>`，例如 `git -C ai_coding status`。不要在 `execute` 命令中再写 `projects/<repo>`，否则会变成错误的 `projects/projects/<repo>`。

## 3. 分析输出必须覆盖的内容

完成首次分析后，整理一份简洁但有证据的中文结论，至少包括：

1. **仓库定位**：GitHub/Gitee 地址、本地目录、当前分支或状态。
2. **技术栈**：后端、前端、数据库、测试框架、主要依赖。
3. **目录结构**：关键目录和文件分别负责什么。
4. **启动方式**：根据文件推断出的启动命令；不确定时明确说明“不确定”。
5. **测试方式**：已有测试命令、测试目录、最小验证建议。
6. **改造风险**：哪些文件不应贸然修改，哪些模块需要先读清楚。
7. **下一步建议**：如果用户要开发，下一步应该先形成技术方案，再等待确认。

不要输出固定模板；必须根据仓库真实文件组织答案。

## 4. 生成技术方案时的额外要求

如果用户要求“生成方案”“给我改造方案”“先不要写代码”，必须：

1. 先完成仓库首次分析。
2. 再说明候选实现路径。
3. 明确推荐方案和理由。
4. 列出预计修改文件、验证命令和风险点。
5. 最后询问用户：`是否确认实施该方案？`

技术方案的目标是让用户确认“实施方向”，不是提前生成完整代码。输出时必须遵守：

1. 推荐使用这些部分组织内容：
   - 需求理解；
   - 当前实现判断；
   - 推荐方案；
   - 预计修改文件；
   - 数据结构或接口变化表；
   - 实施步骤；
   - 验证方式；
   - 风险点；
   - `是否确认实施该方案？`
2. 不要输出完整类定义、完整函数、完整测试用例、完整 HTML 模板或完整 SQL 脚本。
3. 不要写“在某文件末尾追加以下代码”然后贴一大段代码。
4. 可以用表格说明字段、接口和文件变化，例如列出字段名、类型、约束、说明。
5. 可以用 3 到 8 行伪代码描述核心流程，但不要把伪代码写成可直接复制运行的完整实现。
6. 除非用户明确要求“给出代码示例”或“把代码写出来”，否则 Markdown 代码块总长度不要超过 10 行。
7. 如果需要说明代码结构，用自然语言描述修改点，例如“新增 Department 模型，字段包括 id/name/description/created_at”，不要贴完整实现。

在用户确认前，禁止修改文件、提交代码、push 分支或创建 Pull Request。

## 5. 可以使用外部资料，但不能替代本地分析

如果涉及第三方框架、最新 API 或用户给出了官方文档链接，可以使用：

- `web_search`：搜索外部资料。
- `fetch_url`：读取用户指定的公开 HTTP/HTTPS 页面或官方文档页面。

外部资料只能作为辅助。最终判断必须回到当前 GitHub/Gitee 仓库中的真实文件。
