import { createApp, h, ref } from 'vue'

import ChatComposer from '../src/components/ChatComposer.vue'
import '../src/styles/tokens.css'
import '../src/styles/main.css'

// 只用于开发期检视：把 ChatComposer 单独挂到一个干净的 iframe 视口里，
// 这样 media query 会按 iframe 的宽度生效，从而能截到窄屏下的底栏排布。
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
      repo: 'Guo-Yixin/test-coding-repo',
      provider: 'github',
      'onUpdate:draft': (v) => (draft.value = v),
      'onUpdate:model': (v) => (model.value = v),
    }),
}).mount('#app')
