import { createApp, h, ref } from 'vue'

import ChatComposer from '../src/components/ChatComposer.vue'
import '../src/styles/tokens.css'
import '../src/styles/main.css'

/*
 * 只用于开发期检视：把 ChatComposer 单独挂出来，1:1 看底栏。
 *
 * 为什么需要它：底栏里「模型选择器」和「仓库」曾经是同一个形态（1px 边框 +
 * radius-sm + --c-surface 底 + 30px 高），一个能点一个点不动。整屏截图里这一行
 * 只有几十像素高，看不清两者到底像不像；这个夹具给了 620px 宽的宿主和 4 种数据，
 * 配合 capture.mjs --scale 2 就能把底栏放大到能直接判断。
 */
const CASES = [
  { id: 'case-long', repo: 'Guo-Yixin/test-coding-repo-with-a-very-long-name' },
  { id: 'case-short', repo: 'example/app' },
  { id: 'case-none', repo: '' },
  { id: 'case-chat', repo: '', chatOnly: true },
]

for (const item of CASES) {
  const draft = ref('')
  const model = ref('deepseek-flash')
  createApp({
    render: () =>
      h(ChatComposer, {
        draft: draft.value,
        model: model.value,
        models: [
          { id: 'deepseek-flash', label: 'deepseek-flash' },
          { id: 'deepseek-v4-pro', label: 'deepseek-v4-pro' },
        ],
        effort: 'default',
        repo: item.repo,
        provider: 'github',
        chatOnly: Boolean(item.chatOnly),
        'onUpdate:draft': (v) => (draft.value = v),
        'onUpdate:model': (v) => (model.value = v),
      }),
  }).mount(`#${item.id}`)
}
