<script setup>
defineProps({
  threads: {
    type: Array,
    default: () => [],
  },
  activeId: {
    type: String,
    default: null,
  },
  disabled: {
    type: Boolean,
    default: false,
  },
  collapsed: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['new-thread', 'select-thread', 'delete-thread', 'toggle-collapse'])

function titleOf(thread) {
  return thread.title || thread.repoFullName || thread.repo || '未命名任务'
}

function confirmDelete(thread) {
  if (window.confirm('确认删除该会话吗？该操作会同时删除会话历史、checkpoint 和业务记录。')) {
    emit('delete-thread', thread.id)
  }
}
</script>

<template>
  <aside class="sidebar" :class="{ collapsed }">
    <div class="sidebar-topbar">
      <div class="brand" :title="collapsed ? 'CODING' : undefined">
        <img src="/coding-mark.svg" alt="CODING" />
        <span v-if="!collapsed" class="brand-name">CODING</span>
      </div>
      <button
        class="sidebar-toggle"
        type="button"
        :aria-label="collapsed ? '展开侧栏' : '折叠侧栏'"
        :title="collapsed ? '展开侧栏' : '折叠侧栏'"
        @click="emit('toggle-collapse')"
      >
        <span aria-hidden="true">{{ collapsed ? '›' : '‹' }}</span>
      </button>
    </div>

    <button class="new-button" :disabled="disabled" :title="collapsed ? '新任务' : undefined" @click="$emit('new-thread')">
      <span class="new-button-icon" aria-hidden="true">＋</span>
      <span v-if="!collapsed">新任务</span>
    </button>

    <div v-if="!collapsed" class="sidebar-section-label">历史任务</div>
    <nav class="thread-list" aria-label="历史任务">
      <div class="thread-list-inner">
        <button
          v-for="thread in threads"
          :key="thread.id"
          type="button"
          class="thread-item"
          :class="{ active: thread.id === activeId }"
          :aria-label="collapsed ? `${titleOf(thread)}，${thread.repoFullName || thread.repo || '未选择仓库'}` : undefined"
          :title="collapsed ? `${titleOf(thread)} · ${thread.repoFullName || thread.repo || '未选择仓库'}` : undefined"
          @click="$emit('select-thread', thread.id)"
        >
          <span class="status-dot" :class="thread.status"></span>
          <span v-if="!collapsed" class="thread-content">
            <span class="thread-title">{{ titleOf(thread) }}</span>
            <small>{{ thread.repoFullName || thread.repo }}</small>
          </span>
          <span v-else class="collapsed-thread-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" focusable="false">
              <path d="M5 6.5h14A1.5 1.5 0 0 1 20.5 8v8A1.5 1.5 0 0 1 19 17.5H9l-4.5 3v-12A1.5 1.5 0 0 1 5 6.5Z" />
              <path d="M8 11.5h.01M12 11.5h.01M16 11.5h.01" />
            </svg>
          </span>
          <span
            v-if="!collapsed"
            class="thread-delete"
            title="删除会话"
            role="button"
            tabindex="0"
            @click.stop="confirmDelete(thread)"
            @keydown.enter.stop.prevent="confirmDelete(thread)"
            @keydown.space.stop.prevent="confirmDelete(thread)"
          >
            ×
          </span>
        </button>
      </div>
    </nav>
  </aside>
</template>
