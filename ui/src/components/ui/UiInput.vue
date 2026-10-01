<!-- 文本输入框：统一的高度/圆角/边框，支持尺寸、禁用、错误态与前缀/后缀插槽。 -->
<script setup>
defineOptions({ inheritAttrs: false })

defineProps({
  modelValue: { type: [String, Number], default: '' },
  placeholder: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
  invalid: { type: Boolean, default: false },
  /** 'sm' | 'md' */
  size: { type: String, default: 'md' },
  type: { type: String, default: 'text' },
  /** 透传 id，供外部 <label for> 关联 */
  id: { type: String, default: undefined },
})

const emit = defineEmits(['update:modelValue', 'focus', 'blur'])

function handleInput(event) {
  emit('update:modelValue', event.target.value)
}
</script>

<template>
  <div class="ui-input" :class="[`ui-input--${size}`, { 'is-disabled': disabled }]">
    <span v-if="$slots.prefix" class="ui-input__affix ui-input__affix--start">
      <slot name="prefix" />
    </span>

    <input
      v-bind="$attrs"
      class="ui-input__field"
      :class="{
        'is-invalid': invalid,
        'has-affix-start': Boolean($slots.prefix),
        'has-affix-end': Boolean($slots.suffix),
      }"
      :id="id"
      :type="type"
      :value="modelValue"
      :placeholder="placeholder"
      :disabled="disabled"
      :aria-invalid="invalid ? 'true' : undefined"
      @input="handleInput"
      @focus="emit('focus', $event)"
      @blur="emit('blur', $event)"
    />

    <span v-if="$slots.suffix" class="ui-input__affix ui-input__affix--end">
      <slot name="suffix" />
    </span>
  </div>
</template>

<style scoped>
.ui-input {
  position: relative;
  display: flex;
  align-items: center;
  width: 100%;
}

/* 边框与焦点环都放在 input 自身，避免出现「外层壳 + 内层焦点环」的双重描边 */
.ui-input__field {
  box-sizing: border-box;
  width: 100%;
  height: var(--control-h-md);
  padding-inline: var(--space-12);
  color: var(--c-text);
  background-color: var(--c-surface);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-sm);
  font-family: inherit;
  font-size: var(--text-base);
  line-height: var(--leading-normal);
  transition:
    background-color var(--dur-fast) var(--ease),
    border-color var(--dur-fast) var(--ease);
}

.ui-input__field::placeholder {
  color: var(--c-text-muted);
}

.ui-input__field:not(:disabled):hover {
  border-color: var(--c-border-strong);
}

.ui-input__field:focus {
  border-color: var(--c-accent);
}

/* 焦点必须始终可见：不使用 outline: none */
.ui-input__field:focus-visible {
  outline: 2px solid var(--c-accent);
  outline-offset: 2px;
}

.ui-input__field.is-invalid {
  border-color: var(--c-danger);
}

.ui-input__field.is-invalid:focus {
  border-color: var(--c-danger);
}

.ui-input__field.is-invalid:focus-visible {
  outline-color: var(--c-danger);
}

.ui-input__field:disabled {
  color: var(--c-text-muted);
  background-color: var(--c-bg-subtle);
  border-color: var(--c-border);
  cursor: not-allowed;
}

/* ---------- 尺寸（与 UiSelect 完全同源） ---------- */
.ui-input--sm .ui-input__field {
  height: var(--control-h-sm);
  font-size: var(--text-sm);
}

.ui-input--md .ui-input__field {
  height: var(--control-h-md);
  font-size: var(--text-base);
}

/* ---------- 前后缀插槽 ---------- */
.ui-input__affix {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1em;
  height: 1em;
  color: var(--c-text-muted);
  pointer-events: none;
}

/* 容器不拦截点击（点击图标也能聚焦输入框），交互式子元素再恢复点击 */
.ui-input__affix > * {
  pointer-events: auto;
}

.ui-input__affix--start {
  inset-inline-start: var(--space-12);
}

.ui-input__affix--end {
  inset-inline-end: var(--space-12);
}

.ui-input__field.has-affix-start {
  padding-inline-start: calc(var(--space-12) + 1em + var(--space-8));
}

.ui-input__field.has-affix-end {
  padding-inline-end: calc(var(--space-12) + 1em + var(--space-8));
}

.ui-input.is-disabled .ui-input__affix {
  opacity: 0.6;
}
</style>
