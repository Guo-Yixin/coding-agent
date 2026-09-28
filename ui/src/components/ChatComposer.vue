<script setup>
import { computed, nextTick, shallowRef } from 'vue'

const props = defineProps({
  disabled: {
    type: Boolean,
    default: false,
  },
  draft: { type: String, default: '' },
  model: {
    type: String,
    default: '',
  },
  models: { type: Array, default: () => [] },
  chatOnly: { type: Boolean, default: false },
  effort: {
    type: String,
    default: 'default',
  },
  repo: {
    type: String,
    default: '',
  },
  provider: {
    type: String,
    default: 'github',
  },
  locked: {
    type: Boolean,
    default: false,
  },
  lockedHint: {
    type: String,
    default: '',
  },
  interactionHint: {
    type: String,
    default: '',
  },
})

const emit = defineEmits(['send', 'stop', 'cancel-interaction', 'update:draft', 'update:model'])
const inputRef = shallowRef(null)
const draft = computed({ get: () => props.draft, set: (value) => emit('update:draft', value) })

const effortLabel = computed(() => props.effort || 'default')
const canSend = computed(() => !props.disabled && !props.locked && Boolean(draft.value.trim()))

const providerLabel = computed(() => props.provider === 'gitee' ? 'Gitee' : 'GitHub')

function resizeTextarea() {
  const element = inputRef.value
  if (!element) return
  element.style.height = 'auto'
  element.style.height = `${Math.min(Math.max(element.scrollHeight, 60), 140)}px`
}

function send() {
  const content = draft.value.trim()
  if (!content || props.disabled || props.locked) return
  nextTick(resizeTextarea)
  emit('send', content)
}

function onKeydown(event) {
  if (event.isComposing) return
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    send()
  }
}

function onDraftInput() {
  resizeTextarea()
}

function stop() {
  emit('stop')
}

</script>

<template>
  <footer class="composer">
    <div v-if="lockedHint" class="composer-locked-hint" role="status">{{ lockedHint }}</div>
    <div v-if="interactionHint" class="composer-interaction-hint">
      <span>{{ interactionHint }}</span>
      <button type="button" aria-label="取消方案调整" @click="emit('cancel-interaction')">取消</button>
    </div>
    <textarea
      ref="inputRef"
      v-model="draft"
      :disabled="disabled || locked"
      :placeholder="locked ? '请先在人工介入卡片中答复…' : interactionHint ? '描述你希望如何调整方案…' : chatOnly ? '写下你的问题、想法，或想一起推敲的技术难题…' : '描述你希望 CODING 在仓库中完成的工作…'"
      aria-label="任务指令"
      @input="onDraftInput"
      @keydown="onKeydown"
    />

    <div class="composer-footer">
      <div class="composer-meta">
        <label class="model-picker" aria-label="选择模型">
          <span class="model-picker-orbit" aria-hidden="true">✳</span>
          <select :value="model" :disabled="disabled || models.length < 2" aria-label="选择模型" @change="emit('update:model', $event.target.value)">
            <option v-for="option in models" :key="option.id" :value="option.id">{{ option.label }}</option>
          </select>
          <span class="model-picker-chevron" aria-hidden="true">⌄</span>
        </label>
        <span class="meta-chip reasoning-meta"><span class="meta-label">推理</span>{{ effortLabel }}</span>
      </div>
      <div v-if="chatOnly" class="composer-chat-context"><span class="chat-context-dot"></span>普通聊天</div>
      <label v-else class="repo-control">
        <span class="repo-control-label">仓库</span>
        <span class="repo-control-input repo-control-fixed" :title="repo">
          <span class="sr-only">{{ providerLabel }} 仓库地址</span>
          <span class="repo-provider-label">{{ providerLabel }}</span>
          <span class="repo-fixed-name">{{ repo || '请先新建项目并选择仓库' }}</span>
        </span>
      </label>
      <button v-if="disabled" class="stop-button" type="button" @click="stop">
        <span aria-hidden="true">■</span>
        停止运行
      </button>
      <button v-else class="send-button" type="button" :disabled="!canSend" @click="send">
        发送
        <span aria-hidden="true">→</span>
      </button>
    </div>
  </footer>
</template>
