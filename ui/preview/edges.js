// 边界态矩阵预览 + 横向溢出自动探测。
//
// 为什么必须有这张夹具：DESIGN.md §6 的「边界态」那一列，全都是**正常数据下不会出现**的输入 ——
// 超长标题、超长仓库名、200 字符宽的代码行、300 字符不换行的 URL。手工点不出来，只能种数据渲染。
//
// 它比状态矩阵多做一件事：**每格跑一次横向溢出探测**，把「有没有元素跑到 1440 视口之外」
// 变成一句可读的结论放进截图里。因为「内容被切掉」和「整页出现横向滚动条」这两种症状，
// 在缩小的拼版图上是看不出来的 —— 必须量。
//
// 用法：
//   node scripts/capture.mjs http://127.0.0.1:3000/preview/edges.html tmp/ed --widths 1500 --height 6500 --budget 9000 --name edges
//   node scripts/capture.mjs "http://127.0.0.1:3000/preview/edges.html?cell=0" tmp/ed --widths 1500 --height 1150 --budget 6000 --name e0
//
// 与 states.js 一样：每格独立 Pinia，bootstrap / refreshActiveRuns 换成空实现，否则会真打接口。
import { createApp, nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'

import '/src/styles/tokens.css'
import '/src/styles/main.css'
import AgentWorkspace from '/src/components/AgentWorkspace.vue'
import { useAgentStore } from '/src/stores/agent'

const CHAT_THREAD = {
  id: 't-chat', projectId: null, chatOnly: true, title: '会话标题',
  repo: '', repoFullName: '', provider: 'github', branch: '', baseBranch: '',
  model: 'deepseek-flash', effort: 'default', status: 'idle',
  createdAt: 1, updatedAt: 1, draftContent: '', messages: [], changedFiles: [],
}

const msg = (id, author, chunks) => ({ id, author, timestamp: 1, chunks })

const LOADING = [
  { title: '① 极长消息 · 不换行 URL / 超宽代码行 / 超宽表格', note: '三个都塞进同一条助手消息里，一次看全。期望：气泡内自己横向滚动，视口不被撑破。' },
  { title: '② 超长标题 · 无空格的 120 字符', note: '标题里没有空格，浏览器没有任何可断行的地方。期望：省略号，且不撑破 Header。' },
  { title: '③ 侧栏 · 超长项目名与会话名', note: '60 字项目名 + 80 字会话标题，都不含空格。' },
  { title: '④ 运行轨迹 · 超长日志行', note: 'todo 文本与 event detail 都是不含空格的超长串。' },
  { title: '⑤ 弹窗 · 超长输入', note: '仓库地址没有 maxlength，塞一个 260 字符的 URL；项目名用满 maxlength=80。' },
  { title: '⑥ 加载失败 · 侧栏与主区', note: 'projects 加载抛错、threads 加载抛错。这格不是几何问题，是「有没有出路」的问题。' },
]

// 不含空格的长串：不给浏览器任何断行机会，能用来看截断/滚动是否真的生效。
const LONG_WORD = 'SuperCalifragilisticExpialidociousAndThenSomeMoreLettersToMakeItDefinitelyTooLong'
const LONG_PATH = 'src/components/deeply/nested/directory/structure/with/a/very/long/file/name/that/keeps/going/and/going/and/going/and/going/and/going/and/going/Component.vue'
const LONG_URL = 'https://github.com/' + 'very-long-organization-name/'.repeat(4) + 'repository-with-an-absurdly-long-name/blob/main/' + LONG_PATH
const WIDE_CODE = `const result = await audit.run('${LONG_PATH}', { ignore: ['tokens.css'], report: 'json' }) // ${LONG_WORD}`
const WIDE_TABLE_HEAD = '| 区域 | 空态 | 加载态 | 正常态 | 错误态 | 边界态 |'
const WIDE_TABLE_DIV = '|---|---|---|---|---|---|'

const LONG_URL_MESSAGE = {
  kind: 'text',
  text: [
    '这是一个不换行的超长 URL，用来验横向溢出：',
    LONG_URL,
    '',
    '下面是一个 200 字符宽的代码行：',
    '```js',
    WIDE_CODE,
    '```',
    '',
    '下面是一个宽表格：',
    WIDE_TABLE_HEAD,
    WIDE_TABLE_DIV,
    '| 侧栏 · 项目列表 | ✅ 无项目引导 | ⬜ 无骨架屏 | ✅ 分组树 | ⬜ 加载失败无重试 | ✅ 展开显示其余 N 个 |',
    '| 主区 · 内容 | ✅ Hero 三变体 | ✅ spinner | ✅ 消息列表 | ✅ 错误横幅 | ⬜ 极长消息溢出 |',
  ].join('\n'),
}

const LONG_TITLE = '这是一个完全不包含任何空格的一百二十个字符长的会话标题用来验证省略号与头部布局在极端输入下到底会发生什么情况请仔细观察右侧的标题区域是否被撑破或者把状态徽章挤走'

const EDGES = [
  {
    title: LOADING[0].title, note: LOADING[0].note,
    state: { currentThread: CHAT_THREAD, messages: [msg('m1', 'agent', [LONG_URL_MESSAGE])] },
  },
  {
    title: LOADING[1].title, note: LOADING[1].note,
    state: { currentThread: { ...CHAT_THREAD, title: LONG_TITLE }, messages: [] },
  },
  {
    title: LOADING[2].title, note: LOADING[2].note,
    state: {
      currentThread: null,
      projects: [{
        id: 'p1',
        name: LONG_WORD + ' ' + LONG_WORD,
        provider: 'github',
        repo: 'https://github.com/example/app.git',
        repoFullName: LONG_WORD + '/' + LONG_WORD,
        legacy: false,
        conversations: [
          { id: 't1', title: LONG_TITLE, status: 'idle', updatedAt: 5 },
          { id: 't2', title: LONG_WORD, status: 'running', updatedAt: 4 },
          { id: 't3', title: '短标题', status: 'idle', updatedAt: 3 },
        ],
      }],
    },
  },
  {
    title: LOADING[3].title, note: LOADING[3].note,
    state: {
      currentThread: CHAT_THREAD,
      messages: [msg('m1', 'agent', [
        { kind: 'todo', todos: [
          { content: '把 ' + LONG_PATH + ' 里的字面量收敛到 token', status: 'completed' },
          { content: LONG_WORD + LONG_WORD, status: 'in_progress' },
          { content: '重跑 audit 并核对分数', status: 'pending' },
        ] },
        { kind: 'run_activity', activity: { run_id: 'r1', status: 'completed', started_at: new Date(Date.now() - 74000).toISOString(), finished_at: new Date().toISOString(), error: '' } },
      ])],
    },
  },
  {
    // 弹窗不是挂在 AgentWorkspace 里的，这格单独处理（见下面 mountDialog）。
    title: LOADING[4].title, note: LOADING[4].note, dialog: true,
    state: {},
  },
  {
    title: LOADING[5].title, note: LOADING[5].note,
    state: {
      currentThread: null,
      projects: [],
      // 关键：`projectsError` 有值才走「没读到」那一屏；没有它就等于「你确实没有项目」。
      projectsError: '加载项目列表失败：HTTP 503',
      error: '加载项目列表失败：HTTP 503',
    },
  },
  {
    title: '⑦ 侧栏加载中 · 三种「空」的第三种',
    note: 'projects 同样为空，但这次是「还在读」。期望：spinner + 正在加载项目…，而不是「创建第一个项目」。',
    state: { currentThread: null, projects: [], projectsLoading: true, loading: true },
  },
]

// —— 探测 ———————————————————————————————————————————————————————————————
//
// 只问一个问题：有没有元素的边界跑到 .panel 的 1440×900 之外（横向）。
// 纵向不算：主区本来就是可滚动的，内容比 900 高是正常的。
//
// 两条必须的排除规则，否则报告里全是假阳性：
//   1. **被祖先裁剪的不算**。`pre { overflow-x: auto }` 里的 `<code>` 天然比视口宽，
//      但它是被 `pre` 裁掉并可滚动的 —— 用户看不到任何越界。只有一路上到 panel
//      都没有 `overflow-x: visible` 以外的祖先时，才算真的漏出来。
//   2. **只保留最内层**。一个子元素跑出去，它的所有祖先也会被判违规。
function clippedByAncestor(el, panel) {
  let node = el.parentElement
  while (node && node !== panel) {
    if (getComputedStyle(node).overflowX !== 'visible') return true
    node = node.parentElement
  }
  return false
}

function probe(panel) {
  const hostRect = panel.getBoundingClientRect()
  const scale = hostRect.width / 1440 || 1
  const all = []
  for (const el of panel.querySelectorAll('*')) {
    const r = el.getBoundingClientRect()
    if (r.width === 0 && r.height === 0) continue
    const overRight = (r.right - hostRect.right) / scale
    const overLeft = (hostRect.left - r.left) / scale
    if (overRight <= 1 && overLeft <= 1) continue
    if (clippedByAncestor(el, panel)) continue
    all.push({ el, overRight, overLeft })
  }
  const inner = all.filter(({ el }) => !all.some((other) => other.el !== el && el.contains(other.el)))
  return inner.map(({ el, overRight, overLeft }) => ({
    tag: el.tagName.toLowerCase(),
    cls: typeof el.className === 'string' && el.className ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.') : '',
    text: (el.textContent || '').trim().slice(0, 34),
    over: Math.max(overRight, overLeft),
    side: overRight > overLeft ? '右' : '左',
  }))
}

// 第二条判据：**文字越过了自己所在的那张卡片**。
//
// 第一条判据（越界视口）会被外面的滚动容器兜住 —— 上层的 `overflow: hidden` 一裁，
// 「越界视口」就不报了，可用户看到的是**一行文字从卡片边框里穿出去、然后在别处被切断**。
// 所以还要问第二个问题：这段文字有没有跑出它最近的那个「有边框或有底色」的祖先？
//
// 只看叶子文本节点，避免整棵树互相包含造成噪声。
function visualContainer(el, panel) {
  let node = el.parentElement
  while (node && node !== panel) {
    const cs = getComputedStyle(node)
    const bg = cs.backgroundColor
    const hasBg = bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent'
    const bw = ['borderLeftWidth', 'borderRightWidth', 'borderTopWidth', 'borderBottomWidth']
      .reduce((sum, k) => sum + (parseFloat(cs[k]) || 0), 0)
    if (hasBg || bw > 0) return { node, cs }
    node = node.parentElement
  }
  return null
}

function escapesContainer(panel) {
  const hostRect = panel.getBoundingClientRect()
  const scale = hostRect.width / 1440 || 1
  const bad = []
  for (const el of panel.querySelectorAll('*')) {
    if (el.childElementCount !== 0) continue
    if (!(el.textContent || '').trim()) continue
    // <option> 不是被正常排版出来的盒子（它由 select 自己绘制），拿它的 rect 去比必然误报。
    if (['OPTION', 'OPTGROUP', 'SELECT'].includes(el.tagName)) continue
    const own = getComputedStyle(el)
    if (own.position === 'absolute' || own.position === 'fixed') continue
    const container = visualContainer(el, panel)
    if (!container) continue
    const cr = container.node.getBoundingClientRect()
    const c = container.cs
    // 容器的 padding box = 边框盒减去四边边框宽度
    const box = {
      left: cr.left + (parseFloat(c.borderLeftWidth) || 0),
      right: cr.right - (parseFloat(c.borderRightWidth) || 0),
    }
    const r = el.getBoundingClientRect()
    const overRight = (r.right - box.right) / scale
    const overLeft = (box.left - r.left) / scale
    if (overRight <= 1 && overLeft <= 1) continue
    bad.push({
      ok: false,
      verdict: '文字越过卡片',
      where: `${el.tagName.toLowerCase()}${typeof el.className === 'string' && el.className ? '.' + el.className.trim().split(/\s+/)[0] : ''} 越出 ${container.node.tagName.toLowerCase()}${typeof container.node.className === 'string' && container.node.className ? '.' + container.node.className.trim().split(/\s+/)[0] : ''}`,
      detail: `${overRight > overLeft ? '右侧' : '左侧'}越出 ${Math.max(overRight, overLeft).toFixed(0)}px（未换行）· ${(el.textContent || '').trim().slice(0, 24)}`,
    })
  }
  return bad
}

function describe(v) {
  return `${v.tag}${v.cls}`
}

function renderReport(cell, violations, extra = []) {
  const table = document.createElement('table')
  table.className = 'report'
  table.innerHTML = '<thead><tr><th>判定</th><th>元素</th><th>越界</th><th>内容开头</th></tr></thead>'
  const tbody = document.createElement('tbody')
  for (const v of violations) {
    const tr = document.createElement('tr')
    tr.className = 'bad'
    tr.innerHTML = `<td class="verdict">✗ 越界 ${v.over.toFixed(0)}px（${v.side}）</td><td>${describe(v)}</td><td>${v.over.toFixed(0)}px</td><td>${v.text.replace(/</g, '&lt;')}</td>`
    tbody.appendChild(tr)
  }
  for (const e of extra) {
    const tr = document.createElement('tr')
    tr.className = e.ok ? 'ok' : 'bad'
    tr.innerHTML = `<td class="verdict">${e.ok ? '✓' : '✗'} ${e.verdict}</td><td>${e.where}</td><td>—</td><td>${e.detail}</td>`
    tbody.appendChild(tr)
  }
  if (!violations.length && !extra.length) {
    const tr = document.createElement('tr')
    tr.className = 'ok'
    tr.innerHTML = '<td class="verdict">✓ 没有元素越界</td><td>—</td><td>—</td><td>1440 视口内一切内容都被正确约束</td>'
    tbody.appendChild(tr)
  }
  table.appendChild(tbody)
  cell.appendChild(table)

  const bad = violations.length + extra.filter((e) => !e.ok).length
  const line = document.createElement('p')
  line.className = 'summary'
  line.textContent = bad ? `本格结论：${bad} 项越界` : '本格结论：无横向越界'
  cell.appendChild(line)
}

// —— 额外探针（几何说不清、但必须回答的问题）———————————————————————————————
function extraProbes(panel) {
  const out = []

  // 标题是否真的省略号了
  const h1 = panel.querySelector('.workspace-header h1')
  if (h1) {
    const cs = getComputedStyle(h1)
    const clipped = h1.scrollWidth > h1.clientWidth + 1
    out.push({
      ok: cs.textOverflow === 'ellipsis' || !clipped,
      verdict: '超长标题',
      where: '.workspace-header h1',
      detail: `text-overflow=${cs.textOverflow} · overflow=${cs.overflowX} · 被裁=${clipped ? '是' : '否'}`,
    })
  }

  // 侧栏项目名 / 会话名
  for (const [sel, label] of [['.project-heading-main strong', '侧栏项目名'], ['.thread-title', '侧栏会话名'], ['.project-heading-main small', '侧栏仓库名']]) {
    const el = panel.querySelector(sel)
    if (!el) continue
    const cs = getComputedStyle(el)
    const clipped = el.scrollWidth > el.clientWidth + 1
    out.push({
      ok: cs.textOverflow === 'ellipsis' || !clipped,
      verdict: label,
      where: sel,
      detail: `text-overflow=${cs.textOverflow} · display=${cs.display} · overflow=${cs.overflowX} · 被裁=${clipped ? '是' : '否'}`,
    })
  }

  // 代码块是不是在气泡内自己滚
  const pre = panel.querySelector('.message-body pre, pre')
  if (pre) {
    const cs = getComputedStyle(pre)
    out.push({
      ok: cs.overflowX === 'auto' || cs.overflowX === 'scroll',
      verdict: '代码块横向滚动',
      where: 'pre',
      detail: `overflow-x=${cs.overflowX} · scrollWidth=${pre.scrollWidth} / clientWidth=${pre.clientWidth}`,
    })
  }
  return out
}

// 全应用范围的结构性检查：**写了 text-overflow: ellipsis 却用不到的**。
//
// `text-overflow` 只对「块级/行内块容器及其行内内容」生效。一旦元素是 flex / grid 容器，
// 它的文本会变成匿名 flex/grid 项，省略号**永远不会出现** —— 外观上表现为
// 「文字被硬生生切断、没有任何提示」。这类错误在代码里看不出来（三件套写得很齐全），
// 只有在长内容真的渲染出来时才暴露，所以值得单独做成一条静态判据。
function ellipsisOnFlexContainer(panel) {
  const bad = []
  for (const el of panel.querySelectorAll('*')) {
    const cs = getComputedStyle(el)
    if (cs.textOverflow !== 'ellipsis') continue
    if (!['flex', 'inline-flex', 'grid', 'inline-grid'].includes(cs.display)) continue
    if (el.scrollWidth <= el.clientWidth + 1) continue // 内容没超，暂时看不出问题
    bad.push({
      ok: false,
      verdict: '省略号用不到',
      where: `${el.tagName.toLowerCase()}${typeof el.className === 'string' && el.className ? '.' + el.className.trim().split(/\s+/)[0] : ''}`,
      detail: `display=${cs.display} 容器的 text-overflow 不生效 · 被硬切 · ${el.scrollWidth} / ${el.clientWidth}`,
    })
  }
  return bad
}

// —— 渲染 ———————————————————————————————————————————————————————————————
const params = new URLSearchParams(location.search)
const only = params.has('cell') ? Number(params.get('cell')) : null
const sheet = document.getElementById('sheet')

const CHROME = document.createElement('div')
const results = []

async function mountWorkspace(cell, panel, state) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useAgentStore()
  store.$patch({
    options: { models: [{ id: 'deepseek-flash', label: 'deepseek-flash' }], providers: [{ id: 'github', label: 'GitHub' }] },
    selectedModel: 'deepseek-flash',
    ...state,
  })
  store.bootstrap = async () => {}
  store.refreshActiveRuns = async () => {}
  const app = createApp(AgentWorkspace)
  app.use(pinia)
  app.mount(panel)
  return app
}

