<script setup>
defineProps({
  tasks: { type: Array, default: () => [] },
  activeId: { type: String, default: null },
})

const emit = defineEmits(['select', 'cancel'])

function label(status) {
  if (status === 'queued') return '排队中'
  if (status === 'cancelling') return '正在取消'
  return '运行中'
}
</script>

<template>
  <nav v-if="tasks.length" class="active-task-strip" aria-label="活跃任务">
    <span class="active-task-heading">活跃任务</span>
    <div class="active-task-list">
      <div v-for="task in tasks" :key="task.id" class="active-task-item" :class="{ selected: task.id === activeId }">
        <button class="active-task-select" type="button" @click="emit('select', task.id)">
          <span class="status-dot" :class="task.status"></span>
          <span class="active-task-title">{{ task.title || task.repoFullName || '新任务' }}</span>
          <small>{{ label(task.status) }}</small>
        </button>
        <button
          v-if="task.runId"
          class="active-task-cancel"
          type="button"
          :aria-label="`取消${task.title || '任务'}`"
          title="取消任务"
          @click="emit('cancel', { threadId: task.id, runId: task.runId })"
        >×</button>
      </div>
    </div>
  </nav>
</template>

<style scoped>
.active-task-strip { display: flex; align-items: center; gap: 12px; padding: 9px 22px; border-bottom: 1px solid var(--border-color, #e5e7eb); overflow: hidden; }
.active-task-heading { flex: none; color: var(--muted-color, #737373); font-size: 12px; }
.active-task-list { display: flex; gap: 8px; overflow-x: auto; }
.active-task-item { display: flex; align-items: center; border: 1px solid var(--border-color, #e5e7eb); border-radius: 9px; }
.active-task-item.selected { border-color: var(--accent-color, #6366f1); }
.active-task-select, .active-task-cancel { display: flex; align-items: center; gap: 7px; border: 0; background: transparent; color: inherit; cursor: pointer; padding: 6px 8px; white-space: nowrap; }
.active-task-select small { color: var(--muted-color, #737373); }
.active-task-title { max-width: 190px; overflow: hidden; text-overflow: ellipsis; }
.active-task-cancel { padding-left: 4px; font-size: 17px; }
</style>
