<script setup>
import { computed } from 'vue'
import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'

const props = defineProps({
  proposal: { type: Object, required: true },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['action'])

const markdown = new MarkdownIt({ html: false, linkify: true, breaks: true })
const body = computed(() => DOMPurify.sanitize(markdown.render(props.proposal.plan_text || '')))
const statusLabel = computed(() => ({
  pending: '待你确认', approved: '已批准实施', rejected: '已拒绝', superseded: '已由新方案替代',
}[props.proposal.status] || '方案'))
</script>

<template>
  <section class="proposal-card" :aria-label="`实施方案 V${proposal.version || 1}`">
    <header class="proposal-card-header">
      <div>
        <span class="proposal-eyebrow">实施方案 · V{{ proposal.version || 1 }}</span>
        <h3>请确认实施范围</h3>
      </div>
      <span class="proposal-status" :class="`proposal-status-${proposal.status || 'pending'}`">{{ statusLabel }}</span>
    </header>
    <div class="proposal-card-content markdown-body" v-html="body"></div>
    <footer v-if="proposal.status === 'pending'" class="proposal-actions">
      <button class="proposal-button proposal-button-primary" type="button" :disabled="disabled" @click="emit('action', 'approve')">
        确认并实施
      </button>
      <button class="proposal-button" type="button" :disabled="disabled" @click="emit('action', 'revise')">调整方案</button>
      <button class="proposal-button proposal-button-muted" type="button" :disabled="disabled" @click="emit('action', 'reject')">
        拒绝实施
      </button>
    </footer>
  </section>
</template>
