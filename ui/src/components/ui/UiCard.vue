<!-- 卡片容器：统一的表面/边框/圆角/阴影，可选页头页脚分隔线与三档内边距。 -->
<script setup>
defineProps({
  /** 'none' | 'sm' | 'md' */
  padding: { type: String, default: 'md' },
})
</script>

<template>
  <section class="ui-card" :class="`ui-card--pad-${padding}`">
    <header v-if="$slots.header" class="ui-card__header">
      <slot name="header" />
    </header>

    <div class="ui-card__body">
      <slot />
    </div>

    <footer v-if="$slots.footer" class="ui-card__footer">
      <slot name="footer" />
    </footer>
  </section>
</template>

<style scoped>
.ui-card {
  color: var(--c-text);
  background-color: var(--c-surface);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-xs);
  line-height: var(--leading-normal);
}

.ui-card__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-12);
  font-size: var(--text-md);
  font-weight: 600;
  line-height: var(--leading-snug);
  border-bottom: 1px solid var(--c-border);
}

.ui-card__body {
  font-size: var(--text-base);
}

.ui-card__footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--space-12);
  font-size: var(--text-base);
  color: var(--c-text-secondary);
  border-top: 1px solid var(--c-border);
}

/* ---------- 内边距三档：none → 0，sm → --space-12，md → --space-16 ---------- */
.ui-card--pad-none > .ui-card__header,
.ui-card--pad-none > .ui-card__body,
.ui-card--pad-none > .ui-card__footer {
  padding: 0;
}

.ui-card--pad-sm > .ui-card__header,
.ui-card--pad-sm > .ui-card__body,
.ui-card--pad-sm > .ui-card__footer {
  padding: var(--space-12);
}

.ui-card--pad-md > .ui-card__header,
.ui-card--pad-md > .ui-card__body,
.ui-card--pad-md > .ui-card__footer {
  padding: var(--space-16);
}
</style>
