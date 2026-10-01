<script setup>
import { computed, nextTick, ref, watch } from 'vue'

import UiButton from './ui/UiButton.vue'

const props = defineProps({
  projects: { type: Array, default: () => [] },
  standaloneThreads: { type: Array, default: () => [] },
  activeId: { type: String, default: null },
  disabled: { type: Boolean, default: false },
  collapsed: { type: Boolean, default: false },
  collapsedProjectIds: { type: Array, default: () => [] },
  // 「项目列表没读到」——与「一个项目都没有」是两件事，界面上必须分开。
  // 传空字符串表示读到了（哪怕是空数组）。
  projectsError: { type: String, default: '' },
  // 「还在读」也是第三种情况：这时 `projects` 同样是空的，
  // 不能让它冒充「你还没有项目」，否则首屏会先闪一下「创建第一个项目」再跳走。
  projectsLoading: { type: Boolean, default: false },
})

const emit = defineEmits([
  'new-chat', 'new-project', 'new-thread', 'select-thread', 'delete-thread',
  'rename-project', 'delete-project', 'toggle-project', 'toggle-collapse', 'retry-projects',
])

const editingProjectId = ref(null)
const projectNameDraft = ref('')
const openMenuId = ref(null)
const expandedProjectIds = ref(new Set())
const commandModifier = /Mac|iPhone|iPad/.test(navigator.userAgentData?.platform || navigator.platform || '') ? '⌘' : 'Ctrl'
const recentlyVisited = computed(() => [
  ...props.standaloneThreads.map((thread) => ({ ...thread, projectLabel: '普通聊天', repoLabel: '未连接仓库' })),
  ...props.projects.flatMap((project) => (project.conversations || []).map((thread) => ({
    ...thread,
    projectLabel: project.name,
    repoLabel: `${project.provider === 'gitee' ? 'Gitee' : 'GitHub'} · ${project.repoFullName || project.repo || '仓库未记录'}`,
  }))),
].sort((a, b) => Number(b.updatedAt || 0) - Number(a.updatedAt || 0)))

function visibleConversations(project) {
  const conversations = project.conversations || []
  return expandedProjectIds.value.has(project.id) ? conversations : conversations.slice(0, 3)
}

function toggleRecent(projectId) {
  const next = new Set(expandedProjectIds.value)
  next.has(projectId) ? next.delete(projectId) : next.add(projectId)
  expandedProjectIds.value = next
  try { localStorage.setItem('coding.sidebar.expanded-projects', JSON.stringify([...next])) } catch { /* optional preference */ }
}

function beginRename(project) {
  openMenuId.value = null
  editingProjectId.value = project.id
  projectNameDraft.value = project.name
  nextTick(() => {
    const input = document.querySelector('.project-rename-input')
    input?.focus()
    input?.select()
  })
}

function saveRename(project) {
  if (editingProjectId.value !== project.id) return
  const name = projectNameDraft.value.trim()
  editingProjectId.value = null
  if (name && name !== project.name) emit('rename-project', { id: project.id, name })
}

function cancelRename() {
  editingProjectId.value = null
  projectNameDraft.value = ''
}

function onRenameKeydown(event, project) {
  if (event.isComposing) return
  if (event.key === 'Enter') { event.preventDefault(); saveRename(project) }
  if (event.key === 'Escape') { event.preventDefault(); cancelRename() }
}

function openProjectMenu(event, project) {
  event.stopPropagation()
  openMenuId.value = openMenuId.value === project.id ? null : project.id
}

function sessionTooltip(thread) {
  return `${thread.title || '新聊天'}\n${thread.projectLabel} · ${thread.repoLabel}`
}

watch(() => props.projects, () => {
  try {
    const valid = new Set(props.projects.map((project) => project.id))
    expandedProjectIds.value = new Set([...expandedProjectIds.value].filter((id) => valid.has(id)))
  } catch { /* keep current view */ }
}, { deep: true })

try {
  const saved = JSON.parse(localStorage.getItem('coding.sidebar.expanded-projects') || '[]')
  if (Array.isArray(saved)) expandedProjectIds.value = new Set(saved)
} catch { /* optional preference */ }
</script>

