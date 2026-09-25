<script setup>
import { computed, shallowRef } from 'vue'
import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'

import TodoPlan from './TodoPlan.vue'
import ProposalCard from './ProposalCard.vue'
import HumanInterventionCard from './HumanInterventionCard.vue'

const props = defineProps({
  message: {
    type: Object,
    required: true,
  },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['plan-action', 'intervention-response'])

const userExpanded = shallowRef(false)

const markdown = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
})

markdown.renderer.rules.fence = (tokens, index) => {
  const token = tokens[index]
  const language = token.info.trim().split(/\s+/)[0] || 'text'
  const safeLanguage = markdown.utils.escapeHtml(language)
  const safeCode = markdown.utils.escapeHtml(token.content)

  return `<div class="code-window"><div class="code-window-header"><span class="code-window-language"><span class="code-window-icon" aria-hidden="true">&lt;/&gt;</span>${safeLanguage}</span><span class="code-window-actions"><span class="code-window-action" aria-hidden="true">↗</span><button type="button" class="code-window-action code-copy-action" data-code-action="copy" aria-label="复制代码">⧉</button></span></div><pre><code class="language-${safeLanguage}">${safeCode}</code></pre></div>`
}

function renderMarkdown(text) {
  return DOMPurify.sanitize(markdown.render(text || ''))
}

function textChunks() {
  return (props.message.chunks || []).filter((chunk) => chunk.kind === 'text')
}

const userText = computed(() => textChunks().map((chunk) => chunk.text || '').join('\n'))
const userLines = computed(() => userText.value.split(/\r?\n/))
const userHasMore = computed(() => userLines.value.length > 7)
const visibleUserText = computed(() => {
  if (!userHasMore.value || userExpanded.value) return userText.value
  return userLines.value.slice(0, 7).join('\n')
})

function toggleUserMessage() {
  userExpanded.value = !userExpanded.value
}

function todoChunks() {
  return (props.message.chunks || []).filter((chunk) => chunk.kind === 'todo')
}

function errorChunks() {
  return (props.message.chunks || []).filter((chunk) => chunk.kind === 'error')
}

function proposalChunks() {
  return (props.message.chunks || []).filter((chunk) => chunk.kind === 'proposal')
}

function interventionChunks() {
  return (props.message.chunks || []).filter((chunk) => chunk.kind === 'intervention')
}

function handleCodeClick(event) {
  const action = event.target.closest?.('[data-code-action="copy"]')
  if (!action) return

  const code = action.closest('.code-window')?.querySelector('code')?.textContent || ''
  if (!code || !navigator.clipboard) return

  navigator.clipboard.writeText(code).then(() => {
    action.textContent = '✓'
    window.setTimeout(() => {
      action.textContent = '⧉'
    }, 1200)
  }).catch(() => {})
}
</script>

<template>
  <article class="message" :class="`message-${message.author}`">
    <div v-if="message.author === 'user'" class="user-message-content">
      <div class="message-meta message-meta-user">
        <span class="message-avatar user-avatar" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <circle cx="12" cy="8" r="3.2" fill="currentColor" />
            <path d="M5.5 19.2c.7-3.1 3-5 6.5-5s5.8 1.9 6.5 5" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
          </svg>
        </span>
        <span>USER</span>
      </div>
      <div class="user-bubble">
        <div class="plain-text">{{ visibleUserText }}</div>
        <button
          v-if="userHasMore"
          type="button"
          class="message-expand-button"
          :aria-expanded="userExpanded"
          @click="toggleUserMessage"
        >
          <span>{{ userExpanded ? '收起' : '显示更多' }}</span>
          <span
            class="message-expand-chevron"
            :class="{ expanded: userExpanded }"
            aria-hidden="true"
          ></span>
        </button>
      </div>
    </div>

    <div v-else class="assistant-message-content">
      <div class="message-meta">
        <img class="message-avatar" src="/coding-mark.svg" alt="CODING" />
        <span>CODING</span>
      </div>
      <div class="assistant-message-body" @click="handleCodeClick">
        <div
          v-for="(chunk, index) in textChunks()"
          :key="`text-${index}`"
          class="markdown-body"
          v-html="renderMarkdown(chunk.text)"
        ></div>

        <TodoPlan
          v-for="(chunk, index) in todoChunks()"
          :key="`todo-${index}`"
          :todos="chunk.todos || []"
        />

        <ProposalCard
          v-for="proposal in proposalChunks()"
          :key="`proposal-${proposal.plan_id}`"
          :proposal="proposal"
          :disabled="disabled"
          @action="(action) => emit('plan-action', { action, proposal })"
        />

        <HumanInterventionCard
          v-for="intervention in interventionChunks()"
          :key="`intervention-${intervention.intervention_id}`"
          :intervention="intervention"
          :disabled="disabled"
          @respond="emit('intervention-response', $event)"
        />

        <div
          v-for="(chunk, index) in errorChunks()"
          :key="`error-${index}`"
          class="error-banner"
        >
          {{ chunk.text }}
        </div>
      </div>
    </div>
  </article>
</template>
