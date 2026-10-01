<script setup>
/**
 * 主区 Header：文件夹图标 + 会话标题（可双击改名）+ 仓库/项目副标题 + 右侧状态胶囊。
 *
 * 刻意做成"受控组件"：改名要打接口，异步与错误归父级管（`AgentWorkspace.vue`），
 * 这里只持有"正在编辑"这一点纯 UI 状态，并 emit `rename`。
 * 与 `SessionSidebar.vue` 的 rename 分工会不同 —— 那里组件自己管编辑态也自己发请求，
 * 因为侧栏的项目改名没有保存中/保存失败这两个可见状态要渲染。
 *
 * 本组件**必须保持原有 DOM 结构与类名**：`ui/src/styles/main.css` 按类名命中，
 * `AgentWorkspace.test.js` 按 `.workspace-header h1` / `.workspace-title-input` 断言。
 */
import { computed, nextTick, ref } from 'vue'

const props = defineProps({
  /** 已经算好的标题（后端 title 或从前几条消息推导出来的） */
  title: { type: String, default: '' },
  /**
   * 面包屑的第一级：项目名，或「普通聊天」。空字符串表示还没有上下文，
   * 这时面包屑只显示标题本身。
   */
  crumb: { type: String, default: '' },
  /** 第二行徽标：仓库全名，或「未连接仓库」。空字符串表示不显示徽标。 */
  repoLabel: { type: String, default: '' },
  chatOnly: { type: Boolean, default: false },
  /** 有会话 id 才允许改名 */
  editable: { type: Boolean, default: false },
  status: { type: String, default: '' },
  streaming: { type: Boolean, default: false },
  branchLabel: { type: String, default: '' },
  /** 是否显示分支标签（普通聊天不显示） */
  showBranch: { type: Boolean, default: false },
  prUrl: { type: String, default: '' },
  saving: { type: Boolean, default: false },
  errorMessage: { type: String, default: '' },
})

const emit = defineEmits(['rename'])

/**
 * 仓库徽标在两种情况下不显示：
 *   1. 没有仓库（空字符串）；
 *   2. **仓库名和面包屑的项目名一模一样** —— 这不是边界情况，是常态：
 *      项目基本都是按仓库建的，两个字符串相同。并排显示等于同一句话写两遍。
 *      这种情况下去掉徽标，面包屑那一行已经把信息说完了。
 */
const showRepo = computed(() => !!props.repoLabel && props.repoLabel !== props.crumb)

const isEditing = ref(false)
const draft = ref('')
const inputRef = ref(null)

/** 状态胶囊文案。这里而不是 store 里，因为它纯粹是显示措辞。 */
function statusText() {
  if (props.streaming || props.status === 'running') return '正在运行'
  if (props.status === 'queued') return '排队中'
  if (props.status === 'cancelling') return '正在取消'
  if (props.status === 'awaiting_approval') return '等待你介入'
  if (props.status === 'cancelled') return '已取消'
  if (props.status === 'interrupted') return '运行中断'
  if (props.status === 'error' || props.status === 'failed') return '运行失败'
  if (props.status === 'finished' || props.status === 'completed') return '已完成'
  return '等待任务'
}

function startEdit() {
  if (!props.editable || props.saving) return
  draft.value = props.title
  isEditing.value = true
  nextTick(() => {
    inputRef.value?.focus()
    inputRef.value?.select()
  })
}

function cancelEdit() {
  isEditing.value = false
  draft.value = props.title
}

function commit() {
  if (!isEditing.value) return
  const nextTitle = draft.value.trim()
  const previousTitle = props.title
  isEditing.value = false

  // 空标题或没改动就什么都不做 —— 不发请求、不报错。
  if (!nextTitle || nextTitle === previousTitle) {
    draft.value = previousTitle
    return
  }
  emit('rename', nextTitle)
}

function onKeydown(event) {
  // 中文输入法组合期间的回车是"选字"，不是"提交"。
  if (event.isComposing) return
  if (event.key === 'Escape') {
    event.preventDefault()
    cancelEdit()
    return
  }
  if (event.key === 'Enter') {
    event.preventDefault()
    commit()
  }
}
</script>

<template>
  <header class="workspace-header">
    <div class="workspace-heading">
      <span class="conversation-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" focusable="false">
          <path d="M3.5 6.5h6l1.8 2H20.5v9.25a1.75 1.75 0 0 1-1.75 1.75H5.25a1.75 1.75 0 0 1-1.75-1.75V6.5Z" />
          <path d="M3.5 6.5V5.75A1.75 1.75 0 0 1 5.25 4h4.1l1.8 2h7.6A1.75 1.75 0 0 1 20.5 7.75V8.5" />
        </svg>
      </span>
      <div class="workspace-heading-body">
        <div class="workspace-title-row">
          <template v-if="crumb">
            <span class="crumb-root" :title="crumb">{{ crumb }}</span>
            <span class="crumb-sep" aria-hidden="true">/</span>
          </template>
          <input
            v-if="isEditing"
            ref="inputRef"
            v-model="draft"
            class="workspace-title-input"
            type="text"
            maxlength="80"
            aria-label="会话标题"
            @blur="commit"
            @keydown="onKeydown"
          />
          <h1
            v-else
            :title="editable ? '双击编辑会话名称' : title"
            @dblclick="startEdit"
          >
            {{ title }}
          </h1>
          <span v-if="saving" class="title-save-state" aria-live="polite">保存中</span>
          <span v-else-if="errorMessage" class="title-save-error" :title="errorMessage">保存失败</span>
        </div>
        <p v-if="showRepo" class="workspace-repo" :class="{ 'workspace-repo-chat': chatOnly }" :title="repoLabel">{{ repoLabel }}</p>
      </div>
    </div>
    <div class="workspace-status">
      <span class="status-pill" :class="status || 'idle'">
        <span class="status-pill-dot"></span>
        {{ statusText() }}
      </span>
      <span v-if="showBranch" class="branch-label" :title="branchLabel.includes('→') ? '当前工作分支 → 基线分支' : '尚未记录实际工作分支'">
        {{ branchLabel }}
      </span>
      <a v-if="prUrl" :href="prUrl" target="_blank" rel="noreferrer">查看 PR</a>
    </div>
  </header>
</template>