<template>
  <aside class="sidebar" :class="{ collapsed }">
    <div class="sidebar-topbar">
      <div class="brand" :title="collapsed ? 'CODING 开发工作台' : undefined">
        <img src="/coding-mark.svg" alt="CODING" />
        <span v-if="!collapsed" class="brand-name">CODING</span>
      </div>
      <UiButton class="sidebar-toggle" variant="ghost" size="sm" icon :aria-label="collapsed ? '展开侧栏' : '折叠侧栏'" @click="emit('toggle-collapse')">
        <svg viewBox="0 0 20 20" aria-hidden="true"><path :d="collapsed ? 'm7 4 6 6-6 6' : 'm13 4-6 6 6 6'" /></svg>
      </UiButton>
    </div>

    <div v-if="!collapsed" class="sidebar-create-actions">
      <UiButton class="new-chat-button" variant="secondary" size="md" block align="start" :disabled="disabled" @click="emit('new-chat')"><span aria-hidden="true">↗</span><span>新聊天</span><kbd>{{ commandModifier }} K</kbd></UiButton>
      <UiButton class="new-project-button" variant="primary" size="md" block align="start" :disabled="disabled" @click="emit('new-project')"><span aria-hidden="true">＋</span><span>新建项目</span></UiButton>
    </div>
    <div v-else class="sidebar-create-actions collapsed-create-actions">
      <button class="rail-action" type="button" title="新聊天" aria-label="新聊天" @click="emit('new-chat')"><span aria-hidden="true">↗</span></button>
      <button class="rail-action" type="button" title="新建项目" aria-label="新建项目" @click="emit('new-project')"><span aria-hidden="true">＋</span></button>
    </div>

    <nav v-if="!collapsed" class="thread-list" aria-label="聊天和项目">
      <div v-if="standaloneThreads.length" class="sidebar-list-section">
        <div class="sidebar-section-label"><span>最近聊天</span><span class="section-count">{{ standaloneThreads.length }}</span></div>
        <div v-for="thread in standaloneThreads" :key="thread.id" class="thread-row" :class="{ 'is-active': thread.id === activeId }">
          <button type="button" class="thread-item standalone-thread-item" :class="{ active: thread.id === activeId }" :title="thread.title || '新聊天'" @click="emit('select-thread', thread.id)">
            <span class="status-dot" :class="thread.status"></span>
            <span class="thread-content"><span class="thread-title">{{ thread.title || '新聊天' }}</span><small>普通聊天</small></span>
          </button>
          <button type="button" class="thread-delete" aria-label="删除聊天" @click="emit('delete-thread', thread.id)">×</button>
        </div>
      </div>

      <div class="sidebar-list-section project-list-section">
        <div class="sidebar-section-label"><span>项目</span><span class="section-count">{{ projects.length }}</span></div>
        <section v-for="project in projects" :key="project.id" class="project-group" :class="{ 'project-is-collapsed': collapsedProjectIds.includes(project.id) }">
          <div class="project-heading">
            <UiButton class="project-disclosure" variant="ghost" size="sm" icon :aria-label="`${collapsedProjectIds.includes(project.id) ? '展开' : '折叠'}项目 ${project.name}`" :aria-expanded="!collapsedProjectIds.includes(project.id)" @click="emit('toggle-project', project.id)">
              <svg viewBox="0 0 16 16" aria-hidden="true"><path d="m5 6 3 3 3-3" /></svg>
            </UiButton>
            <span class="project-heading-main">
              <input v-if="editingProjectId === project.id" v-model="projectNameDraft" class="project-rename-input" maxlength="80" :aria-label="`项目 ${project.name} 新名称`" @blur="saveRename(project)" @keydown="onRenameKeydown($event, project)" />
              <strong v-else :title="`${project.name}（双击重命名）`" @dblclick.stop="beginRename(project)">{{ project.name }}</strong>
              <small :title="project.repoFullName || project.repo"><span class="provider-mark" :class="project.provider">{{ project.provider === 'gitee' ? 'G' : 'GH' }}</span><span class="repo-name">{{ project.repoFullName || project.repo || '历史仓库未记录' }}</span></small>
            </span>
            <UiButton class="project-add-thread" variant="ghost" size="sm" icon :disabled="disabled || project.legacy && !project.repo" :aria-label="`在 ${project.name} 新建会话`" title="在此项目中新建会话" @click="emit('new-thread', project.id)">＋</UiButton>
            <UiButton class="project-menu-trigger" variant="ghost" size="sm" icon :aria-label="`${project.name} 项目菜单`" :aria-expanded="openMenuId === project.id" @click="openProjectMenu($event, project)">···</UiButton>
            <div v-if="openMenuId === project.id" class="project-context-menu" role="menu">
              <button type="button" role="menuitem" @click="beginRename(project)"><span>✎</span>重命名项目</button>
              <button type="button" role="menuitem" class="context-danger" @click="openMenuId = null; emit('delete-project', project)"><span>⌫</span>删除项目</button>
            </div>
          </div>
          <div v-show="!collapsedProjectIds.includes(project.id)" class="project-conversations">
            <div v-for="thread in visibleConversations(project)" :key="thread.id" class="thread-row" :class="{ 'is-active': thread.id === activeId }">
              <button type="button" class="thread-item project-thread-item" :class="{ active: thread.id === activeId }" :title="thread.title || '新会话'" @click="emit('select-thread', thread.id)">
                <span class="status-dot" :class="thread.status"></span>
                <span class="thread-content"><span class="thread-title">{{ thread.title || '新会话' }}</span></span>
              </button>
              <button type="button" class="thread-delete" aria-label="删除会话" @click="emit('delete-thread', thread.id)">×</button>
            </div>
            <UiButton v-if="(project.conversations || []).length > 3" class="show-more-button" variant="ghost" size="sm" @click="toggleRecent(project.id)">
              {{ expandedProjectIds.has(project.id) ? '收起' : `展开显示其余 ${(project.conversations || []).length - 3} 个会话` }}
            </UiButton>
            <div v-if="!project.conversations?.length" class="project-no-conversations">尚无会话 <UiButton variant="ghost" size="sm" @click="emit('new-thread', project.id)">新建</UiButton></div>
          </div>
        </section>
        <div v-if="!projects.length && projectsError" class="project-error" role="alert">
          <span class="error-mark" aria-hidden="true">!</span>
          <strong>项目列表没能加载</strong>
          <small>{{ projectsError }}</small>
          <p class="project-error-hint">这不代表你还没有项目。重试一次，或先继续用普通聊天。</p>
          <UiButton variant="secondary" size="sm" @click="emit('retry-projects')">重新加载</UiButton>
        </div>
        <div v-else-if="!projects.length && projectsLoading" class="project-loading" role="status" aria-live="polite">
          <span class="loading-spinner" aria-hidden="true"></span>
          <small>正在加载项目…</small>
        </div>
        <div v-else-if="!projects.length" class="project-empty"><span class="empty-folder">⌂</span><strong>项目会出现在这里</strong><small>创建项目并绑定仓库，开始持续开发。</small><UiButton variant="primary" size="sm" @click="emit('new-project')">创建第一个项目</UiButton></div>
      </div>
    </nav>

    <nav v-else class="collapsed-session-rail" aria-label="最近会话快捷入口">
      <button v-for="thread in recentlyVisited" :key="thread.id" type="button" class="rail-session" :class="[{ active: thread.id === activeId }, `rail-${thread.status || 'idle'}`]" :aria-label="sessionTooltip(thread)" :data-tooltip="sessionTooltip(thread)" @click="emit('select-thread', thread.id)">
        <span class="rail-session-mark"></span>
      </button>
      <div v-if="!recentlyVisited.length" class="rail-empty" title="创建聊天或项目后，这里会显示快捷入口">···</div>
    </nav>

    <div v-if="!collapsed" class="sidebar-bottom"><span class="sidebar-bottom-dot"></span><span>工作区已就绪</span><span class="sidebar-bottom-version">v1</span></div>
  </aside>
</template>
