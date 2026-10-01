<script setup>
import { computed } from 'vue'

import UiButton from './ui/UiButton.vue'
import UiSelect from './ui/UiSelect.vue'
import UiTextarea from './ui/UiTextarea.vue'

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
const draft = computed({ get: () => props.draft, set: (value) => emit('update:draft', value) })

const effortLabel = computed(() => props.effort || 'default')
const canSend = computed(() => !props.disabled && !props.locked && Boolean(draft.value.trim()))

const providerLabel = computed(() => props.provider === 'gitee' ? 'Gitee' : 'GitHub')

function send() {
  const content = draft.value.trim()
  if (!content || props.disabled || props.locked) return
  emit('send', content)
}

function onKeydown(event) {
  if (event.isComposing) return
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    send()
  }
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
      <UiButton variant="ghost" size="sm" aria-label="取消方案调整" @click="emit('cancel-interaction')">取消</UiButton>
    </div>
    <UiTextarea
      v-model="draft"
      bare
      auto-resize
      :min-height="60"
      :max-height="140"
      :disabled="disabled || locked"
      :placeholder="locked ? '请先在人工介入卡片中答复…' : interactionHint ? '描述你希望如何调整方案…' : chatOnly ? '写下你的问题、想法，或想一起推敲的技术难题…' : '描述你希望 CODING 在仓库中完成的工作…'"
      aria-label="任务指令"
      @keydown="onKeydown"
    />

    <div class="composer-footer">
      <div class="composer-meta">
        <label class="model-picker" aria-label="选择模型">
          <UiSelect
            bare
            size="sm"
            :model-value="model"
            :options="models.map((option) => ({ value: option.id, label: option.label }))"
            :disabled="disabled || models.length < 2"
            aria-label="选择模型"
            @update:model-value="emit('update:model', $event)"
          >
            <template #prefix><span class="model-picker-orbit" aria-hidden="true">✳</span></template>
            <template #suffix><span class="model-picker-chevron" aria-hidden="true">⌄</span></template>
          </UiSelect>
        </label>
        <span class="meta-chip reasoning-meta"><span class="meta-label">推理</span>{{ effortLabel }}</span>
      </div>
      <div v-if="chatOnly" class="composer-chat-context"><span class="chat-context-dot"></span>普通聊天</div>
      <!--
        这里本来是 <label>，因为它以前包着一个真的 <input>。现在里面只有文字，
        没有表单控件 —— 一个不指向任何控件的 <label> 是错语义，所以换成 <span>。
        tabindex="0" 是为了让被 ellipsis 截断的长仓库名能用键盘聚焦、从而看到 title。
      -->
      <span v-else class="repo-control">
        <span class="repo-control-label">仓库</span>
        <span class="repo-control-input repo-control-fixed" tabindex="0" :title="repo">
          <span class="sr-only">{{ providerLabel }} 仓库地址</span>
          <span class="repo-provider-label">{{ providerLabel }}</span>
          <span class="repo-fixed-name">{{ repo || '请先新建项目并选择仓库' }}</span>
        </span>
      </span>
      <UiButton
        v-if="disabled"
        class="composer-action"
        variant="danger"
        size="md"
        @click="stop"
      >
        <span aria-hidden="true">■</span>
        停止运行
      </UiButton>
      <UiButton
        v-else
        class="composer-action"
        variant="primary"
        size="md"
        :disabled="!canSend"
        @click="send"
      >
        发送
        <span aria-hidden="true">→</span>
      </UiButton>
    </div>
  </footer>
</template>
