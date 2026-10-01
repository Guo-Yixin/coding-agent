/**
 * 契约层 —— 后端返回数据的形状（唯一真相源）。
 *
 * 本项目用 JavaScript 而非 TypeScript，所以契约用 JSDoc `@typedef` 表达：
 * 编辑器能补全、能报错，但不需要引入 TS 工具链。
 *
 * 引用方式：`/** @type {import('./types.js').Thread} *\/`
 *
 * ⚠️ 三条规则
 * 1. **本文件的形状必须以真实响应为准**，不许凭印象写。当前形状全部由
 *    `http://127.0.0.1:2024/dashboard/api` 的真实响应实测得到（见文件末尾「取证记录」）。
 * 2. 组件**永远不直接 fetch**。所有网络访问走 `client.js`（axios）或 `sse.js`（流式）。
 * 3. 后端改了形状，**先改本文件**，再改用到它的组件 —— 顺序反了就等于没有契约。
 *
 * @module api/types
 */

// ───────────────────────── 基础 ─────────────────────────

/**
 * 当前登录用户。`GET /me`
 * @typedef {object} Me
 * @property {string} login
 * @property {string|null} email
 * @property {string|null} avatar_url
 * @property {boolean} is_admin
 * @property {boolean} slack_oauth_enabled
 */

/**
 * 一个可选模型。`GET /options` → `models[]`
 * @typedef {object} ModelOption
 * @property {string} id            例如 "deepseek-flash"
 * @property {string} label
 * @property {string[]} efforts     例如 ["default"]
 * @property {string} default_effort
 * @property {boolean} supports_images
 */

/**
 * 一个可选仓库托管方。`GET /options` → `providers[]`
 * @typedef {object} ProviderOption
 * @property {string} id            例如 "github"
 * @property {string} label         例如 "GitHub"
 * @property {string} url_placeholder
 */

/**
 * 全局可选项与默认值。`GET /options`
 * @typedef {object} Options
 * @property {string} default_repo
 * @property {string} default_provider
 * @property {ProviderOption[]} providers
 * @property {string} repo_placeholder
 * @property {ModelOption[]} models
 * @property {string} default_agent_model
 * @property {string} default_agent_reasoning_effort
 * @property {string} default_agent_subagent_model
 * @property {string} default_agent_subagent_reasoning_effort
 */

// ───────────────────────── 消息 ─────────────────────────

/**
 * 消息块：纯文本。
 * @typedef {object} TextChunk
 * @property {'text'} kind
 * @property {string} text
 */

/**
 * 消息块：一次运行的元信息（运行轨迹折叠条的标题行）。
 * 注意这里**只有元信息**，详细事件要用 `activity.run_id` 再去
 * `GET /threads/{threadId}/runs/{runId}/events` 取。
 * @typedef {object} RunActivityChunk
 * @property {'run_activity'} kind
 * @property {RunActivity} activity
 */

/**
 * @typedef {object} RunActivity
 * @property {string} run_id
 * @property {'queued'|'running'|'completed'|'failed'|'cancelled'} status
 * @property {string} started_at   ISO 8601（带 +08:00 偏移）
 * @property {string|null} finished_at
 * @property {string|null} error
 */

/**
 * 消息块：一份等待用户批准/已批准的技术方案。
 * @typedef {object} ProposalChunk
 * @property {'proposal'} kind
 * @property {'pending'|'approved'|'rejected'|'superseded'} status
 * @property {string} plan_id
 * @property {number} version
 * @property {string} plan_text     Markdown
 * @property {string} source_prompt 触发这份方案的原始输入
 */

/**
 * 清单里的一项。
 * @typedef {object} TodoItem
 * @property {'pending'|'in_progress'|'completed'} status
 * @property {string} content
 */

/**
 * 消息块：计划清单。
 * @typedef {object} TodoChunk
 * @property {'todo'} kind
 * @property {TodoItem[]} todos
 */

/**
 * 消息块：一次错误的正文（渲染成 `.error-banner`，与其它块**共存**而不是取而代之）。
 * @typedef {object} ErrorChunk
 * @property {'error'} kind
 * @property {string} text
 */

/**
 * 消息块：需要人来拍板的一次介入。
 * `status` 为 `pending` 时卡片渲染成表单；`resuming` 时只显示「正在恢复处理中」。
 * @typedef {object} InterventionChunk
 * @property {'intervention'} kind
 * @property {string} intervention_id
 * @property {'pending'|'resuming'|'resolved'} status
 * @property {string} reason
 * @property {string} question
 * @property {string[]} [options]   可选的快捷选项；为空时只显示自由输入
 */

/**
 * 消息块联合类型。**渲染时按 `kind` 分支，不要用 `if (chunk.text)` 猜。**
 * @typedef {TextChunk | RunActivityChunk | TodoChunk | ProposalChunk | InterventionChunk | ErrorChunk} MessageChunk
 */

