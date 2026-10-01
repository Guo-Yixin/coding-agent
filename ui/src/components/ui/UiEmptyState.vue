<!-- 空状态占位：让「没有数据时的界面」有一致的、体面的默认形态。 -->
<script setup>
defineProps({
  title: { type: String, required: true },
  description: { type: String, default: '' },
})
</script>

<template>
  <div class="ui-empty">
    <div class="ui-empty__icon">
      <slot name="icon">
        <span class="ui-empty__placeholder" aria-hidden="true">
          <span class="ui-empty__placeholder-dot"></span>
        </span>
      </slot>
    </div>

    <p class="ui-empty__title">{{ title }}</p>
    <p v-if="description" class="ui-empty__description">{{ description }}</p>

    <div v-if="$slots.actions" class="ui-empty__actions">
      <slot name="actions" />
    </div>
  </div>
</template>

<style scoped>
.ui-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-12);
  padding-block: var(--space-32);
  padding-inline: var(--space-16);
  text-align: center;
}

.ui-empty__icon {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--c-text-muted);
}

/* 默认圆形占位（未提供 icon 插槽时） */
.ui-empty__placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  width: var(--space-48);
  height: var(--space-48);
  border-radius: var(--radius-full);
  background-color: var(--c-bg-subtle);
  color: var(--c-text-muted);
}

.ui-empty__placeholder-dot {
  width: var(--space-8);
  height: var(--space-8);
  border-radius: var(--radius-full);
  background-color: currentColor;
}

.ui-empty__title {
  margin: 0;
  font-size: var(--text-md);
  font-weight: 600;
  line-height: var(--leading-snug);
  color: var(--c-text);
}

.ui-empty__description {
  margin: 0;
  font-size: var(--text-base);
  line-height: var(--leading-normal);
  color: var(--c-text-secondary);
}

.ui-empty__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: var(--space-8);
  margin-block-start: var(--space-8);
}
</style>
