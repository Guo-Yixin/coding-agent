<script setup>
import { computed, onUnmounted, shallowRef } from 'vue'

const props = defineProps({
  text: { type: String, required: true },
  timestamp: { type: [String, Number], default: null },
})

const copied = shallowRef(false)
const copyError = shallowRef(false)
let feedbackTimer
onUnmounted(() => window.clearTimeout(feedbackTimer))

const timeLabel = computed(() => {
  if (props.timestamp === null || props.timestamp === undefined || props.timestamp === '') return ''
  const date = new Date(props.timestamp)
  if (Number.isNaN(date.getTime())) return ''
  return new Intl.DateTimeFormat(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).format(date)
})

async function copyMessage() {
  copyError.value = false
  try {
    await navigator.clipboard.writeText(props.text)
    copied.value = true
  } catch {
    copyError.value = true
  }
  window.clearTimeout(feedbackTimer)
  feedbackTimer = window.setTimeout(() => {
    copied.value = false
    copyError.value = false
  }, 1400)
}
</script>

<template>
  <div class="message-actions">
    <button
      class="message-copy-button"
      type="button"
      :aria-label="copyError ? '复制失败' : copied ? '已复制消息' : '复制消息'"
      :title="copyError ? '复制失败' : copied ? '已复制' : '复制消息'"
      @click="copyMessage"
    >
      <svg v-if="!copied" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <rect x="8" y="8" width="12" height="12" rx="2" stroke="currentColor" stroke-width="1.7" />
        <path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" stroke="currentColor" stroke-width="1.7" />
      </svg>
      <span v-else aria-hidden="true">{{ copyError ? '!' : '✓' }}</span>
    </button>
    <span class="message-copy-feedback" aria-live="polite">
      {{ copyError ? '复制失败' : copied ? '已复制' : '' }}
    </span>
    <time v-if="timeLabel" class="message-action-time" :datetime="new Date(timestamp).toISOString()">
      {{ timeLabel }}
    </time>
  </div>
</template>
