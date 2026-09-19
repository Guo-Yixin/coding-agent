<script setup>
import { computed, nextTick, shallowRef } from 'vue'

const props = defineProps({
  disabled: {
    type: Boolean,
    default: false,
  },
  model: {
    type: String,
    default: '',
  },
  effort: {
    type: String,
    default: 'default',
  },
  repo: {
    type: String,
    default: '',
  },
})

const emit = defineEmits(['send', 'stop', 'update:repo'])
const draft = shallowRef('')
const inputRef = shallowRef(null)

const modelLabel = computed(() => props.model || 'deepseek-v4-pro')
const effortLabel = computed(() => props.effort || 'default')
const canSend = computed(() => !props.disabled && Boolean(draft.value.trim()))

const giteeUrlPattern = /^https?:\/\/(?:www\.)?gitee\.com\/[\w.-]+\/[\w.-]+(?:\.git)?\/?$/i
const shortRepoPattern = /^[\w.-]+\/[\w.-]+$/

const repoStatus = computed(() => {
  const value = props.repo.trim()
  if (!value) return { label: '待填写', className: 'empty' }
  if (giteeUrlPattern.test(value) || shortRepoPattern.test(value)) {
    return { label: '已识别', className: 'ready' }
  }
  return { label: '检查地址', className: 'warning' }
})

function resizeTextarea() {
  const element = inputRef.value
  if (!element) return
  element.style.height = 'auto'
  element.style.height = `${Math.min(Math.max(element.scrollHeight, 60), 140)}px`
}

function send() {
  const content = draft.value.trim()
  if (!content || props.disabled) return
  draft.value = ''
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
    <textarea
      ref="inputRef"
      v-model="draft"
      :disabled="disabled"
      placeholder="描述你希望 CODING 完成的任务…"
      aria-label="任务指令"
      @input="onDraftInput"
      @keydown="onKeydown"
    />

    <div class="composer-footer">
      <div class="composer-meta">
        <span class="meta-chip"><span class="meta-label">模型</span>{{ modelLabel }}</span>
        <span class="meta-chip"><span class="meta-label">推理</span>{{ effortLabel }}</span>
      </div>
      <label class="repo-control">
        <span class="repo-control-label">Gitee</span>
        <span class="repo-control-input">
          <span class="sr-only">Gitee 仓库地址</span>
          <input
            :value="repo"
            :disabled="disabled"
            placeholder="owner/repo"
            aria-label="Gitee 仓库地址"
            @input="emit('update:repo', $event.target.value)"
          />
          <span class="repo-status" :class="repoStatus.className">
            <span class="repo-status-dot"></span>
            <span class="sr-only">{{ repoStatus.label }}</span>
          </span>
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
