<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  intervention: { type: Object, required: true },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['respond'])
const response = ref('')
const pending = computed(() => ['pending', 'resuming'].includes(props.intervention.status))
const canRespond = computed(() => props.intervention.status === 'pending' && !props.disabled)

function submit() {
  const value = response.value.trim()
  if (!value || !canRespond.value) return
  emit('respond', { intervention_id: props.intervention.intervention_id, response: value })
  response.value = ''
}
</script>

<template>
  <section class="intervention-card" :class="{ 'intervention-card-resolved': !pending }">
    <header class="intervention-card-header">
      <span class="intervention-icon" aria-hidden="true">?</span>
      <div>
            <strong>{{ props.intervention.status === 'resuming' ? '正在恢复处理中' : pending ? '需要你确认后继续' : '人工确认记录' }}</strong>
        <p>{{ intervention.reason }}</p>
      </div>
    </header>
    <h4>{{ intervention.question }}</h4>
    <div v-if="intervention.options?.length" class="intervention-options">
      <button
        v-for="option in intervention.options"
        :key="option"
        type="button"
        :disabled="!canRespond"
        @click="response = option"
      >{{ option }}</button>
    </div>
    <p v-if="props.intervention.status === 'resuming'" class="intervention-complete">答复已收到，正在从原任务断点继续。</p>
    <form v-else-if="pending" class="intervention-reply" @submit.prevent="submit">
      <textarea v-model="response" :disabled="!canRespond" rows="2" placeholder="输入你的决定或补充说明…" aria-label="人工介入答复" />
      <button type="submit" :disabled="!response.trim() || !canRespond">答复并继续</button>
    </form>
    <p v-else class="intervention-complete">已收到答复，Agent 已继续处理。</p>
  </section>
</template>
