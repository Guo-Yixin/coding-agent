// 侧栏状态预览 + 键盘可达性检查。
//
// 为什么需要这张夹具：侧栏里大多数「控件」是 div/span，能不能被键盘够到无法靠读代码确定
// （浏览器对 <button> 内部的可聚焦内容、role=button 的 span 处理并不一致），
// 必须在真实浏览器里 el.focus() 之后看 document.activeElement 才算数。
//
// 用法：node scripts/capture.mjs http://127.0.0.1:3000/preview/sidebar.html shots --widths 1320 --height 760 --budget 6000 --name vitals
//
// 注意：probe() 会先 el.focus() 再读计算样式，所以表里的背景/边框是**聚焦态**的值。
// 这是刻意的 —— 这张表要回答的是"聚焦时看得见吗"，顺带量的尺寸/圆角/字号不受聚焦影响。
import { createApp, h } from 'vue'

import '/src/styles/tokens.css'
import '/src/styles/main.css'
import SessionSidebar from '/src/components/SessionSidebar.vue'

const projects = [
  {
    id: 'p1',
    name: '产品官网重构',
    provider: 'github',
    repo: 'https://github.com/example/site.git',
    repoFullName: 'example/site',
    legacy: false,
    conversations: [
      { id: 't1', title: '重构首页 Hero 区', status: 'finished', updatedAt: 5 },
      { id: 't2', title: '把配色收敛到 token', status: 'running', updatedAt: 4 },
      { id: 't3', title: '修掉移动端抽屉遮挡', status: 'idle', updatedAt: 3 },
      { id: 't4', title: '第四个会话（触发展开）', status: 'error', updatedAt: 2 },
    ],
  },
  {
    id: 'p2',
    name: 'gitee 测试仓库',
    provider: 'gitee',
    repo: 'https://gitee.com/example/test.git',
    repoFullName: 'example/test',
    legacy: true,
    conversations: [{ id: 't5', title: '只做并发验证', status: 'idle', updatedAt: 1 }],
  },
  {
    id: 'p3',
    name: '空项目（无会话）',
    provider: 'github',
    repo: 'https://github.com/example/empty.git',
    repoFullName: 'example/empty',
    legacy: false,
    conversations: [],
  },
]

const standaloneThreads = [
  { id: 's1', title: '普通聊天：解释一下 SSE', status: 'finished', updatedAt: 6 },
]

const shared = {
  projects,
  standaloneThreads,
  activeId: 't2',
  collapsedProjectIds: [],
}

createApp({ render: () => h(SessionSidebar, shared) }).mount('#expanded')
createApp({ render: () => h(SessionSidebar, { ...shared, collapsed: true }) }).mount('#collapsed')

// ---------- 键盘可达性检查 ----------
// 判据：一个「看起来可以操作」的东西，如果不能通过 el.focus() 成为 activeElement，
// 键盘用户就永远够不到它。
const CANDIDATES = [
  ['.sidebar-toggle', '折叠/展开侧栏'],
  ['.new-chat-button', '新聊天'],
  ['.new-project-button', '新建项目'],
  ['.rail-action', '收起态：图标按钮'],
  ['.thread-item', '会话行'],
  ['.thread-delete', '删除会话'],
  ['.project-disclosure', '折叠项目'],
  ['.project-add-thread', '在项目内新建会话'],
  ['.project-menu-trigger', '项目菜单'],
  ['.show-more-button', '展开更多会话'],
  ['.project-no-conversations button', '空项目里的新建'],
  ['.rail-session', '收起态：会话快捷入口'],
]

function probe(selector) {
  const el = document.querySelector(selector)
  if (!el) return { status: 'skip', detail: '当前形态下不存在' }

  const tag = el.tagName.toLowerCase()
  const role = el.getAttribute('role')
  const before = document.activeElement
  el.focus()
  const focusable = document.activeElement === el
  if (before && before !== document.body) before.blur?.()

  // <button> 内部不允许再放可交互内容（HTML 规范），浏览器对内层元素的可聚焦性处理不一致
  const interactiveAncestor = el.closest('button, a[href]')
  const nested = interactiveAncestor && interactiveAncestor !== el && el.matches('[role="button"], button, a[href]')

  // 量一遍视觉体征：用来判断它到底是「按钮」还是「图标」还是「列表行」。
  // 这三个的迁移路径完全不同，靠肉眼在截图里分不准确。
  const cs = getComputedStyle(el)
  const r = el.getBoundingClientRect()
  const cs0 = getComputedStyle(el, '::before')

  return {
    status: focusable ? 'ok' : 'bad',
    tag,
    role: role || '',
    nested: Boolean(nested),
    ancestor: nested ? `${interactiveAncestor.tagName.toLowerCase()}.${interactiveAncestor.className.split(' ')[0]}` : '',
    detail: focusable
      ? '可聚焦'
      : `无法聚焦（activeElement 仍是 ${document.activeElement?.tagName.toLowerCase() || 'null'}）`,
    size: `${Math.round(r.width)}×${Math.round(r.height)}`,
    box: `${cs.borderTopWidth} ${cs.borderStyle} / ${cs.borderTopLeftRadius}`,
    bg: cs.backgroundColor,
    font: cs.fontSize,
    before: cs0.content && cs0.content !== 'none' ? '有伪元素' : '',
  }
}

const rows = CANDIDATES.map(([selector, label]) => [selector, label, probe(selector)])
const bad = rows.filter(([, , r]) => r.status === 'bad')

document.querySelector('#report').innerHTML = `
  <h2>侧栏控件体征 · ${rows.length - bad.length} / ${rows.length} 可聚焦${
    bad.length ? ` —— <span style="color:#b85c5c">${bad.length} 个够不到</span>` : ''
  }</h2>
  <table>
    <thead><tr><th>选择器</th><th>元素 / role</th><th>尺寸</th><th>边框 / 圆角</th><th>背景</th><th>字号</th><th>结果</th><th>嵌套</th></tr></thead>
    <tbody>
      ${rows.map(([selector, label, r]) => `
        <tr class="${r.status === 'bad' || r.nested ? 'bad' : ''}">
          <td><code>${selector}</code><br /><span style="color:#6b6b6b">${label}</span></td>
          <td>&lt;${r.tag || '—'}&gt; ${r.role ? `role=${r.role}` : ''}</td>
          <td>${r.size || '—'}</td>
          <td>${r.box || '—'}</td>
          <td>${r.bg || '—'}</td>
          <td>${r.font || '—'}</td>
          <td>${r.status === 'skip' ? '—' : (r.status === 'ok' ? '✅ ' : '❌ ') + r.detail}</td>
          <td>${r.nested ? `⚠️ 在 <code>${r.ancestor}</code> 内` : '否'}</td>
        </tr>`).join('')}
    </tbody>
  </table>
`
