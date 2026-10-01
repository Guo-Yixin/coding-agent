// 状态预览夹具：在同一页里挂载组件的各个状态/形态，用 capture.mjs 一张截图看全。
// 用法：node scripts/capture.mjs http://127.0.0.1:3000/preview/dialogs.html shots --widths 1560 --height 700 --name dialogs
import { createApp, h } from 'vue'

import '/src/styles/tokens.css'
import '/src/styles/main.css'
import CreateProjectDialog from '/src/components/CreateProjectDialog.vue'
import ConfirmProjectDeleteDialog from '/src/components/ConfirmProjectDeleteDialog.vue'

const project = {
  id: 'project-1',
  name: '产品官网重构',
  provider: 'github',
  repo: 'https://github.com/example/app.git',
  repoFullName: 'example/app',
  conversations: [{ id: 't1' }, { id: 't2' }, { id: 't3' }],
}

createApp({
  render: () => h('div', { class: 'grid' }, [
    h(CreateProjectDialog),                        // 新建：空态
    h(CreateProjectDialog, { project }),           // 重命名：已有仓库绑定
    h(ConfirmProjectDeleteDialog, { project }),    // 删除：确认按钮禁用态
  ]),
}).mount('#app')