async function mountDialog(panel) {
  const { default: CreateProjectDialog } = await import('/src/components/CreateProjectDialog.vue')
  const app = createApp(CreateProjectDialog, { project: null })
  app.mount(panel)
  return app
}

for (const [index, edge] of EDGES.entries()) {
  if (only !== null && index !== only) continue
  const cell = document.createElement('div')
  cell.className = 'cell'
  const h3 = document.createElement('h3')
  h3.textContent = edge.title
  const note = document.createElement('p')
  note.className = 'note'
  note.textContent = edge.note
  const box = document.createElement('div')
  box.className = 'box'
  const panel = document.createElement('div')
  panel.className = 'panel'
  box.appendChild(panel)
  cell.append(h3, note, box)
  sheet.appendChild(cell)

  if (edge.dialog) {
    // 弹窗自带 .dialog-backdrop（position: fixed），塞进 1440×900 的盒子里正好等价于一屏。
    await mountDialog(panel)
    // 往两个输入框里灌超长内容
    await nextTick()
    const nameInput = panel.querySelector('#project-name')
    const repoInput = panel.querySelector('#project-repo')
    if (nameInput) nameInput.value = LONG_WORD.repeat(2).slice(0, 80)
    if (repoInput) repoInput.value = 'https://github.com/' + LONG_WORD + '/' + LONG_WORD + '.git'
    await nextTick()
  } else {
    await mountWorkspace(cell, panel, edge.state)
    await nextTick()
  }
  await nextTick()

  const violations = probe(panel)
  const extra = [...extraProbes(panel), ...ellipsisOnFlexContainer(panel), ...escapesContainer(panel)]
  renderReport(cell, violations, extra)
  results.push({ index, title: edge.title, violations, extra })
}

globalThis.__EDGE_REPORT__ = results
document.title = results.some((r) => r.violations.length || r.extra.some((e) => !e.ok))
  ? `边界态 · ${results.filter((r) => r.violations.length || r.extra.some((e) => !e.ok)).length} 格有越界`
  : '边界态 · 全部通过'
