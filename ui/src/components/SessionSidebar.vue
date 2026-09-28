<script setup>
import { computed, nextTick, ref, watch } from 'vue'

const props = defineProps({
  projects: { type: Array, default: () => [] },
  standaloneThreads: { type: Array, default: () => [] },
  activeId: { type: String, default: null },
  disabled: { type: Boolean, default: false },
  collapsed: { type: Boolean, default: false },
  collapsedProjectIds: { type: Array, default: () => [] },
})

const emit = defineEmits([
  'new-chat', 'new-project', 'new-thread', 'select-thread', 'delete-thread',
  'rename-project', 'delete-project', 'toggle-project', 'toggle-collapse',
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
      <button class="sidebar-toggle" type="button" :aria-label="collapsed ? '展开侧栏' : '折叠侧栏'" @click="emit('toggle-collapse')">
        <svg viewBox="0 0 20 20" aria-hidden="true"><path :d="collapsed ? 'm7 4 6 6-6 6' : 'm13 4-6 6 6 6'" /></svg>
      </button>
    </div>

    <div v-if="!collapsed" class="sidebar-create-actions">
      <button class="new-chat-button" type="button" :disabled="disabled" @click="emit('new-chat')"><span aria-hidden="true">↗</span><span>新聊天</span><kbd>{{ commandModifier }} K</kbd></button>
      <button class="new-project-button" type="button" :disabled="disabled" @click="emit('new-project')"><span aria-hidden="true">＋</span><span>新建项目</span></button>
    </div>
    <div v-else class="sidebar-create-actions collapsed-create-actions">
      <button class="rail-action" type="button" title="新聊天" aria-label="新聊天" @click="emit('new-chat')"><span aria-hidden="true">↗</span></button>
      <button class="rail-action" type="button" title="新建项目" aria-label="新建项目" @click="emit('new-project')"><span aria-hidden="true">＋</span></button>
    </div>

    <nav v-if="!collapsed" class="thread-list" aria-label="聊天和项目">
      <div v-if="standaloneThreads.length" class="sidebar-list-section">
        <div class="sidebar-section-label"><span>最近聊天</span><span class="section-count">{{ standaloneThreads.length }}</span></div>
        <button v-for="thread in standaloneThreads" :key="thread.id" type="button" class="thread-item standalone-thread-item" :class="{ active: thread.id === activeId }" @click="emit('select-thread', thread.id)">
          <span class="status-dot" :class="thread.status"></span>
          <span class="thread-content"><span class="thread-title">{{ thread.title || '新聊天' }}</span><small>普通聊天</small></span>
          <span class="thread-delete" role="button" tabindex="0" aria-label="删除聊天" @click.stop="emit('delete-thread', thread.id)" @keydown.enter.stop.prevent="emit('delete-thread', thread.id)">×</span>
        </button>
      </div>

      <div class="sidebar-list-section project-list-section">
        <div class="sidebar-section-label"><span>项目</span><span class="section-count">{{ projects.length }}</span></div>
        <section v-for="project in projects" :key="project.id" class="project-group" :class="{ 'project-is-collapsed': collapsedProjectIds.includes(project.id) }">
          <div class="project-heading">
            <button class="project-disclosure" type="button" :aria-label="`${collapsedProjectIds.includes(project.id) ? '展开' : '折叠'}项目 ${project.name}`" :aria-expanded="!collapsedProjectIds.includes(project.id)" @click="emit('toggle-project', project.id)">
              <svg viewBox="0 0 16 16" aria-hidden="true"><path d="m5 6 3 3 3-3" /></svg>
            </button>
            <span class="project-heading-main">
              <input v-if="editingProjectId === project.id" v-model="projectNameDraft" class="project-rename-input" maxlength="80" :aria-label="`项目 ${project.name} 新名称`" @blur="saveRename(project)" @keydown="onRenameKeydown($event, project)" />
              <strong v-else :title="`${project.name}（双击重命名）`" @dblclick.stop="beginRename(project)">{{ project.name }}</strong>
              <small :title="project.repoFullName || project.repo"><span class="provider-mark" :class="project.provider">{{ project.provider === 'gitee' ? 'G' : 'GH' }}</span>{{ project.repoFullName || project.repo || '历史仓库未记录' }}</small>
            </span>
            <button class="project-add-thread" type="button" :disabled="disabled || project.legacy && !project.repo" :aria-label="`在 ${project.name} 新建会话`" title="在此项目中新建会话" @click="emit('new-thread', project.id)">＋</button>
            <button class="project-menu-trigger" type="button" :aria-label="`${project.name} 项目菜单`" :aria-expanded="openMenuId === project.id" @click="openProjectMenu($event, project)">···</button>
            <div v-if="openMenuId === project.id" class="project-context-menu" role="menu">
              <button type="button" role="menuitem" @click="beginRename(project)"><span>✎</span>重命名项目</button>
              <button type="button" role="menuitem" class="context-danger" @click="openMenuId = null; emit('delete-project', project)"><span>⌫</span>删除项目</button>
            </div>
          </div>
          <div v-show="!collapsedProjectIds.includes(project.id)" class="project-conversations">
            <button v-for="thread in visibleConversations(project)" :key="thread.id" type="button" class="thread-item project-thread-item" :class="{ active: thread.id === activeId }" :title="thread.title || '新会话'" @click="emit('select-thread', thread.id)">
              <span class="status-dot" :class="thread.status"></span>
              <span class="thread-content"><span class="thread-title">{{ thread.title || '新会话' }}</span></span>
              <span class="thread-delete" role="button" tabindex="0" aria-label="删除会话" @click.stop="emit('delete-thread', thread.id)" @keydown.enter.stop.prevent="emit('delete-thread', thread.id)">×</span>
            </button>
            <button v-if="(project.conversations || []).length > 3" class="show-more-button" type="button" @click="toggleRecent(project.id)">
              {{ expandedProjectIds.has(project.id) ? '收起' : `展开显示其余 ${(project.conversations || []).length - 3} 个会话` }}
            </button>
            <div v-if="!project.conversations?.length" class="project-no-conversations">尚无会话 <button type="button" @click="emit('new-thread', project.id)">新建</button></div>
          </div>
        </section>
        <div v-if="!projects.length" class="project-empty"><span class="empty-folder">⌂</span><strong>项目会出现在这里</strong><small>创建项目并绑定仓库，开始持续开发。</small><button type="button" @click="emit('new-project')">创建第一个项目</button></div>
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
