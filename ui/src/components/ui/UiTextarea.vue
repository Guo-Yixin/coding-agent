<!-- 多行文本域：与 UiInput / UiSelect 同源的高度、圆角、边框与焦点环。

     两种形态：
     - 默认（有框）：自己带边框与焦点环，用于表单。
     - bare（无框）：去掉边框与背景，把「框」交给外层容器，由容器用 :focus-within 表达焦点。
       用于 composer 这种「整张卡片就是输入区」的场景。bare 形态下仍然不使用 outline: none，
       焦点环由容器提供 —— 见 ChatComposer 的 .composer:focus-within。 -->
<script setup>
import { nextTick, onMounted, ref, watch } from 'vue'

defineOptions({ inheritAttrs: false })

const props = defineProps({
  modelValue: { type: [String, Number], default: '' },
  placeholder: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
  invalid: { type: Boolean, default: false },
  /** 'sm' | 'md' */
  size: { type: String, default: 'md' },
  rows: { type: Number, default: 3 },
  /** 无框形态：边框与背景交给外层容器，焦点也由容器表达 */
  bare: { type: Boolean, default: false },
  /** 随内容自动增高。为 true 时 minHeight / maxHeight 生效 */
  autoResize: { type: Boolean, default: false },
  /** 自动增高的下限（px）。null 表示用 CSS 默认值 */
  minHeight: { type: Number, default: null },
  /** 自动增高的上限（px）。null 表示不设上限 */
  maxHeight: { type: Number, default: null },
  /** 透传 id，供外部 <label for> 关联 */
  id: { type: String, default: undefined },
})

const emit = defineEmits(['update:modelValue', 'focus', 'blur'])

const fieldRef = ref(null)

/** 先清成 auto 再读 scrollHeight，否则高度只能单向增长 */
function syncHeight() {
  const element = fieldRef.value
  if (!element || !props.autoResize) return
  element.style.height = 'auto'
  const min = props.minHeight ?? element.scrollHeight
  const max = props.maxHeight ?? element.scrollHeight
  element.style.height = `${Math.min(Math.max(element.scrollHeight, min), max)}px`
}

// 外部改 draft（例如发送后清空）也要跟着回缩
watch(() => props.modelValue, () => nextTick(syncHeight))
onMounted(syncHeight)

function handleInput(event) {
  emit('update:modelValue', event.target.value)
  syncHeight()
}

defineExpose({ syncHeight })
</script>

<template>
  <div class="ui-textarea" :class="[`ui-textarea--${size}`, { 'is-bare': bare, 'is-disabled': disabled }]">
    <textarea
      ref="fieldRef"
      v-bind="$attrs"
      class="ui-textarea__field"
      :class="{ 'is-invalid': invalid }"
      :id="id"
      :value="modelValue"
      :rows="bare ? 1 : rows"
      :placeholder="placeholder"
      :disabled="disabled"
      :aria-invalid="invalid ? 'true' : undefined"
      :style="autoResize && maxHeight !== null ? { maxHeight: `${maxHeight}px` } : undefined"
      @input="handleInput"
      @focus="emit('focus', $event)"
      @blur="emit('blur', $event)"
    />
  </div>
</template>

<style scoped>
.ui-textarea {
  position: relative;
  display: flex;
  width: 100%;
}

/* 边框与焦点环都放在 textarea 自身，避免「外层壳 + 内层焦点环」的双重描边 */
.ui-textarea__field {
  box-sizing: border-box;
  width: 100%;
  padding: var(--space-8) var(--space-12);
  color: var(--c-text);
  background-color: var(--c-surface);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-sm);
  font-family: inherit;
  font-size: var(--text-base);
  line-height: var(--leading-normal);
  resize: vertical;
  transition:
    background-color var(--dur-fast) var(--ease),
    border-color var(--dur-fast) var(--ease);
}

.ui-textarea__field::placeholder {
  color: var(--c-text-muted);
}

.ui-textarea__field:not(:disabled):hover {
  border-color: var(--c-border-strong);
}

.ui-textarea__field:focus {
  border-color: var(--c-accent);
}

/* 焦点必须始终可见：不使用 outline: none */
.ui-textarea__field:focus-visible {
  outline: 2px solid var(--c-accent);
  outline-offset: 2px;
}

.ui-textarea__field.is-invalid {
  border-color: var(--c-danger);
}

.ui-textarea__field.is-invalid:focus-visible {
  outline-color: var(--c-danger);
}

.ui-textarea__field:disabled {
  color: var(--c-text-muted);
  background-color: var(--c-bg-subtle);
  border-color: var(--c-border);
  cursor: not-allowed;
}

/* ---------- 尺寸（与 UiInput / UiSelect 完全同源） ---------- */
.ui-textarea--sm .ui-textarea__field {
  font-size: var(--text-sm);
}

.ui-textarea--md .ui-textarea__field {
  font-size: var(--text-base);
}

/* ---------- 无框形态 ----------
   这里去掉的是边框与背景，不是焦点。 */
.ui-textarea.is-bare .ui-textarea__field {
  padding: 0;
  background-color: transparent;
  border: 0;
  resize: none;
}

.ui-textarea.is-bare .ui-textarea__field:hover {
  border-color: transparent;
}

/* bare 形态下焦点环由外层容器提供（composer 的 .composer:focus-within）。
   必须压掉 textarea 自己的默认环，否则同一个控件上会出现两圈。
   这是全项目唯一被允许写 outline: none 的地方 —— 用 disable 注释让它可被 grep 到，
   规则本身保持硬性，例外只有这一处、且带理由。 */
.ui-textarea.is-bare .ui-textarea__field:focus-visible {
  /* stylelint-disable-next-line declaration-property-value-disallowed-list */
  outline: none;
}
</style>
