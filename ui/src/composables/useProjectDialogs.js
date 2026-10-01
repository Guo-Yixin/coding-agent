import { ref } from 'vue'

import { useAgentStore } from '../stores/agent'

/**
 * 「新建 / 重命名 / 删除项目」这两个弹窗的全部状态与动作。
 *
 * 它是一个真正的功能单元，而不是一组散落的 ref：两个弹窗共用一个
 * `agent.error` 通道（新建失败显示在弹窗里，重命名失败显示在主区横幅），
 * 而删除走的是自己独立的 `projectDeleteError` —— 因为删除确认框关掉之后
 * 主区横幅会被下一次操作清空，用户就看不到失败原因了。这层区别值得有个家。
 */
export function useProjectDialogs() {
  const agent = useAgentStore()

  // 新建 / 重命名共用同一个弹窗，`projectBeingEdited` 为 null 时是"新建"。
  const showProjectDialog = ref(false)
  const creatingProject = ref(false)
  const projectBeingEdited = ref(null)

  const projectPendingDelete = ref(null)
  const deletingProject = ref(false)
  const projectDeleteError = ref('')

  function openProjectDialog(project = null) {
    projectBeingEdited.value = project
    agent.error = ''
    showProjectDialog.value = true
  }

  function closeProjectDialog() {
    showProjectDialog.value = false
    projectBeingEdited.value = null
  }

  async function saveProject({ id, name, provider, repo }) {
    creatingProject.value = true
    agent.error = ''
    try {
      if (id) await agent.renameProject(id, name)
      else await agent.createProject(name, provider, repo)
      closeProjectDialog()
    } catch (error) {
      agent.error = error.message || (id ? '重命名项目失败' : '创建项目失败')
    } finally {
      creatingProject.value = false
    }
  }

  function askDeleteProject(project) {
    projectPendingDelete.value = project
    projectDeleteError.value = ''
  }

  async function confirmDeleteProject() {
    if (!projectPendingDelete.value) return
    deletingProject.value = true
    projectDeleteError.value = ''
    try {
      await agent.deleteProject(projectPendingDelete.value.id)
      projectPendingDelete.value = null
    } catch (error) {
      projectDeleteError.value = error.message || '删除项目失败'
    } finally {
      deletingProject.value = false
    }
  }

  return {
    showProjectDialog,
    creatingProject,
    projectBeingEdited,
    projectPendingDelete,
    deletingProject,
    projectDeleteError,
    openProjectDialog,
    closeProjectDialog,
    saveProject,
    askDeleteProject,
    confirmDeleteProject,
  }
}