/**
 * 一条消息。
 * @typedef {object} Message
 * @property {string} id
 * @property {'user'|'agent'} author   注意是 `author` 不是 `role`
 * @property {string} timestamp        ISO 8601
 * @property {MessageChunk[]} chunks
 */

// ───────────────────────── 运行轨迹 ─────────────────────────

/**
 * 一条运行事件。`GET /threads/{threadId}/runs/{runId}/events` → `events[]`
 * @typedef {object} RunEvent
 * @property {string} id
 * @property {'think'|'other'|'todo'} kind
 * @property {string} title
 * @property {'pending'|'running'|'completed'|'failed'} status
 * @property {string} created_at  ISO 8601
 * @property {object} detail      形状随 kind 变化（观测到的是 `{}`）
 */

/**
 * 运行事件的响应外壳。
 * @typedef {object} RunEventsResponse
 * @property {string} run_id
 * @property {RunEvent[]} events
 */

// ───────────────────────── 会话与项目 ─────────────────────────

/**
 * 一个会话。`GET /threads` → 数组元素（消息内联，响应可能达数百 KB）
 * @typedef {object} Thread
 * @property {string} id
 * @property {string} projectId
 * @property {boolean} chatOnly
 * @property {string} title
 * @property {string} repo
 * @property {string} repoFullName   可能为空字符串（不是 null）
 * @property {string} provider
 * @property {string|null} branch
 * @property {string} baseBranch
 * @property {string} model
 * @property {string|null} effort
 * @property {string} source
 * @property {'idle'|'running'|'finished'|'error'} status
 * @property {number} createdAt       毫秒时间戳（不是 ISO 字符串）
 * @property {number} updatedAt       毫秒时间戳
 * @property {string} draftContent
 * @property {Message[]} messages
 * @property {object|null} pendingIntervention
 * @property {object|null} pr
 * @property {object|null} latestPlan
 * @property {object|null} diffStats
 * @property {string[]} changedFiles
 */

/**
 * 一个项目（含其会话）。`GET /projects` → 数组元素
 * @typedef {object} Project
 * @property {string} id
 * @property {string} name
 * @property {string|null} provider
 * @property {string|null} repo
 * @property {string} repoFullName
 * @property {boolean} legacy         true = 「历史会话」这类无仓库的兜底分组
 * @property {Thread[]} conversations
 */

// ───────────────────────── 流式（SSE） ─────────────────────────

/**
 * `sse.js` 解析后交给 `onEvent` 的事件。
 * @typedef {object} StreamEvent
 * @property {string} event   SSE `event:` 名（服务端也可能改用 body 里的 `event` 字段）
 * @property {object} data    JSON 解析后的负载
 * @property {string|null} id SSE `id:` 名
 */

/**
 * 三个流式出口（都在 `sse.js` 里）：
 * - `POST /threads/stream-message`（新会话）
 * - `POST /threads/{threadId}/stream-message`（已有会话）
 * - `GET  /threads/{threadId}/runs/{runId}/stream?after=<n>`（断线重连 / 续看运行）
 *
 * 四态要求（DESIGN.md 第 6 节）：pending / streaming / done / error 都必须在
 * 有真后端之前就定死，否则接流式时页面会缺状态。
 */

// ───────────────────────── 取证记录 ─────────────────────────

/**
 * 实测于 `http://127.0.0.1:2024/dashboard/api`（Postgres 后端，24 个会话 / 201 条消息 / 71 个 run）：
 *
 * | 端点 | HTTP | 大小 | 说明 |
 * |---|---|---|---|
 * | `GET /me` | 200 | 93 B | |
 * | `GET /options` | 200 | 775 B | |
 * | `GET /projects` | 200 | 6399 B | 4 个项目 |
 * | `GET /threads` | 200 | 410459 B | 24 个会话，messages 内联 |
 * | `GET /runs/active` | 200 | 2 B | `[]` |
 * | `GET /threads/{t}/runs/{r}/events` | 200 | 61–? B | `{run_id, events}`，多数 run 的 events 为空 |
 *
 * 观测到 `author` 只有 `user` / `agent` 两种；`RunEvent.kind` 只有
 * `think` / `other` / `todo` 三种。
 *
 * **`chunks[].kind` 实测只见到 `text` / `run_activity` / `proposal` 三种，但代码里一共处理六种。**
 * 另外三种（`todo` / `error` / `intervention`）的形状是从 `ChatMessage.vue` 与它分发的子组件
 * 的字段用法反推出来的，**不是从真实响应里取到的** —— 现有 24 个会话 / 201 条消息里一个都没有。
 * 它们的渲染路径由 `ui/preview/messages.html` 人工种出状态来验证（见 `docs/design/DESIGN.md` §15）。
 *
 * **未观测到实际值**（当前数据里恒为 null，形状以 `stores/agent.js` 的用法为准，
 * 接入相关 UI 前必须再取一次真实样本）：`Thread.pendingIntervention`、`Thread.pr`、
 * `Thread.latestPlan`、`Thread.diffStats`。
 */
export {}
