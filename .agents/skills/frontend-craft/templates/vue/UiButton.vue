<!-- 通用按钮：四种语义变体 × 三种尺寸，支持加载态、块级布局与禁用。 -->
<script setup>
import { computed } from 'vue'

const props = defineProps({
  /** 'primary' | 'secondary' | 'ghost' | 'danger' */
  variant: { type: String, default: 'primary' },
  /** 'sm' | 'md' | 'lg' */
  size: { type: String, default: 'md' },
  disabled: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  block: { type: Boolean, default: false },
  type: { type: String, default: 'button' },
})

// 加载中即视为禁用，避免重复提交
const isDisabled = computed(() => props.disabled || props.loading)
</script>

<template>
  <button
    class="ui-btn"
    :class="[`ui-btn--${variant}`, `ui-btn--${size}`, { 'is-block': block }]"
    :type="type"
    :disabled="isDisabled"
    :aria-busy="loading ? 'true' : undefined"
  >
    <span v-if="loading" class="ui-btn__spinner" aria-hidden="true"></span>
    <slot />
  </button>
</template>

<style scoped>
.ui-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-8);
  box-sizing: border-box;
  height: var(--control-h-md);
  padding-inline: var(--space-16);
  border-width: 1px;
  border-style: solid;
  border-color: transparent;
  border-radius: var(--radius-sm);
  font-family: inherit;
  font-size: var(--text-base);
  font-weight: 500;
  line-height: var(--leading-tight);
  white-space: nowrap;
  cursor: pointer;
  user-select: none;
  transition:
    background-color var(--dur-fast) var(--ease),
    border-color var(--dur-fast) var(--ease),
    color var(--dur-fast) var(--ease);
}

/* 焦点必须始终可见：不使用 outline: none */
.ui-btn:focus-visible {
  outline: 2px solid var(--c-accent);
  outline-offset: 2px;
}

.ui-btn:disabled {
  cursor: not-allowed;
}

/* ---------- 尺寸 ---------- */
.ui-btn--sm {
  height: var(--control-h-sm);
  padding-inline: var(--space-12);
  font-size: var(--text-sm);
}

.ui-btn--md {
  height: var(--control-h-md);
  padding-inline: var(--space-16);
  font-size: var(--text-base);
}

.ui-btn--lg {
  height: var(--control-h-lg);
  padding-inline: var(--space-24);
  font-size: var(--text-md);
}

.is-block {
  display: flex;
  width: 100%;
}

/* ---------- primary ---------- */
.ui-btn--primary {
  color: var(--c-text-inverse);
  background-color: var(--c-accent);
  border-color: var(--c-accent);
}

.ui-btn--primary:not(:disabled):hover {
  background-color: var(--c-accent-hover);
  border-color: var(--c-accent-hover);
}

.ui-btn--primary:not(:disabled):active {
  background-color: var(--c-accent-active);
  border-color: var(--c-accent-active);
}

.ui-btn--primary:disabled {
  color: var(--c-text-muted);
  background-color: var(--c-accent-subtle);
  border-color: transparent;
}

/* ---------- secondary ---------- */
.ui-btn--secondary {
  color: var(--c-text);
  background-color: var(--c-surface);
  border-color: var(--c-border);
}

.ui-btn--secondary:not(:disabled):hover {
  background-color: var(--c-surface-hover);
  border-color: var(--c-border-strong);
}

.ui-btn--secondary:not(:disabled):active {
  background-color: var(--c-bg-subtle);
  border-color: var(--c-border-strong);
}

.ui-btn--secondary:disabled {
  color: var(--c-text-muted);
  background-color: var(--c-bg-subtle);
  border-color: var(--c-border);
}

/* ---------- ghost ---------- */
.ui-btn--ghost {
  color: var(--c-text-secondary);
  background-color: transparent;
  border-color: transparent;
}

.ui-btn--ghost:not(:disabled):hover {
  color: var(--c-text);
  background-color: var(--c-surface-hover);
}

.ui-btn--ghost:not(:disabled):active {
  color: var(--c-text);
  background-color: var(--c-bg-subtle);
}

.ui-btn--ghost:disabled {
  color: var(--c-text-muted);
  background-color: transparent;
}

/* ---------- danger ---------- */
/* 令牌集没有 --c-danger-hover / --c-danger-active，故用「浅底 → 实心 → 浅底」
   构成 hover / active 的可见差异，而不是自己发明颜色。 */
.ui-btn--danger {
  color: var(--c-danger);
  background-color: var(--c-danger-subtle);
  border-color: var(--c-danger);
}

.ui-btn--danger:not(:disabled):hover {
  color: var(--c-text-inverse);
  background-color: var(--c-danger);
  border-color: var(--c-danger);
}

.ui-btn--danger:not(:disabled):active {
  color: var(--c-danger);
  background-color: var(--c-danger-subtle);
  border-color: var(--c-danger);
}

.ui-btn--danger:disabled {
  color: var(--c-text-muted);
  background-color: var(--c-bg-subtle);
  border-color: var(--c-border);
}

/* ---------- 加载指示器（纯 CSS，跟随 currentColor） ---------- */
.ui-btn__spinner {
  flex: none;
  width: 1em;
  height: 1em;
  border: 0.125em solid currentColor;
  border-top-color: transparent;
  border-radius: 50%;
  animation: ui-btn-spin calc(var(--dur-base) * 3) linear infinite;
}

@keyframes ui-btn-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
