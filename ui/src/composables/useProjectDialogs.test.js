import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useAgentStore } from '../stores/agent'
import { useProjectDialogs } from './useProjectDialogs'

/**
 * 锁的是**两条错误通道的分工**，这是把这段代码抽出来时唯一的真决定：
 * - 新建 / 重命名失败 → `agent.error`（会显示在主区横幅上）
 * - 删除失败 → `projectDeleteError`（留在确认框里）
 *
 * 为什么删除要单独一条：确认框一关，主区横幅会被下一次操作清空，
 * 用户就再也看不到失败原因了。
 */
describe('useProjectDialogs', () => {
  let agent

  beforeEach(() => {
    setActivePinia(createPinia())
    agent = useAgentStore()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('默认没有任何弹窗打开', () => {
    const dialogs = useProjectDialogs()
    expect(dialogs.showProjectDialog.value).toBe(false)
    expect(dialogs.projectBeingEdited.value).toBe(null)
    expect(dialogs.projectPendingDelete.value).toBe(null)
  })

  it('openProjectDialog 不带参是"新建"，带项目是"重命名"，并清掉上一次的错误', () => {
    const dialogs = useProjectDialogs()
    agent.error = '上一次失败了'

    dialogs.openProjectDialog()
    expect(dialogs.showProjectDialog.value).toBe(true)
    expect(dialogs.projectBeingEdited.value).toBe(null)
    expect(agent.error).toBe('')

    dialogs.openProjectDialog({ id: 'p1', name: '旧名' })
    expect(dialogs.projectBeingEdited.value).toEqual({ id: 'p1', name: '旧名' })
  })

  it('saveProject 不带 id 走创建，带 id 走重命名，成功后关窗', async () => {
    const create = vi.spyOn(agent, 'createProject').mockResolvedValue(undefined)
    const rename = vi.spyOn(agent, 'renameProject').mockResolvedValue(undefined)
    const dialogs = useProjectDialogs()

    await dialogs.saveProject({ name: '新项目', provider: 'github', repo: 'o/r' })
    expect(create).toHaveBeenCalledWith('新项目', 'github', 'o/r')
    expect(rename).not.toHaveBeenCalled()
    expect(dialogs.showProjectDialog.value).toBe(false)

    dialogs.openProjectDialog({ id: 'p1', name: '旧名' })
    await dialogs.saveProject({ id: 'p1', name: '改名' })
    expect(rename).toHaveBeenCalledWith('p1', '改名')
    expect(dialogs.showProjectDialog.value).toBe(false)
  })

  it('saveProject 失败时留在弹窗里并把原因写到 agent.error', async () => {
    vi.spyOn(agent, 'createProject').mockRejectedValue(new Error('仓库不存在'))
    const dialogs = useProjectDialogs()

    // 注意：`saveProject` 自己不会开窗，它假定窗已经开着（由 openProjectDialog 开）。
    dialogs.openProjectDialog()
    await dialogs.saveProject({ name: '新项目', provider: 'github', repo: 'o/r' })

    expect(agent.error).toBe('仓库不存在')
    expect(dialogs.showProjectDialog.value).toBe(true)
    expect(dialogs.creatingProject.value).toBe(false)
  })

  it('重命名失败时的兜底文案与创建不同', async () => {
    vi.spyOn(agent, 'renameProject').mockRejectedValue(new Error(''))
    const dialogs = useProjectDialogs()

    await dialogs.saveProject({ id: 'p1', name: '改名' })

    expect(agent.error).toBe('重命名项目失败')
  })

  it('删除的失败原因留在 projectDeleteError，不污染 agent.error', async () => {
    vi.spyOn(agent, 'deleteProject').mockRejectedValue(new Error('还有 3 个会话'))
    const dialogs = useProjectDialogs()

    dialogs.askDeleteProject({ id: 'p1', name: '开发工作台' })
    expect(dialogs.projectPendingDelete.value.id).toBe('p1')

    await dialogs.confirmDeleteProject()

    expect(dialogs.projectDeleteError.value).toBe('还有 3 个会话')
    expect(agent.error).toBe('')
    // 弹窗还必须开着，否则用户看不到失败原因。
    expect(dialogs.projectPendingDelete.value.id).toBe('p1')
    expect(dialogs.deletingProject.value).toBe(false)
  })

  it('删除成功后关掉确认框并清空错误', async () => {
    const remove = vi.spyOn(agent, 'deleteProject').mockResolvedValue(undefined)
    const dialogs = useProjectDialogs()

    dialogs.askDeleteProject({ id: 'p1', name: '开发工作台' })
    await dialogs.confirmDeleteProject()

    expect(remove).toHaveBeenCalledWith('p1')
    expect(dialogs.projectPendingDelete.value).toBe(null)
    expect(dialogs.projectDeleteError.value).toBe('')
  })

  it('没有待删项目时 confirmDeleteProject 什么都不做', async () => {
    const remove = vi.spyOn(agent, 'deleteProject').mockResolvedValue(undefined)
    const dialogs = useProjectDialogs()

    await dialogs.confirmDeleteProject()

    expect(remove).not.toHaveBeenCalled()
  })
})
