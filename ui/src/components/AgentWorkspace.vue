<script setup>
/**
 * 主区布局：侧栏 + Header + 活跃任务条 + 会话流 + 两个项目弹窗。
 *
 * 这个文件现在只做三件事：**摆位置、接事件、管跨区域的那一点状态**
 * （会话标题的保存中/保存失败、项目的增删改弹窗）。其余的都搬到了
 * `WorkspaceHeader.vue` / `WorkspaceConversation.vue` / `WorkspaceWelcome.vue`
 * 与 `composables/useSidebarPreferences.js` / `composables/useProjectDialogs.js`。
 *
 * 它自己不再持有会话级或消息级状态 —— 那是上一版 454 行里最难读的部分：
 * 标题编辑、方案审批、人工介入、滚动、项目 CRUD 全挤在一个作用域里。
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'

import WorkspaceHeader from './WorkspaceHeader.vue'
import WorkspaceConversation from './WorkspaceConversation.vue'
import ActiveTaskStrip from './ActiveTaskStrip.vue'
import SessionSidebar from './SessionSidebar.vue'
import CreateProjectDialog from './CreateProjectDialog.vue'
import ConfirmProjectDeleteDialog from './ConfirmProjectDeleteDialog.vue'
import { useProjectDialogs } from '../composables/useProjectDialogs'
import { useSidebarPreferences } from '../composables/useSidebarPreferences'
import { useAgentStore } from '../stores/agent'

const agent = useAgentStore()
const titleSaving = ref(false)
const titleError = ref('')
let activeRunRefreshTimer = null

// 侧栏的两项本地偏好（整体收起 / 哪些项目折叠）连读写一起抽到了 composable 里。
const {
  collapsed: sidebarCollapsed,
  collapsedProjectIds,
  toggleCollapsed: toggleSidebar,
  toggleProject,
} = useSidebarPreferences()

const {
  showProjectDialog,
  creatingProject,
  projectBeingEdited,
  projectPendingDelete,
  deletingProject,
  projectDeleteError,
  openProjectDialog,
  closeProjectDialog,
  saveProject,
  askDeleteProject,
  confirmDeleteProject,
} = useProjectDialogs()

/** 会话还没有标题时，用第一条用户消息推导一个 —— 比"新会话"更有辨识度。 */
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
/**
 * Header 现在是两级面包屑：`<项目名> / <会话标题>`，仓库单独作为下面的徽标。
 *
 * 拆成两段而不是拼成一个字符串，是因为真实数据里项目名与仓库名**经常完全相同**
 * （项目基本就是按仓库建的），拼起来会得到
 * `clumsyspc/test_coding_repo · clumsyspc/test_coding_repo` —— 同一句话写两遍。
 * 拆开之后 `WorkspaceHeader` 能在两者相同时把徽标整个隐掉。
 */
const crumb = computed(() => {
  if (agent.currentThread?.chatOnly) return '普通聊天'
  return agent.currentProject?.name || ''
})
const repoLabel = computed(() => {
  if (agent.currentThread?.chatOnly) return '未连接仓库'
  return agent.currentThread?.repoFullName || agent.currentThread?.repo || ''
})

/**
 * Header 只负责"正在编辑"，保存这一步归这里 —— 它要打接口，还要有
 * 保存中/保存失败两个可见状态。空标题与未改动的判断已在 Header 里挡掉。
 */
async function renameTitle(nextTitle) {
  const threadId = agent.currentThread?.id
  if (!threadId) return
  titleSaving.value = true
  titleError.value = ''
  try {
    await agent.renameThread(threadId, nextTitle)
  } catch (error) {
    titleError.value = error.message || '标题保存失败'
  } finally {
    titleSaving.value = false
  }
}

async function createProjectThread(projectId) {
  try { await agent.createThread(projectId) }
  catch (error) { agent.error = error.message || '创建会话失败' }
}

function onWorkspaceShortcut(event) {
  if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== 'k') return
  event.preventDefault()
  createChatThread()
}

async function createChatThread() {
  try { await agent.createChatThread() }
  catch (error) { agent.error = error.message || '创建聊天失败' }
}

function renameProjectFromSidebar({ id, name }) {
  agent.renameProject(id, name).catch((error) => { agent.error = error.message })
}

// 切走就清掉，否则下次回到这个会话时还挂着上一个会话的"保存失败"。
watch(() => agent.currentThreadId, () => {
  titleError.value = ''
})

onMounted(() => {
  // Keep the empty workspace neutral: users may begin with a repository-free chat.
  agent.bootstrap()
  window.addEventListener('keydown', onWorkspaceShortcut)
  activeRunRefreshTimer = window.setInterval(() => agent.refreshActiveRuns(), 3000)
})

onUnmounted(() => {
  window.removeEventListener('keydown', onWorkspaceShortcut)
  if (activeRunRefreshTimer) window.clearInterval(activeRunRefreshTimer)
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
      :projects-error="agent.projectsError"
      :projects-loading="agent.loading && !agent.projects.length"
      @retry-projects="agent.retryProjects()"
      @new-chat="createChatThread"
      @new-project="openProjectDialog()"
      @new-thread="createProjectThread"
      @select-thread="agent.selectThread"
      @delete-thread="agent.deleteThread"
      @rename-project="renameProjectFromSidebar"
      @delete-project="askDeleteProject"
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
      <!-- key 绑线程 id：切换会话时强制重挂，编辑到一半的标题输入框不会跨会话留着。 -->
      <WorkspaceHeader
        :key="agent.currentThreadId || 'no-thread'"
        :title="sessionTitle"
        :repo-label="repoLabel"
        :crumb="crumb"
        :chat-only="!!agent.currentThread?.chatOnly"
        :editable="!!agent.currentThread?.id"
        :status="agent.currentThread?.status || ''"
        :streaming="agent.streaming"
        :branch-label="branchLabel"
        :show-branch="!!agent.currentThread && !agent.currentThread.chatOnly"
        :pr-url="agent.currentThread?.pr?.url || ''"
        :saving="titleSaving"
        :error-message="titleError"
        @rename="renameTitle"
      />

      <ActiveTaskStrip
        :tasks="agent.activeTasks"
        :active-id="agent.currentThreadId"
        @select="agent.selectThread"
        @cancel="agent.cancelRun($event.threadId, $event.runId)"
      />

      <WorkspaceConversation @new-project="openProjectDialog()" />

      <CreateProjectDialog
        v-if="showProjectDialog"
        :project="projectBeingEdited"
        :busy="creatingProject"
        :error-message="creatingProject ? '' : agent.error"
        @close="closeProjectDialog"
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
