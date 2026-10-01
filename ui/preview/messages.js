// 消息块状态预览夹具：把 ChatMessage 能渲染的每一种 chunk kind 与每一种状态铺开。
//
// 为什么需要它：proposal / intervention / todo / error 这几种块**只在特定数据下出现**，
// 现有会话数据里一个都没有，所以既点不出来也截不到。而 ChatMessage.vue 是"块分发中心"——
// 它按 chunk.kind 分支渲染五个子组件，任何一个子组件的状态都可能没被看过。
//
// 用法：
//   node scripts/capture.mjs http://127.0.0.1:3000/preview/messages.html shots --widths 1560 --height 2400 --budget 8000 --name messages
import { createApp, h } from 'vue'

import '/src/styles/tokens.css'
import '/src/styles/main.css'
import ChatMessage from '/src/components/ChatMessage.vue'

const T = 1756742400000 // 固定时间戳，避免截图随时间变化

function user(text) {
  return { id: 'u', author: 'user', timestamp: T, chunks: [{ kind: 'text', text }] }
}
function agent(chunks) {
  return { id: 'a', author: 'agent', timestamp: T, chunks }
}

const LONG_USER = Array.from({ length: 11 }, (_, i) => `第 ${i + 1} 行：这是一条很长的用户消息，用来触发「显示更多」。`).join('\n')

const MARKDOWN = [
  '## 改造要点',
  '',
  '把 `main.css` 里的字面量收敛到 token，**类名一个不动**。',
  '',
  '- 字号 19 档 → 7 档',
  '- 圆角 20 档 → 4 档',
  '',
  '```js',
  "const audit = await run('ui/src', { ignore: ['tokens.css'] })",
  'console.log(audit.checks.filter((c) => !c.pass))',
  '```',
].join('\n')

// 运行中的用例必须用"相对现在"的起点，否则「用时」会算出几百天，看着像 bug 其实是夹具的锅。
const RUNNING_START = new Date(Date.now() - 74000).toISOString()
const FAILED_END = new Date(T + 12000).toISOString()

const TODOS = [
  { content: '读取现有 main.css 并建立字面量分布', status: 'completed' },
  { content: '把 19 种字号归到 7 档', status: 'completed' },
  { content: '收敛圆角与近白背景', status: 'in_progress' },
  { content: '重跑 audit 并核对分数', status: 'pending' },
]

// 运行轨迹的事件。`kind: 'think'` 是模型推理（会被收进「深度思考」那一层），
// `other` 是工具/步骤（留在平铺时间线里）。夹具必须给真实事件 ——
// 传空数组时执行记录永远是「暂无可展示的执行过程」，深度思考那一层根本不会出现。
const THINK_EVENTS = [
  { id: 't-1', kind: 'think', title: '先确认圆角到底散在哪些地方 —— 如果本来就只有三四种，收敛的意义不大，得先看分布再决定要不要动。', status: 'completed', detail: {} },
  { id: 't-2', kind: 'think', title: '19 种字号里多半是同一档的近似值（12.5 / 12.8 / 13），所以应该按频次归一，而不是取平均。', status: 'completed', detail: {} },
]
const OTHER_EVENTS = [
  { id: 'e-1', kind: 'other', title: '读取 ui/src/styles/main.css', status: 'completed', detail: { text: '1313 行 · 规则块 503 · distinct 选择器 408' } },
  { id: 'e-2', kind: 'other', title: '运行 audit 建立基线', status: 'completed', detail: {} },
  { id: 'e-3', kind: 'other', title: '替换 42 处颜色字面量', status: 'in_progress', detail: {} },
]
const RUN_EVENTS = {
  'r-done': [...THINK_EVENTS, ...OTHER_EVENTS],
  'r-run': [...THINK_EVENTS, ...OTHER_EVENTS],
  'r-fail': [...THINK_EVENTS, ...OTHER_EVENTS],
}

