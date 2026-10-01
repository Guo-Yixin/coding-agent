<!-- 状态徽标：浅底 + 深字五种色调、两种尺寸，纯展示不承担按钮语义。 -->
<script setup>
defineProps({
  /** 'neutral' | 'accent' | 'success' | 'warning' | 'danger' */
  tone: { type: String, default: 'neutral' },
  /** 'sm' | 'md' */
  size: { type: String, default: 'sm' },
})
</script>

<template>
  <span class="ui-badge" :class="[`ui-badge--${tone}`, `ui-badge--${size}`]">
    <slot />
  </span>
</template>

<style scoped>
.ui-badge {
  display: inline-flex;
  align-items: center;
  gap: var(--space-4);
  padding-block: var(--space-4);
  padding-inline: var(--space-8);
  border-radius: var(--radius-full);
  font-size: var(--text-xs);
  font-weight: 500;
  line-height: var(--leading-tight);
  white-space: nowrap;
}

/* ---------- 尺寸 ---------- */
.ui-badge--sm {
  padding-inline: var(--space-8);
  font-size: var(--text-xs);
}

.ui-badge--md {
  padding-inline: var(--space-12);
  font-size: var(--text-sm);
}

/* ---------- 色调：一律「浅底 + 深字」，不用实心 accent + 反白 ---------- */
.ui-badge--neutral {
  color: var(--c-text-secondary);
  background-color: var(--c-bg-subtle);
}

.ui-badge--accent {
  color: var(--c-accent);
  background-color: var(--c-accent-subtle);
}

.ui-badge--success {
  color: var(--c-success);
  background-color: var(--c-success-subtle);
}

.ui-badge--warning {
  color: var(--c-warning);
  background-color: var(--c-warning-subtle);
}

.ui-badge--danger {
  color: var(--c-danger);
  background-color: var(--c-danger-subtle);
}
</style>
