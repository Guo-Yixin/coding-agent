<script setup>
/**
 * 主区空态（三条文案分支，靠是否有会话 / 是否普通聊天 / 是否有项目区分）。
 *
 * 这个组件存在的理由不只是"行数"：它是**新用户看到的第一屏**，而且只在
 * `!agent.currentThread` 时才会出现那两个 CTA —— 只要账号下有任何一条会话，
 * 这一屏就再也回不去，手工点不出来，所以它必须能被单独渲染出来验
 * （见 `docs/design/DESIGN.md` §14：这里曾经有五个类名完全没有 CSS）。
 *
 * DOM 结构与类名必须保持不变：`AgentWorkspace.test.js` 断言
 * `.welcome-actions button` 恰好两个、`.empty-state` 的文案。
 */
import UiButton from './ui/UiButton.vue'

defineProps({
  /** 普通聊天：不连接仓库 */
  chatOnly: { type: Boolean, default: false },
  /** 当前项目名；为空表示没有绑定项目 */
  projectName: { type: String, default: '' },
  /** 是否已经有会话（有则显示能力标签而不是两个 CTA） */
  hasThread: { type: Boolean, default: false },
  /** 当前选中的模型，作为能力标签之一 */
  model: { type: String, default: '' },
})

defineEmits(['new-chat', 'new-project'])
</script>

<template>
  <div class="empty-state">
    <div class="welcome-mark"><img class="empty-mark" src="/coding-mark.svg" alt="" /><span></span></div>
    <p class="eyebrow">CODING · 开发工作台</p>
    <h2>{{ chatOnly ? '从一个好问题开始' : projectName ? `准备好继续构建${projectName}` : '让想法，开始成为产品' }}</h2>
    <p class="empty-copy">{{ chatOnly ? '这是一个不连接仓库的独立聊天，可用于讨论方案、梳理思路与技术问答。' : projectName ? '描述你希望完成的工作，CODING 将围绕项目仓库分析、规划并推进任务。' : '开启一段自由对话，或创建一个绑定仓库的项目工作空间。' }}</p>
    <div v-if="!hasThread" class="welcome-actions">
      <UiButton variant="primary" @click="$emit('new-chat')">开始新聊天</UiButton>
      <UiButton variant="secondary" @click="$emit('new-project')">创建项目</UiButton>
    </div>
    <div v-else class="welcome-capabilities"><span>独立会话</span><span>{{ chatOnly ? '纯对话模式' : '仓库上下文' }}</span><span>{{ model }}</span></div>
  </div>
</template>
