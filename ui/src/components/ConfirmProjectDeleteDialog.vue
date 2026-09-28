<script setup>
import { ref } from 'vue'

const props = defineProps({
  project: { type: Object, required: true },
  busy: { type: Boolean, default: false },
  errorMessage: { type: String, default: '' },
})
const emit = defineEmits(['close', 'confirm'])
const confirmation = ref('')

function confirm() {
  if (confirmation.value.trim() !== props.project.name) return
  emit('confirm')
}
</script>

<template>
  <div class="dialog-backdrop" @click.self="!busy && emit('close')" @keydown.esc.stop="!busy && emit('close')">
    <section class="surface-dialog delete-dialog" role="alertdialog" aria-modal="true" aria-labelledby="delete-project-title" aria-describedby="delete-project-description">
      <div class="danger-icon" aria-hidden="true">!</div>
      <p class="dialog-kicker">不可撤销的操作</p>
      <h2 id="delete-project-title">删除“{{ project.name }}”？</h2>
      <p id="delete-project-description" class="delete-description">此操作会永久删除该项目及其 <strong>{{ project.conversations?.length || 0 }} 个会话</strong>，包括聊天记录、运行记录和草稿。仓库代码不会被删除。</p>
      <label class="field-label" for="confirm-project-name">输入项目名称以确认</label>
      <input id="confirm-project-name" v-model="confirmation" class="dialog-input" autocomplete="off" autofocus :placeholder="project.name" @keydown.enter.prevent="confirm" />
      <p v-if="errorMessage" class="dialog-error" role="alert">{{ errorMessage }}</p>
      <div class="dialog-actions">
        <button class="button-secondary" type="button" :disabled="busy" @click="emit('close')">保留项目</button>
        <button class="button-danger" type="button" :disabled="busy || confirmation.trim() !== project.name" @click="confirm">{{ busy ? '正在删除…' : '删除项目及所有会话' }}</button>
      </div>
    </section>
  </div>
</template>
