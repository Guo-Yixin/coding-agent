<script setup>
import { computed, onMounted, onUnmounted, shallowRef } from 'vue'

import TodoPlan from './TodoPlan.vue'

const props = defineProps({
  activity: { type: Object, required: true },
  events: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
})
const emit = defineEmits(['expand'])

const storageKey = `coding.run-activity.expanded.${props.activity.run_id}`
function defaultExpanded() {
  return ['running', 'failed', 'awaiting_approval', 'queued'].includes(props.activity.status)
}

function readExpanded() {
  try {
    const saved = localStorage.getItem(storageKey)
    return saved === null ? defaultExpanded() : saved === 'true'
  } catch {
    return defaultExpanded()
  }
}

const expanded = shallowRef(readExpanded())
const clock = shallowRef(Date.now())
let timer = null

const latestTodos = computed(() => {
  for (let index = props.events.length - 1; index >= 0; index -= 1) {
    const event = props.events[index]
    if (event.kind === 'todo' && event.detail?.todos?.length) return event.detail.todos
  }
  return []
})
const timelineEvents = computed(() => props.events.filter((event) => event.kind !== 'todo'))
const durationMs = computed(() => {
  const start = Date.parse(props.activity.started_at || '')
  if (!Number.isFinite(start)) return null
  const finish = Date.parse(props.activity.finished_at || '')
  const end = Number.isFinite(finish) ? finish : clock.value
  return Math.max(0, end - start)
})
const durationLabel = computed(() => {
  if (durationMs.value === null) return '用时统计中'
  const totalSeconds = Math.floor(durationMs.value / 1000)
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  if (minutes > 0) return `用时 ${minutes} 分 ${seconds} 秒`
  return `用时 ${seconds} 秒`
})
const statusLabel = computed(() => ({
  running: '运行中', queued: '排队中', completed: '已完成',
  failed: '运行失败', awaiting_approval: '等待人工确认',
}[props.activity.status] || '执行记录'))
const todoSummary = computed(() => {
  if (!latestTodos.value.length) return ''
  const done = latestTodos.value.filter((todo) => todo.status === 'completed').length
  return `${done}/${latestTodos.value.length} 项完成`
})

function persistExpanded() {
  try {
    localStorage.setItem(storageKey, String(expanded.value))
  } catch {
    // Private browsing/storage limits should not prevent the panel from working.
  }
}

function toggle() {
  expanded.value = !expanded.value
  persistExpanded()
  if (expanded.value) emit('expand', { run_id: props.activity.run_id })
}

function eventStatus(status) {
  return ({ completed: '完成', in_progress: '进行中', pending: '等待中', error: '失败' })[status] || ''
}

onMounted(() => {
  if (expanded.value) emit('expand', { run_id: props.activity.run_id })
  if (props.activity.status === 'running') {
    timer = window.setInterval(() => { clock.value = Date.now() }, 1000)
  }
})
onUnmounted(() => {
  if (timer) window.clearInterval(timer)
})
</script>

<template>
  <section class="run-activity" :class="`run-activity-${activity.status}`">
    <button
      type="button"
      class="run-activity-toggle"
      :aria-expanded="expanded"
      @click="toggle"
    >
      <span class="run-activity-toggle-icon" aria-hidden="true">
        <svg viewBox="0 0 20 20" :class="{ expanded }" focusable="false">
          <path d="m5.5 7.5 4.5 4.5 4.5-4.5" />
        </svg>
      </span>
      <span class="run-activity-heading">运行轨迹</span>
      <span class="run-activity-summary">
        {{ durationLabel }}<template v-if="todoSummary"> · {{ todoSummary }}</template>
      </span>
      <span class="run-activity-status">{{ statusLabel }}</span>
    </button>

    <div v-if="expanded" class="run-activity-content">
      <p v-if="loading" class="run-activity-loading">正在恢复执行记录…</p>
      <template v-else>
        <TodoPlan v-if="latestTodos.length" :todos="latestTodos" />
        <ol v-if="timelineEvents.length" class="run-activity-timeline">
          <li v-for="event in timelineEvents" :key="event.id" class="run-activity-event">
            <span class="run-activity-event-title">{{ event.title }}</span>
            <span v-if="eventStatus(event.status)" class="run-activity-event-status">{{ eventStatus(event.status) }}</span>
            <p v-if="event.detail?.text" class="run-activity-event-text">{{ event.detail.text }}</p>
          </li>
        </ol>
        <p v-if="!latestTodos.length && !timelineEvents.length" class="run-activity-empty">
          暂无可展示的执行过程。
        </p>
      </template>
    </div>
  </section>
</template>
