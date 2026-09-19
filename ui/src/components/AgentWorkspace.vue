<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'

import ChatComposer from './ChatComposer.vue'
import ChatMessage from './ChatMessage.vue'
import SessionSidebar from './SessionSidebar.vue'
import { useSmartScroll } from '../composables/useSmartScroll'
import { useAgentStore } from '../stores/agent'

const agent = useAgentStore()
const messageList = ref(null)
const sidebarCollapsed = ref(false)
const SIDEBAR_STORAGE_KEY = 'coding.sidebar.collapsed'
const isTitleEditing = ref(false)
const titleDraft = ref('')
const titleInput = ref(null)
const titleSaving = ref(false)
const titleError = ref('')

const derivedSessionTitle = computed(() => {
  const firstUserMessage = agent.messages.find((message) => message.author === 'user')
  const content = (firstUserMessage?.chunks || [])
    .filter((chunk) => chunk.kind === 'text')
    .map((chunk) => chunk.text || '')
    .join(' ')
    .replace(/```[\s\S]*?```/g, '[代码]')
    .replace(/[`*_>#\[\]()]/g, '')
    .replace(/\s+/g, ' ')
    .trim()

  if (!content) return '新会话'
  return content.length > 34 ? `${content.slice(0, 34)}...` : content
})
const sessionTitle = computed(() => agent.currentThread?.title || derivedSessionTitle.value)
const branchLabel = computed(() => {
  const branch = agent.currentThread?.branch
  const base = agent.currentThread?.baseBranch || agent.currentThread?.pr?.baseRef || 'master'
  if (!branch) return `基线 ${base}`
  return branch === base ? branch : `${branch} → ${base}`
})
const {
  hasUnreadContent,
  unreadContentCount,
  onScroll,
  notifyContentChanged,
  resetToLatest,
  scrollToLatest,
} = useSmartScroll(messageList)

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value
}

function startTitleEdit() {
  if (!agent.currentThread?.id || titleSaving.value) return
  titleError.value = ''
  titleDraft.value = sessionTitle.value
  isTitleEditing.value = true
  nextTick(() => {
    titleInput.value?.focus()
    titleInput.value?.select()
  })
}

function cancelTitleEdit() {
  isTitleEditing.value = false
  titleDraft.value = sessionTitle.value
  titleError.value = ''
}

async function saveTitle() {
  if (!isTitleEditing.value) return
  const threadId = agent.currentThread?.id
  const nextTitle = titleDraft.value.trim()
  const previousTitle = sessionTitle.value
  isTitleEditing.value = false

  if (!threadId || !nextTitle || nextTitle === previousTitle) {
    titleDraft.value = previousTitle
    return
  }

  titleSaving.value = true
  titleError.value = ''
  try {
    await agent.renameThread(threadId, nextTitle)
  } catch (error) {
    titleError.value = error.message || '标题保存失败'
    titleDraft.value = previousTitle
  } finally {
    titleSaving.value = false
  }
}

function onTitleKeydown(event) {
  if (event.isComposing) return
  if (event.key === 'Escape') {
    event.preventDefault()
    cancelTitleEdit()
    return
  }
  if (event.key === 'Enter') {
    event.preventDefault()
    saveTitle()
  }
}

function statusLabel(status, streaming) {
  if (streaming || status === 'running') return '正在运行'
  if (status === 'error' || status === 'failed') return '运行失败'
  if (status === 'finished' || status === 'completed') return '已完成'
  return '等待任务'
}

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
    isTitleEditing.value = false
    titleError.value = ''
    await nextTick()
    resetToLatest()
  },
)

function submitMessage(content) {
  scrollToLatest()
  agent.submit(content)
}

onMounted(() => {
  try {
    sidebarCollapsed.value = window.localStorage.getItem(SIDEBAR_STORAGE_KEY) === 'true'
  } catch {
    // 本地存储不可用时保持默认展开状态。
  }
  agent.bootstrap()
})

watch(sidebarCollapsed, (value) => {
  try {
    window.localStorage.setItem(SIDEBAR_STORAGE_KEY, String(value))
  } catch {
    // 本地存储不可用时不影响侧栏交互。
  }
})
</script>

<template>
  <main class="app-shell" :class="{ 'sidebar-collapsed': sidebarCollapsed }">
    <SessionSidebar
      :threads="agent.threads"
      :active-id="agent.currentThreadId"
      :disabled="agent.streaming"
      :collapsed="sidebarCollapsed"
      @new-thread="agent.createThread"
      @select-thread="agent.selectThread"
      @delete-thread="agent.deleteThread"
      @toggle-collapse="toggleSidebar"
    />
    <button
      v-if="!sidebarCollapsed"
      class="sidebar-backdrop"
      type="button"
      aria-label="关闭侧栏"
      @click="toggleSidebar"
    ></button>

    <section class="workspace">
      <header class="workspace-header">
        <div class="workspace-heading">
          <span class="conversation-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" focusable="false">
              <path d="M3.5 6.5h6l1.8 2H20.5v9.25a1.75 1.75 0 0 1-1.75 1.75H5.25a1.75 1.75 0 0 1-1.75-1.75V6.5Z" />
              <path d="M3.5 6.5V5.75A1.75 1.75 0 0 1 5.25 4h4.1l1.8 2h7.6A1.75 1.75 0 0 1 20.5 7.75V8.5" />
            </svg>
          </span>
          <div>
            <div class="workspace-title-row">
              <input
                v-if="isTitleEditing"
                ref="titleInput"
                v-model="titleDraft"
                class="workspace-title-input"
                type="text"
                maxlength="80"
                aria-label="会话标题"
                @blur="saveTitle"
                @keydown="onTitleKeydown"
              />
              <h1
                v-else
                :title="agent.currentThread?.id ? '双击编辑会话名称' : sessionTitle"
                @dblclick="startTitleEdit"
              >
                {{ sessionTitle }}
              </h1>
              <span v-if="titleSaving" class="title-save-state" aria-live="polite">保存中</span>
              <span v-else-if="titleError" class="title-save-error" :title="titleError">保存失败</span>
            </div>
            <p class="workspace-repo">
              {{ agent.currentThread?.repoFullName || agent.selectedRepo || '未选择 Gitee 仓库' }}
            </p>
          </div>
        </div>
        <div class="workspace-status">
          <span class="status-pill" :class="agent.currentThread?.status || 'idle'">
            <span class="status-pill-dot"></span>
            {{ statusLabel(agent.currentThread?.status, agent.streaming) }}
          </span>
          <span v-if="agent.currentThread" class="branch-label" :title="agent.currentThread.branch ? '当前工作分支 → 基线分支' : '尚未记录实际工作分支'">
            {{ branchLabel }}
          </span>
          <a v-if="agent.currentThread?.pr?.url" :href="agent.currentThread.pr.url" target="_blank" rel="noreferrer">查看 PR</a>
        </div>
      </header>

      <div ref="messageList" class="message-list" @scroll="onScroll">
        <div v-if="agent.loading" class="empty-state">正在加载会话...</div>
        <div v-else-if="!agent.messages.length" class="empty-state">
          <img class="empty-mark" src="/coding-mark.svg" alt="CODING" />
          <p class="eyebrow">开发工作台</p>
          <h2>开始一个开发任务</h2>
          <p>输入需求，CODING 会分析仓库、制定计划并执行验证。</p>
        </div>

        <ChatMessage
          v-for="message in agent.messages"
          :key="message.id"
          :message="message"
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
        v-model:repo="agent.selectedRepo"
        :disabled="agent.streaming"
        :model="agent.selectedModel"
        :effort="agent.selectedEffort"
        @send="submitMessage"
        @stop="agent.stopStream"
      />
    </section>
  </main>
</template>
