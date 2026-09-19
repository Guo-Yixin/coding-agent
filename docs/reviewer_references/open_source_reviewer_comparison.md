# 开源 AI Code Reviewer 参考资料对比

> 本文只记录公开资料中可观察到的能力和设计点，用于 CODING 第一版 Gitee Reviewer 子 Agent 设计参考。
> 不直接复制外部项目源码，避免引入 GitHub Action、GitHub App、Vercel Sandbox 等与当前 FastAPI + DeepAgents 架构无关的复杂依赖。

## 1. Alibaba open-code-review

项目地址：

- https://github.com/alibaba/open-code-review

公开资料中值得参考的点：

| 设计点 | 资料描述 | 对 CODING 的启发 |
|---|---|---|
| 确定性工程 + Agent 混合 | README 强调不要完全依赖通用 Agent，自身用确定性逻辑保证文件选择、规则匹配、定位校验等关键步骤 | Reviewer 子 Agent 不应该自由发挥；diff 解析、文件分组、行号校验应由 Python 代码完成 |
| 结构化 review comments | 项目目标是生成 line-level precision 的结构化审查评论 | 本项目已有 `review_findings` 表，可以继续做结构化保存 |
| 文件选择和文件分组 | 资料中提到 precise file selection、smart file bundling | 第一版可以先按变更文件分组，后续再按语言/模块分组 |
| 规则匹配 | 资料中提到 fine-grained rule matching | 第一版先用 Markdown 规则，后续可做路径/语言匹配 |
| 内置缺陷规则方向 | README 提到 NPE、thread-safety、XSS、SQL injection | 可作为默认规则维度 |
| 多模式 diff 输入 | 支持 workspace、branch range、single commit、scan | 本项目第一版先支持本地 branch diff 和 Gitee PR diff 信息 |

适合借鉴：

- 审查流水线。
- 规则体系。
- 行号校验。
- 不完全依赖自然语言 prompt。

不建议照搬：

- CLI 安装机制。
- 多平台 CI/CD 适配。
- 大规模 benchmark 和复杂规则引擎。

## 2. serge

项目资料：

- https://huggingface.github.io/serge/

公开资料中值得参考的点：

| 设计点 | 资料描述 | 对 CODING 的启发 |
|---|---|---|
| OpenAI-compatible endpoint | 支持 OpenAI 兼容模型 | 当前项目 DeepSeek 也是 OpenAI 兼容接口 |
| 仓库级规则 | 支持 `.ai/review-rules.md` | 本项目可以支持 `.lx/review-rules.md` |
| 可选上下文脚本 | 支持 `.ai/context-script` | 第一版暂不做脚本，避免执行任意仓库代码 |
| 只读上下文工具 | 可使用只读 repository context tools | Reviewer 子 Agent 应默认只读 |
| diff 行定位验证 | 只发布指向真实 diff 位置的评论 | finding 必须校验文件和行号是否属于 diff |
| human-in-the-loop | 支持 staged reviews | 本项目发布 Gitee PR 评论前要求用户确认 |

适合借鉴：

- 仓库内规则文件。
- finding 位置必须落在真实 diff 上。
- 只读 reviewer 默认模式。

不建议第一版照搬：

- GitHub Pull Request Reviews API。
- 行级发布评论，因为 Gitee 行级评论 position 兼容需要单独验证。

## 3. Robin

项目资料：

- https://www.robinreview.dev/

公开资料中值得参考的点：

| 设计点 | 资料描述 | 对 CODING 的启发 |
|---|---|---|
| BYOK | 用户自己的模型 key | 当前项目沿用 `.env` 中 DeepSeek/Gitee 配置 |
| diff-only privacy | 公开资料强调 diff-only 发送给 LLM | Reviewer 第一版控制上下文规模，优先给 diff 和必要文件上下文 |
| severity-tiered findings | 示例中有 High、Medium、Suggestions | 本项目 findings 使用 `critical/high/medium/low/info` |
| Summary + inline findings | PR 中既有总结，也有行内建议 | 第一版先做总结评论，行级评论后续扩展 |
| on-demand re-review | 支持命令触发重新审查 | 本项目可以通过用户输入“重新 review PR”触发 |

适合借鉴：

- 输出格式。
- severity 分级。
- diff-only 的隐私边界。

不建议照搬：

- GitHub Actions 工作流。
- GitHub inline comment 发布逻辑。

## 4. Vercel OpenReview

项目地址：

- https://github.com/vercel-labs/openreview

公开资料中值得参考的点：

| 设计点 | 资料描述 | 对 CODING 的启发 |
|---|---|---|
| On-demand reviews | 在 PR 评论里提到机器人触发 | 当前项目通过网页输入触发 reviewer |
| Sandboxed execution | 克隆仓库后在 sandbox 中读文件、跑 lint/test | 当前项目使用 `B:\ai_workspace` + LocalShellBackend 实现本地受控工作区 |
| Inline suggestions | 可以发布 suggestion blocks | Gitee 第一版先不做行级 suggestion |
| 可修改简单问题 | 能修复 lint/format 并 push | 本项目 Reviewer 子 Agent 第一版不改代码 |
| Extensible skills | 支持内置和自定义 skills | 本项目应增强 `code-review` skill |

适合借鉴：

- reviewer 可以读仓库、运行项目工具。
- skills 驱动审查流程。

不建议第一版照搬：

- 自动修复并 push。
- Vercel Sandbox 和 GitHub App 生命周期。

## 5. Dailybot AI Diff Reviewer

项目资料：

- https://www.dailybot.com/open-source/ai-diff-reviewer/

公开资料中值得参考的点：

| 设计点 | 资料描述 | 对 CODING 的启发 |
|---|---|---|
| 一套方法论，两种表面 | 同时支持 GitHub Action 和本地 coding-agent skill | 本项目可以把 review 方法论写入 skill，让网页任务和未来 CI 都可复用 |
| severity gating | 支持 critical/warning/info 类似门禁 | 本项目可以用 critical/high 决定“不建议合并” |
| 自动折叠旧评论 | 避免 PR 噪音 | 第一版可以先在本地 findings 去重，Gitee 评论后续再做折叠 |
| BYOK | 用户自己的模型供应商 | 当前项目符合 |

适合借鉴：

- 规则方法论沉淀到 skill。
- severity gating。

不建议第一版照搬：

- GitHub Marketplace Action。
- GitHub 原生 review API。

## 6. 对 CODING 第一版的取舍结论

第一版应采用：

1. 确定性 Python 逻辑负责 diff 解析、文件列表、变更行号、finding 校验。
2. Reviewer 子 Agent 负责结合规则和上下文判断风险。
3. 规则来源采用三层：仓库规则、工作区规则、项目内置规则。
4. finding 先写入本地 SQLite，不直接发布到 Gitee。
5. 最终中文审查报告询问用户是否发布到 Gitee PR 普通评论。

第一版暂不采用：

1. Gitee 行级评论。
2. 自动修复并 push。
3. 任意仓库脚本执行。
4. 复杂规则 DSL。
5. 多平台 GitHub/GitLab/Gerrit 支持。
