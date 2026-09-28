<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'

import ChatComposer from './ChatComposer.vue'
import ChatMessage from './ChatMessage.vue'
import ActiveTaskStrip from './ActiveTaskStrip.vue'
import SessionSidebar from './SessionSidebar.vue'
import CreateProjectDialog from './CreateProjectDialog.vue'
import ConfirmProjectDeleteDialog from './ConfirmProjectDeleteDialog.vue'
import { useSmartScroll } from '../composables/useSmartScroll'
import { useAgentStore } from '../stores/agent'

const agent = useAgentStore()
const messageList = ref(null)
const sidebarCollapsed = ref(false)
const showProjectDialog = ref(false)
const creatingProject = ref(false)
const projectBeingEdited = ref(null)
const projectPendingDelete = ref(null)
const deletingProject = ref(false)
const projectDeleteError = ref('')
const collapsedProjectIds = ref([])
const SIDEBAR_STORAGE_KEY = 'coding.sidebar.collapsed'
const PROJECT_COLLAPSE_STORAGE_KEY = 'coding.sidebar.collapsed-projects'
const isTitleEditing = ref(false)
const titleDraft = ref('')
const titleInput = ref(null)
const titleSaving = ref(false)
const titleError = ref('')
let activeRunRefreshTimer = null
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

function onWorkspaceShortcut(event) {
  if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== 'k') return
  event.preventDefault()
  createChatThread()
}

function openProjectDialog(project = null) {
  projectBeingEdited.value = project
  agent.error = ''
  showProjectDialog.value = true
}

async function saveProject({ id, name, provider, repo }) {
  creatingProject.value = true
  agent.error = ''
  try {
    if (id) await agent.renameProject(id, name)
    else await agent.createProject(name, provider, repo)
    showProjectDialog.value = false
    projectBeingEdited.value = null
  } catch (error) {
    agent.error = error.message || (id ? '重命名项目失败' : '创建项目失败')
  } finally {
    creatingProject.value = false
  }
}

async function createChatThread() {
  try { await agent.createChatThread() }
  catch (error) { agent.error = error.message || '创建聊天失败' }
}

function toggleProject(projectId) {
  const next = new Set(collapsedProjectIds.value)
  next.has(projectId) ? next.delete(projectId) : next.add(projectId)
  collapsedProjectIds.value = [...next]
}

async function confirmDeleteProject() {
  if (!projectPendingDelete.value) return
  deletingProject.value = true
  projectDeleteError.value = ''
  try {
    await agent.deleteProject(projectPendingDelete.value.id)
    projectPendingDelete.value = null
  } catch (error) {
    projectDeleteError.value = error.message || '删除项目失败'
  } finally {
    deletingProject.value = false
  }
}

async function createProjectThread(projectId) {
  try { await agent.createThread(projectId) }
  catch (error) { agent.error = error.message || '创建会话失败' }
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
  if (status === 'queued') return '排队中'
  if (status === 'cancelling') return '正在取消'
  if (status === 'awaiting_approval') return '等待你介入'
  if (status === 'cancelled') return '已取消'
  if (status === 'interrupted') return '运行中断'
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
    revisionPlan.value = null
    isTitleEditing.value = false
    titleError.value = ''
    await nextTick()
    resetToLatest()
  },
)

