<script setup>
/**
 * 主区的会话流：加载态 / 空态 / 消息列表 / 错误横幅 /「N 条新内容」/ 输入框，
 * 加上围着它转的那一套交互流程（方案审批、人工介入答复、运行轨迹展开）。
 *
 * 为什么这一整块要独立成组件：它的核心是 `useSmartScroll` 那套「用户是不是
 * 贴着底部」的判断，而**未读计数只在用户不贴底时才累加** —— 也就是说
 * 消息区、未读按钮、输入框三者共享同一个滚动上下文，拆开任何一半都会让
 * 状态穿过组件边界。它天然是一个整体。
 *
 * 项目级动作（新建项目）不在这里，往上抛给 `AgentWorkspace.vue`。
 */
import { computed, nextTick, ref, watch } from 'vue'

import ChatComposer from './ChatComposer.vue'
import ChatMessage from './ChatMessage.vue'
import WorkspaceWelcome from './WorkspaceWelcome.vue'
import { useSmartScroll } from '../composables/useSmartScroll'
import { useAgentStore } from '../stores/agent'

const emit = defineEmits(['new-project'])

const agent = useAgentStore()
const messageList = ref(null)
/** 正在"调整方案"的目标；非空时输入框会提示，且下一条消息带上 revise_plan。 */
const revisionPlan = ref(null)

const pendingIntervention = computed(() => {
  if (agent.currentThread && Object.hasOwn(agent.currentThread, 'pendingIntervention')) {
    return agent.currentThread.pendingIntervention
  }
  for (const message of agent.messages) {
    const active = (message.chunks || []).find((chunk) => (
      chunk.kind === 'intervention' && ['pending', 'resuming'].includes(chunk.status)
    ))
    if (active) return active
  }
  return null
})

const {
  hasUnreadContent,
  unreadContentCount,
  onScroll,
  notifyContentChanged,
  resetToLatest,
  scrollToLatest,
} = useSmartScroll(messageList)

async function createChatThread() {
  try { await agent.createChatThread() }
  catch (error) { agent.error = error.message || '创建聊天失败' }
}

function submitMessage(content) {
  // 等待人工介入时输入框已经锁住，这里是第二道防线。
  if (pendingIntervention.value) return
  scrollToLatest()
  if (revisionPlan.value) {
    const plan = revisionPlan.value
    revisionPlan.value = null
    agent.submit(content, { interaction_action: 'revise_plan', plan_id: plan.plan_id })
    return
  }
  agent.submit(content)
}

function handlePlanAction({ action, proposal }) {
  if (action === 'revise') {
    // 不立刻发请求：把下一条用户输入当作修订意见一起提交。
    revisionPlan.value = proposal
    return
  }
  const decision = action === 'approve' ? 'approve_plan' : 'reject_plan'
  const prompt = action === 'approve' ? '确认并实施该方案' : '拒绝实施该方案'
  agent.submit(prompt, { interaction_action: decision, plan_id: proposal.plan_id })
}

function handleInterventionResponse({ intervention_id, response }) {
  agent.submit(response, { interaction_action: 'resume_intervention', intervention_id })
}

function handleRunActivityExpand({ run_id }) {
  agent.loadRunActivity(run_id)
}

// 消息变长了才需要重算"现在离底部多远"。只比 id 不够 —— 流式输出时 id 不变。
watch(
  () => agent.messages.map((message) => {
    const length = message.chunks?.map((chunk) => {
      if (chunk.kind === 'todo') return JSON.stringify(chunk.todos || [])
      return chunk.text || ''
    }).join('').length || 0
    return `${message.id}:${length}`
  }).join('|'),
  async () => {
    await nextTick()
    notifyContentChanged()
  },
)

watch(
  () => agent.currentThreadId,
  async () => {
    revisionPlan.value = null
    await nextTick()
    resetToLatest()
  },
)
</script>

<template>
  <div ref="messageList" class="message-list" @scroll="onScroll">
    <div v-if="agent.loading" class="empty-state loading-state" role="status" aria-live="polite">
      <span class="loading-spinner" aria-hidden="true"></span>
      <p class="empty-copy">正在加载会话…</p>
    </div>
    <WorkspaceWelcome
      v-else-if="!agent.messages.length"
      :chat-only="!!agent.currentThread?.chatOnly"
      :project-name="agent.currentProject?.name || ''"
      :has-thread="!!agent.currentThread"
      :model="agent.selectedModel"
      @new-chat="createChatThread"
      @new-project="emit('new-project')"
    />

    <ChatMessage
      v-for="message in agent.messages"
      :key="message.id"
      :message="message"
      :disabled="agent.streaming"
      :run-activity-events="agent.runActivityEvents"
      :run-activity-loading="agent.runActivityLoading"
      @plan-action="handlePlanAction"
      @intervention-response="handleInterventionResponse"
      @run-activity-expand="handleRunActivityExpand"
    />

    <div v-if="agent.error" class="error-banner">{{ agent.error }}</div>
  </div>

  <button
    v-if="hasUnreadContent"
    class="new-content-button"
    type="button"
    @click="scrollToLatest('smooth')"
  >
    <span aria-hidden="true">↓</span>
    {{ unreadContentCount >= 99 ? '99+ 条新内容' : `${unreadContentCount} 条新内容` }}
  </button>

  <ChatComposer
    :draft="agent.currentDraft"
    @update:draft="agent.setDraft(agent.currentThreadId, $event)"
    :repo="agent.currentThread?.repoFullName || agent.currentThread?.repo || ''"
    :provider="agent.currentThread?.provider || 'github'"
    :chat-only="!agent.currentThread || !!agent.currentThread.chatOnly"
    :disabled="agent.streaming"
    :locked="!!pendingIntervention"
    :locked-hint="pendingIntervention ? '此会话正在等待人工介入答复，请在上方确认卡片中提交答复后继续。' : ''"
    :model="agent.selectedModel"
    :models="agent.modelOptions"
    :effort="agent.selectedEffort"
    :interaction-hint="revisionPlan ? `正在调整方案 V${revisionPlan.version || 1}` : ''"
    @send="submitMessage"
    @update:model="agent.setSelectedModel"
    @cancel-interaction="revisionPlan = null"
    @stop="agent.stopStream"
  />
</template>
