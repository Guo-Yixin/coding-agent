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
  provider: {
    type: String,
    default: 'github',
  },
  providers: {
    type: Array,
    default: () => [],
  },
})

const emit = defineEmits(['send', 'stop', 'update:repo', 'update:provider'])
const draft = shallowRef('')
const inputRef = shallowRef(null)

const modelLabel = computed(() => props.model || 'deepseek-v4-pro')
const effortLabel = computed(() => props.effort || 'default')
const canSend = computed(() => !props.disabled && Boolean(draft.value.trim()))

const githubUrlPattern = /^https?:\/\/(?:www\.)?github\.com\/[\w.-]+\/[\w.-]+(?:\.git)?\/?$/i
const giteeUrlPattern = /^https?:\/\/(?:www\.)?gitee\.com\/[\w.-]+\/[\w.-]+(?:\.git)?\/?$/i
const shortRepoPattern = /^[\w.-]+\/[\w.-]+$/

const providerLabel = computed(() => {
  const selected = props.providers.find((item) => item.id === props.provider)
  return selected?.label || (props.provider === 'gitee' ? 'Gitee' : 'GitHub')
})
const repoPlaceholder = computed(() => {
  const selected = props.providers.find((item) => item.id === props.provider)
  return selected?.url_placeholder || `${props.provider === 'gitee' ? 'https://gitee.com' : 'https://github.com'}/owner/repo`
})

const repoStatus = computed(() => {
  const value = props.repo.trim()
  if (!value) return { label: '待填写', className: 'empty' }
  if (githubUrlPattern.test(value) || giteeUrlPattern.test(value) || shortRepoPattern.test(value)) {
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

function changeProvider(event) {
  const nextProvider = event.target.value
  emit('update:provider', nextProvider)
  const current = props.repo.trim().toLowerCase()
  const isGithubUrl = current.includes('github.com/')
  const isGiteeUrl = current.includes('gitee.com/')
  if ((nextProvider === 'github' && isGiteeUrl) || (nextProvider === 'gitee' && isGithubUrl)) {
    emit('update:repo', '')
  }
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
        <span class="repo-control-label">仓库</span>
        <select
          class="repo-provider-select"
          :value="provider"
          :disabled="disabled"
          aria-label="仓库平台"
          @change="changeProvider"
        >
          <option v-for="item in providers" :key="item.id" :value="item.id">
            {{ item.label }}
          </option>
          <option v-if="!providers.length" value="github">GitHub</option>
          <option v-if="!providers.length" value="gitee">Gitee</option>
        </select>
        <span class="repo-control-input">
          <span class="sr-only">{{ providerLabel }} 仓库地址</span>
          <input
            :value="repo"
            :disabled="disabled"
            :placeholder="repoPlaceholder"
            :aria-label="`${providerLabel} 仓库地址`"
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
