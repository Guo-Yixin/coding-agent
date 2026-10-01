<script setup>
import UiButton from './ui/UiButton.vue'

defineProps({
  tasks: { type: Array, default: () => [] },
  activeId: { type: String, default: null },
})

const emit = defineEmits(['select', 'cancel'])

function label(status) {
  if (status === 'queued') return '排队中'
  if (status === 'cancelling') return '正在取消'
  return '运行中'
}
</script>

<template>
  <nav v-if="tasks.length" class="active-task-strip" aria-label="活跃任务">
    <span class="active-task-heading">活跃任务</span>
    <div class="active-task-list">
      <div v-for="task in tasks" :key="task.id" class="active-task-item" :class="{ selected: task.id === activeId }">
        <button class="active-task-select" type="button" @click="emit('select', task.id)">
          <span class="status-dot" :class="task.status"></span>
          <span class="active-task-title">{{ task.title || task.repoFullName || '新任务' }}</span>
          <small>{{ label(task.status) }}</small>
        </button>
        <!--
          没有 runId 就**不渲染**取消键，而不是渲染一个禁用的键：
          本地拿不到 run 就没有可取消的对象，这个条目此刻真的没有这个动作。
        -->
        <UiButton
          v-if="task.runId"
          class="active-task-cancel"
          variant="ghost"
          size="sm"
          icon
          type="button"
          :aria-label="`取消${task.title || '任务'}`"
          title="取消任务"
          @click="emit('cancel', { threadId: task.id, runId: task.runId })"
        >×</UiButton>
      </div>
    </div>
  </nav>
</template>

<style scoped>
/*
 * 这个组件原先写的是 var(--border-color, #e5e7eb) / var(--muted-color, #737373)
 * / var(--accent-color, #6366f1) —— 三个变量在 tokens.css 里**根本不存在**，
 * 所以实际渲染出来的一直是 fallback：Tailwind 的 gray-200 / neutral-500 /
 * indigo-500。这是全项目最后残留的外来配色，也是"AI 默认值"最典型的形态：
 * 写了一个看起来像设计系统的变量名，却没人核对它是否存在。
 * 现在全部换成真实 token。
 *
 * 这是全项目唯一带 scoped <style> 的组件。写法沿用原语那一套（规则之间空行、
 * 状态按 default → hover → focus → selected 排序），这样它也过得了 npm run lint:css:all。
 */
.active-task-strip {
  display: flex;
  align-items: center;
  gap: var(--space-12);
  padding: var(--space-10) var(--space-24);
  border-bottom: 1px solid var(--c-border);
  overflow: hidden;
}

.active-task-heading {
  flex: none;
  color: var(--c-text-muted);
  font-size: var(--text-base);
}

.active-task-list {
  display: flex;
  gap: var(--space-8);
  overflow-x: auto;
}

.active-task-item {
  display: flex;
  align-items: center;
  padding-right: var(--space-2);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-md);
}

/* 整条是按钮，所以悬停要有反馈。只改边框色，不铺底色 —— 铺底色会和里面
   UiButton(ghost) 自带的 hover 底色撞成一片，看不出取消键自己被指到了。 */
.active-task-item:hover {
  border-color: var(--c-border-strong);
}

.active-task-item.selected {
  border-color: var(--c-accent);
}

.active-task-select {
  display: flex;
  align-items: center;
  gap: var(--space-8);
  padding: var(--space-6) var(--space-8);
  border: 0;
  background: transparent;
  color: inherit;
  white-space: nowrap;
  cursor: pointer;
}

.active-task-select:focus-visible {
  outline: 2px solid var(--c-accent);
  outline-offset: -1px;
}

.active-task-select small {
  /* 显式给字号：`<small>` 的浏览器默认是 `font-size: smaller`（13px 下约 10.8px），
     而这份样式表里其它每一处 `small` 都写了字号。靠 UA 默认值等于没有设计。 */
  color: var(--c-text-muted);
  font-size: var(--text-xs);
}

.active-task-title {
  max-width: 190px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.active-task-cancel {
  font-size: var(--text-md);
}

/*
 * 取消键用 UiButton(ghost/sm/icon) 拿到 28×28 点击区与 hover 反馈。
 * 这里只覆盖焦点环的偏移：原语默认 outline-offset: 2px，而按钮已经贴到条目的
 * 圆角边框上，+2px 会画到边框外面；收成 -2px 让环落在按钮内部。
 */
.active-task-cancel:focus-visible {
  outline-offset: -2px;
}
</style>