function submitMessage(content) {
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

onMounted(() => {
  try {
    sidebarCollapsed.value = window.localStorage.getItem(SIDEBAR_STORAGE_KEY) === 'true'
    const savedCollapsedProjects = JSON.parse(window.localStorage.getItem(PROJECT_COLLAPSE_STORAGE_KEY) || '[]')
    if (Array.isArray(savedCollapsedProjects)) collapsedProjectIds.value = savedCollapsedProjects
  } catch {
    // 本地存储不可用时保持默认展开状态。
  }
  // Keep the empty workspace neutral: users may begin with a repository-free chat.
  agent.bootstrap()
  window.addEventListener('keydown', onWorkspaceShortcut)
  activeRunRefreshTimer = window.setInterval(() => agent.refreshActiveRuns(), 3000)
})

onUnmounted(() => {
  window.removeEventListener('keydown', onWorkspaceShortcut)
  if (activeRunRefreshTimer) window.clearInterval(activeRunRefreshTimer)
})

watch(sidebarCollapsed, (value) => {
  try {
    window.localStorage.setItem(SIDEBAR_STORAGE_KEY, String(value))
  } catch {
    // 本地存储不可用时不影响侧栏交互。
  }
})

watch(collapsedProjectIds, (value) => {
  try { window.localStorage.setItem(PROJECT_COLLAPSE_STORAGE_KEY, JSON.stringify(value)) } catch { /* optional preference */ }
})
</script>

<template>
  <main class="app-shell" :class="{ 'sidebar-collapsed': sidebarCollapsed }">
    <SessionSidebar
      :projects="agent.projects"
      :standalone-threads="agent.standaloneThreads"
      :active-id="agent.currentThreadId"
      :disabled="false"
      :collapsed="sidebarCollapsed"
      :collapsed-project-ids="collapsedProjectIds"
      @new-chat="createChatThread"
      @new-project="openProjectDialog()"
      @new-thread="createProjectThread"
      @select-thread="agent.selectThread"
      @delete-thread="agent.deleteThread"
      @rename-project="agent.renameProject($event.id, $event.name).catch(error => agent.error = error.message)"
      @delete-project="projectPendingDelete = $event; projectDeleteError = ''"
      @toggle-project="toggleProject"
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
            <p class="workspace-repo" :class="{ 'workspace-repo-chat': agent.currentThread?.chatOnly }">
              {{ agent.currentThread?.chatOnly ? '普通聊天 · 未连接仓库' : agent.currentProject?.name ? `${agent.currentProject.name} · ${agent.currentThread?.repoFullName || agent.currentThread?.repo}` : agent.currentThread?.repoFullName || agent.currentThread?.repo || '选择一个项目，或新建普通聊天' }}
            </p>
          </div>
        </div>
        <div class="workspace-status">
          <span class="status-pill" :class="agent.currentThread?.status || 'idle'">
            <span class="status-pill-dot"></span>
            {{ statusLabel(agent.currentThread?.status, agent.streaming) }}
          </span>
          <span v-if="agent.currentThread && !agent.currentThread.chatOnly" class="branch-label" :title="agent.currentThread.branch ? '当前工作分支 → 基线分支' : '尚未记录实际工作分支'">
            {{ branchLabel }}
          </span>
          <a v-if="agent.currentThread?.pr?.url" :href="agent.currentThread.pr.url" target="_blank" rel="noreferrer">查看 PR</a>
        </div>
      </header>

      <ActiveTaskStrip
        :tasks="agent.activeTasks"
        :active-id="agent.currentThreadId"
        @select="agent.selectThread"
        @cancel="agent.cancelRun($event.threadId, $event.runId)"
      />

      <div ref="messageList" class="message-list" @scroll="onScroll">
        <div v-if="agent.loading" class="empty-state">正在加载会话...</div>
        <div v-else-if="!agent.messages.length" class="empty-state">
          <div class="welcome-mark"><img class="empty-mark" src="/coding-mark.svg" alt="" /><span></span></div>
          <p class="eyebrow">CODING · 开发工作台</p>
          <h2>{{ agent.currentThread?.chatOnly ? '从一个好问题开始' : agent.currentProject ? `准备好继续构建${agent.currentProject.name}` : '让想法，开始成为产品' }}</h2>
          <p>{{ agent.currentThread?.chatOnly ? '这是一个不连接仓库的独立聊天，可用于讨论方案、梳理思路与技术问答。' : agent.currentProject ? '描述你希望完成的工作，CODING 将围绕项目仓库分析、规划并推进任务。' : '开启一段自由对话，或创建一个绑定仓库的项目工作空间。' }}</p>
          <div v-if="!agent.currentThread" class="welcome-actions">
            <button type="button" class="welcome-primary" @click="createChatThread">开始新聊天</button>
            <button type="button" class="welcome-secondary" @click="openProjectDialog()">创建项目</button>
          </div>
          <div v-else class="welcome-capabilities"><span>独立会话</span><span>{{ agent.currentThread.chatOnly ? '纯对话模式' : '仓库上下文' }}</span><span>{{ agent.selectedModel }}</span></div>
        </div>

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
      <CreateProjectDialog
        v-if="showProjectDialog"
        :project="projectBeingEdited"
        :busy="creatingProject"
        :error-message="creatingProject ? '' : agent.error"
        @close="showProjectDialog = false"
        @save="saveProject"
      />
      <ConfirmProjectDeleteDialog
        v-if="projectPendingDelete"
        :project="projectPendingDelete"
        :busy="deletingProject"
        :error-message="projectDeleteError"
        @close="projectPendingDelete = null"
        @confirm="confirmDeleteProject"
      />
    </section>
  </main>
</template>
