<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  project: { type: Object, default: null },
  busy: { type: Boolean, default: false },
  errorMessage: { type: String, default: '' },
})
const emit = defineEmits(['close', 'save'])

const name = ref(props.project?.name || '')
const provider = ref(props.project?.provider || 'github')
const repo = ref('')
const error = ref('')
const editing = computed(() => Boolean(props.project))
const repoPlaceholder = computed(() => provider.value === 'github'
  ? 'https://github.com/owner/repo'
  : 'https://gitee.com/owner/repo')

watch(() => props.project, (project) => {
  name.value = project?.name || ''
  provider.value = project?.provider || 'github'
  repo.value = ''
})

function submit() {
  if (!name.value.trim()) { error.value = '请填写项目名称'; return }
  if (!editing.value && !repo.value.trim()) { error.value = '请填写仓库地址'; return }
  error.value = ''
  emit('save', editing.value
    ? { id: props.project.id, name: name.value.trim() }
    : { name: name.value.trim(), provider: provider.value, repo: repo.value.trim() })
}

function onKeydown(event) {
  if (event.key === 'Escape' && !props.busy) emit('close')
}
</script>

<template>
  <div class="dialog-backdrop" @click.self="!busy && emit('close')" @keydown="onKeydown">
    <form class="surface-dialog project-dialog-v2" aria-label="项目设置" @submit.prevent="submit">
      <div class="dialog-icon" aria-hidden="true">⌘</div>
      <div class="dialog-heading">
        <p class="dialog-kicker">CODING WORKSPACE</p>
        <h2>{{ editing ? '重命名项目' : '创建开发项目' }}</h2>
        <p>{{ editing ? '项目名称会同步更新到侧栏。仓库绑定保持不变。' : '为一个代码仓库建立独立工作空间，后续会话自动继承该仓库。' }}</p>
      </div>

      <label class="field-label" for="project-name">项目名称</label>
      <input id="project-name" v-model="name" class="dialog-input" maxlength="80" autofocus placeholder="例如：产品官网重构" />

      <template v-if="!editing">
        <label class="field-label" for="project-provider">代码托管平台</label>
        <select id="project-provider" v-model="provider" class="dialog-input">
          <option value="github">GitHub</option>
          <option value="gitee">Gitee</option>
        </select>
        <label class="field-label" for="project-repo">仓库地址</label>
        <input id="project-repo" v-model="repo" class="dialog-input" :placeholder="repoPlaceholder" />
        <p class="dialog-hint">项目创建后，仓库地址将固定应用于项目中的所有会话。</p>
      </template>
      <div v-else class="bound-repository"><span class="bound-repository-mark">{{ project.provider === 'gitee' ? 'G' : 'GH' }}</span><span><strong>{{ project.provider === 'gitee' ? 'Gitee' : 'GitHub' }}</strong><small>{{ project.repoFullName || project.repo }}</small></span><span class="lock-mark" aria-label="仓库固定">⌑</span></div>

      <p v-if="error || errorMessage" class="dialog-error" role="alert">{{ error || errorMessage }}</p>
      <div class="dialog-actions">
        <button class="button-secondary" type="button" :disabled="busy" @click="emit('close')">取消</button>
        <button class="button-primary" type="submit" :disabled="busy">{{ busy ? '正在保存…' : editing ? '保存名称' : '创建项目' }}</button>
      </div>
    </form>
  </div>
</template>
