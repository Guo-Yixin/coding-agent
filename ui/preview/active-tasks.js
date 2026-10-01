// ActiveTaskStrip 的 1:1 放大夹具。
//
// 为什么单独建这一个：这个组件在外层 <nav> 上没有 v-if 之外的任何依赖，
// 可以脱离整个应用单独挂载，于是能用 capture.mjs 的 --scale 3 放三倍看点击区与间距。
// 整屏夹具做不到这件事（1440×900 放三倍会超出图片尺寸上限）。
//
// 挂两遍：一遍是四个真实任务（覆盖 running / queued / cancelling 与超长标题），
// 一遍是空数组 —— 用来确认「没有任务时整条不渲染」不是靠猜测。
//
// 用法：
//   node scripts/capture.mjs http://127.0.0.1:3000/preview/active-tasks.html tmp/at --widths 740 --height 260 --scale 3 --budget 5000 --name tasks
import { createApp, h } from 'vue'

import '/src/styles/tokens.css'
import '/src/styles/main.css'
import ActiveTaskStrip from '/src/components/ActiveTaskStrip.vue'

const CHAT = {
  projectId: null,
  chatOnly: true,
  repo: '',
  provider: 'github',
  branch: '',
  baseBranch: '',
  model: 'deepseek-flash',
  effort: 'default',
  createdAt: 1,
  updatedAt: 1,
  draftContent: '',
  messages: [],
  changedFiles: [],
}

const TASKS = [
  { ...CHAT, id: 't-run1', title: '实现并验证 FastAPI Task API', repoFullName: 'example/api', status: 'running', runId: 'r1' },
  { ...CHAT, id: 't-run2', title: '重构首页 Hero 区', repoFullName: 'example/site', status: 'queued', runId: 'r2' },
  { ...CHAT, id: 't-run3', title: '把配色收敛到 token', repoFullName: 'example/web', status: 'cancelling', runId: 'r3' },
  // 刻意不给 runId：thread.status 说在跑，但本地没有 run → 取消键不渲染。
  { ...CHAT, id: 't-run4', title: '一个非常长的任务标题用来验证省略号到底有没有生效', repoFullName: 'example/long', status: 'running', runId: null },
]

function Row({ label, tasks, activeId }) {
  return h('section', { style: 'margin-bottom:22px' }, [
    h('p', { style: 'margin:0 0 6px;font-size:11px;letter-spacing:.06em;color:var(--c-text-muted)' }, label),
    h(ActiveTaskStrip, { tasks, activeId }),
  ])
}

createApp({
  render: () =>
    h('div', [
      h(Row, { label: '① 四个任务 · 三种状态 · 第二个不选中', tasks: TASKS, activeId: 't-run2' }),
      h(Row, { label: '② 空数组 —— 整条应当不渲染（下面什么都不该出现）', tasks: [], activeId: null }),
    ]),
}).mount('#app')