const CASES = [
  ['用户消息 · 短', user('把这个页面的圆角统一一下。')],
  ['用户消息 · 超过 7 行（出现「显示更多」）', user(LONG_USER)],
  ['助手消息 · Markdown + 代码块', agent([{ kind: 'text', text: MARKDOWN }])],
  ['执行记录 · 折叠（已完成）', agent([{ kind: 'run_activity', activity: { run_id: 'r-done', status: 'completed', started_at: new Date(T).toISOString(), finished_at: new Date(T + 74000).toISOString() } }])],
  ['执行记录 · 运行中（默认展开 + 计时）', agent([{ kind: 'run_activity', activity: { run_id: 'r-run', status: 'running', started_at: RUNNING_START, finished_at: null } }])],
  ['执行记录 · 失败（默认展开）', agent([{ kind: 'run_activity', activity: { run_id: 'r-fail', status: 'failed', started_at: new Date(T).toISOString(), finished_at: FAILED_END, error: '上游超时' } }])],
  ['执行记录 · 深度思考展开（点名展开，夹具里没有点击，靠挂载后补一次）', agent([{ kind: 'run_activity', activity: { run_id: 'r-run', status: 'running', started_at: RUNNING_START, finished_at: null } }])],
  ['清单 · 部分完成（4 项）', agent([{ kind: 'todo', todos: TODOS }])],
  ['清单 · 全部完成', agent([{ kind: 'todo', todos: TODOS.map((t) => ({ ...t, status: 'completed' })) }])],
  ['方案 · 待确认（三个动作按钮）', agent([{ kind: 'proposal', status: 'pending', plan_id: 'p-1', version: 2, plan_text: MARKDOWN, source_prompt: '重构前端' }])],
  ['方案 · 已批准', agent([{ kind: 'proposal', status: 'approved', plan_id: 'p-2', version: 1, plan_text: '按计划实施。' }])],
  ['方案 · 已拒绝', agent([{ kind: 'proposal', status: 'rejected', plan_id: 'p-3', version: 1, plan_text: '范围过大，先不做。' }])],
  ['人工介入 · 待答复（选项 + 输入框）', agent([{ kind: 'intervention', intervention_id: 'i-1', status: 'pending', reason: '需要确认删除范围', question: '要一并删除关联的会话记录吗？', options: ['仅删除项目', '连同会话一起删除'] }])],
  ['人工介入 · 正在恢复', agent([{ kind: 'intervention', intervention_id: 'i-2', status: 'resuming', reason: '需要确认删除范围', question: '要一并删除关联的会话记录吗？' }])],
  ['人工介入 · 已答复', agent([{ kind: 'intervention', intervention_id: 'i-3', status: 'answered', reason: '需要确认删除范围', question: '要一并删除关联的会话记录吗？' }])],
  ['错误块 · 与正文共存', agent([{ kind: 'text', text: '输出到这里中断了。' }, { kind: 'error', text: '请求失败：HTTP 502 Bad Gateway' }])],
  ['错误块 · 单独出现', agent([{ kind: 'error', text: '请求失败：HTTP 500' }])],
]

// `?cell=N` 只渲染第 N 个用例（1:1、单列），用于把某一格截成大图。
// 注意只能带一个查询参数：capture.mjs 会把 URL 交给 shell，`&` 在那里是命令分隔符。
const cellParam = new URLSearchParams(window.location.search).get('cell')
const shown = cellParam === null ? CASES : [CASES[Number(cellParam)]].filter(Boolean)
if (cellParam !== null) document.documentElement.style.setProperty('--cols', '1')

createApp({
  render: () => h('div', { class: 'grid' }, shown.map(([label, message]) => h('div', { class: 'cell' }, [
    h('p', { class: 'cell-label' }, label),
    h(ChatMessage, { message, disabled: false, runActivityEvents: RUN_EVENTS, runActivityLoading: {} }),
  ]))),
}).mount('#app')

// 「深度思考」默认收起，而截图没法点。挂载后给点名要看的那一格补一次点击。
// 用 setTimeout(0) 是因为 capture.mjs 会先等 budget 再截，晚一帧没有任何风险。
window.setTimeout(() => {
  document.querySelectorAll('.cell').forEach((cell) => {
    if (!cell.querySelector('.cell-label')?.textContent.includes('深度思考展开')) return
    cell.querySelector('.think-toggle')?.click()
  })
}, 0)
