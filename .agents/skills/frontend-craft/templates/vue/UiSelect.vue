<!-- 原生 select 封装：与 UiInput 同源的高度/圆角/边框，自绘箭头，兼容字符串数组选项。 -->
<script setup>
import { computed } from 'vue'

defineOptions({ inheritAttrs: false })

const props = defineProps({
  modelValue: { type: [String, Number], default: '' },
  /** [{ value, label }] 或 ['a', 'b'] 均可 */
  options: { type: Array, default: () => [] },
  disabled: { type: Boolean, default: false },
  /** 'sm' | 'md' */
  size: { type: String, default: 'md' },
  /** 透传 id，供外部 <label for> 关联 */
  id: { type: String, default: undefined },
  placeholder: { type: String, default: '' },
})

const emit = defineEmits(['update:modelValue'])

// 对字符串数组 / 缺字段的对象做容错归一化
const normalizedOptions = computed(() =>
  (props.options || []).map((option) => {
    if (option !== null && typeof option === 'object') {
      const value = 'value' in option ? option.value : option.label
      const label = 'label' in option ? option.label : value
      return { value, label: label === null || label === undefined ? '' : String(label) }
    }
    return { value: option, label: option === null || option === undefined ? '' : String(option) }
  }),
)

const isPlaceholder = computed(
  () => props.placeholder !== '' && (props.modelValue === '' || props.modelValue === null || props.modelValue === undefined),
)

// 原生 select 只回传字符串：数值型 value 由调用方自行转换
function handleChange(event) {
  emit('update:modelValue', event.target.value)
}
</script>

<template>
  <div
    class="ui-select"
    :class="[`ui-select--${size}`, { 'is-disabled': disabled, 'is-placeholder': isPlaceholder }]"
  >
    <select
      v-bind="$attrs"
      class="ui-select__field"
      :id="id"
      :value="modelValue"
      :disabled="disabled"
      @change="handleChange"
    >
      <!-- 占位项用空 value + disabled：可展示提示，但不会被当成一个真实可选值提交 -->
      <option v-if="placeholder" value="" disabled>{{ placeholder }}</option>
      <option v-for="option in normalizedOptions" :key="String(option.value)" :value="option.value">
        {{ option.label }}
      </option>
    </select>
  </div>
</template>

<style scoped>
.ui-select {
  position: relative;
  display: flex;
  align-items: center;
  width: 100%;
}

/* 与 UiInput 完全一致：同源高度 / 圆角 / 边框，保证同一行控件视觉重量相同 */
.ui-select__field {
  box-sizing: border-box;
  width: 100%;
  height: var(--control-h-md);
  padding-inline: var(--space-12) calc(var(--space-12) + 1em);
  color: var(--c-text);
  background-color: var(--c-surface);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-sm);
  font-family: inherit;
  font-size: var(--text-base);
  line-height: var(--leading-normal);
  appearance: none;
  -webkit-appearance: none;
  cursor: pointer;
  transition:
    background-color var(--dur-fast) var(--ease),
    border-color var(--dur-fast) var(--ease);
}

/* 展开列表里的文字保持正常颜色，不被占位态灰字影响 */
.ui-select__field option {
  color: var(--c-text);
  background-color: var(--c-surface);
}

.ui-select__field:not(:disabled):hover {
  border-color: var(--c-border-strong);
}

.ui-select__field:focus {
  border-color: var(--c-accent);
}

/* 焦点必须始终可见：不使用 outline: none */
.ui-select__field:focus-visible {
  outline: 2px solid var(--c-accent);
  outline-offset: 2px;
}

.ui-select__field:disabled {
  color: var(--c-text-muted);
  background-color: var(--c-bg-subtle);
  border-color: var(--c-border);
  cursor: not-allowed;
}

.ui-select.is-placeholder .ui-select__field {
  color: var(--c-text-muted);
}

.ui-select.is-disabled .ui-select__field {
  color: var(--c-text-muted);
}

/* ---------- 尺寸（与 UiInput 完全同源） ---------- */
.ui-select--sm .ui-select__field {
  height: var(--control-h-sm);
  font-size: var(--text-sm);
}

.ui-select--md .ui-select__field {
  height: var(--control-h-md);
  font-size: var(--text-base);
}

/* ---------- 自绘下拉箭头（颜色跟随 --c-text-muted） ---------- */
.ui-select::after {
  content: '';
  position: absolute;
  inset-inline-end: var(--space-12);
  top: 50%;
  width: 0.4em;
  height: 0.4em;
  border-right: 1px solid var(--c-text-muted);
  border-bottom: 1px solid var(--c-text-muted);
  transform: translateY(-70%) rotate(45deg);
  pointer-events: none;
}

.ui-select.is-disabled::after {
  opacity: 0.6;
}
</style>
