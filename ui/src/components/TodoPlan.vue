<script setup>
defineProps({
  todos: {
    type: Array,
    default: () => [],
  },
})

function icon(status) {
  if (status === 'completed') return '✓'
  if (status === 'in_progress') return '↻'
  return '○'
}
</script>

<template>
  <section class="todo-card">
    <header>
      <span>☷</span>
      <strong>{{ todos.filter((item) => item.status === 'completed').length }} out of {{ todos.length }} tasks completed</strong>
    </header>
    <ol>
      <li
        v-for="(todo, index) in todos"
        :key="`${index}-${todo.content}`"
        :class="todo.status"
      >
        <span class="todo-icon">{{ icon(todo.status) }}</span>
        <span>{{ index + 1 }}. {{ todo.content }}</span>
      </li>
    </ol>
  </section>
</template>
