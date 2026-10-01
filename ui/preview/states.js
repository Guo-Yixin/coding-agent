// 主区状态矩阵预览。
//
// 为什么必须有这张夹具：主区的空态（Hero）三变体、加载态、错误态里，有一部分在真实应用里
// **够不到** —— 只要账号下还有任何会话，`agent.currentThread` 就不为空，"无会话 Hero"那一屏
// 永远不会再出现。而它恰好是新用户的第一个屏幕。靠手工点不出来，只能种状态渲染。
//
// 用法：
//   node scripts/capture.mjs http://127.0.0.1:3000/preview/states.html shots --widths 920 --height 2900 --budget 8000 --name states
//
// 每个面板用独立的 Pinia 实例，互不干扰；bootstrap / refreshActiveRuns 换成空实现，
// 否则夹具会去打真实接口并启动 3 秒轮询。
import { createApp } from 'vue'
import { createPinia, setActivePinia } from 'pinia'

import '/src/styles/tokens.css'
import '/src/styles/main.css'
import AgentWorkspace from '/src/components/AgentWorkspace.vue'
import { useAgentStore } from '/src/stores/agent'

const CHAT_THREAD = {
  id: 't-chat',
  projectId: null,
  chatOnly: true,
  title: '会话标题',
  repo: '',
  repoFullName: '',
  provider: 'github',
  branch: '',
  baseBranch: '',
  model: 'deepseek-flash',
  effort: 'default',
  status: 'idle',
  createdAt: 1,
  updatedAt: 1,
  draftContent: '',
  messages: [],
  changedFiles: [],
}

const PROJECT_THREAD = { ...CHAT_THREAD, id: 't-proj', projectId: 'p1', chatOnly: false, repoFullName: 'example/app', title: '准备好继续构建' }

const PROJECT = {
  id: 'p1',
  name: '开发工作台',
  provider: 'github',
  repo: 'https://github.com/example/app.git',
  repoFullName: 'example/app',
  legacy: false,
  conversations: [{ id: 't-proj', title: '标题', status: 'idle', updatedAt: 1 }],
}

// 活跃任务条的候选。字段要与 `stores/agent.js` 的 `activeTasks` getter 对得上：
// 它把 `threads` 里 status ∈ queued/running/cancelling（或本地 activeRuns 有条目）的挑出来，
// 再用 `activeRuns[id]` 覆盖 status 与 runId。
const RUNNING_TASKS = [
  { ...CHAT_THREAD, id: 't-run1', projectId: 'p1', chatOnly: false, title: '实现并验证 FastAPI Task API', repoFullName: 'example/api', status: 'running' },
  { ...CHAT_THREAD, id: 't-run2', projectId: 'p2', chatOnly: false, title: '重构首页 Hero 区', repoFullName: 'example/site', status: 'queued' },
  { ...CHAT_THREAD, id: 't-run3', projectId: 'p3', chatOnly: false, title: '把配色收敛到 token', repoFullName: 'example/web', status: 'cancelling' },
  { ...CHAT_THREAD, id: 't-run4', projectId: 'p4', chatOnly: false, title: '一个非常长的任务标题用来验证省略号到底有没有生效', repoFullName: 'example/long', status: 'running' },
]

const STATES = [
  { title: '① 无会话（新用户第一屏）', state: { currentThread: null } },
  { title: '② 普通聊天空态', state: { currentThread: CHAT_THREAD } },
  { title: '③ 项目会话空态', state: { currentThread: PROJECT_THREAD, projects: [PROJECT] } },
  {
    title: '④ 加载态',
    state: { currentThread: CHAT_THREAD, loading: true },
  },
  {
    title: '⑤ 错误态（有消息时）',
    state: {
      currentThread: CHAT_THREAD,
      error: '创建聊天失败：HTTP 500',
      messages: [
        { id: 'm1', author: 'user', timestamp: 1, chunks: [{ kind: 'text', text: '帮我看看这个仓库的结构' }] },
      ],
    },
  },
  {
    title: '⑥ 正常态（有消息）',
    state: {
      currentThread: CHAT_THREAD,
      messages: [
        { id: 'm1', author: 'user', timestamp: 1, chunks: [{ kind: 'text', text: '帮我看看这个仓库的结构' }] },
        {
          id: 'm2',
          author: 'agent',
          timestamp: 2,
          chunks: [{ kind: 'text', text: '仓库分成前端与后端两块，前端在 `ui/`，后端是 FastAPI 服务。需要我先看哪一块？' }],
        },
      ],
    },
  },
  {
    // 活跃任务条只在有正在运行的任务时出现 —— 默认截图里永远拍不到。
    // 四个任务刻意覆盖三种状态 + 一个超长标题 + 一个"服务端说在跑但本地没有 runId"的边界。
    title: '⑦ 活跃任务条（4 个任务 · 三种状态）',
    state: {
      currentThread: RUNNING_TASKS[0],
      threads: RUNNING_TASKS,
      activeRuns: {
        't-run1': { status: 'running', runId: 'r1' },
        't-run2': { status: 'queued', runId: 'r2' },
        't-run3': { status: 'cancelling', runId: 'r3' },
        // t-run4 刻意不在 activeRuns 里：thread.status 说在跑，但本地没有 runId →
        // 取消按钮不渲染。这是服务端状态与本地状态不一致时的真实边界。
      },
    },
  },
]

// 支持 ?cell=<序号> 只放大看一格（1 倍、单格）；不加参数就是整张矩阵（0.62 倍）。
// 刻意只用**一个**查询参数：capture.mjs 会把 URL 交给 shell，`&` 在那里是命令分隔符，
// 写成 `?only=0&scale=1` 会被 cmd 拆开并报 "'scale' is not recognized"。
const params = new URLSearchParams(location.search)
const only = params.has('cell') ? Number(params.get('cell')) : null
const scale = only === null ? 0.62 : 1

const sheet = document.getElementById('sheet')
sheet.style.setProperty('--scale', String(scale))
document.documentElement.style.setProperty('--box-w', `${Math.round(1440 * scale)}px`)
document.documentElement.style.setProperty('--box-h', `${Math.round(900 * scale)}px`)

for (const [index, { title, state }] of STATES.entries()) {
  if (only !== null && index !== only) continue
  const cell = document.createElement('div')
  cell.className = 'cell'
  const heading = document.createElement('h3')
  heading.textContent = title
  const box = document.createElement('div')
  box.className = 'box'
  const panel = document.createElement('div')
  panel.className = 'panel'
  box.appendChild(panel)
  cell.append(heading, box)
  sheet.appendChild(cell)

  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useAgentStore()
  store.$patch({
    options: { models: [{ id: 'deepseek-flash', label: 'deepseek-flash' }], providers: [{ id: 'github', label: 'GitHub' }] },
    selectedModel: 'deepseek-flash',
    ...state,
  })
  // 夹具不碰网络，也不启动轮询。
  store.bootstrap = async () => {}
  store.refreshActiveRuns = async () => {}

  const app = createApp(AgentWorkspace)
  app.use(pinia)
  app.mount(panel)
}
