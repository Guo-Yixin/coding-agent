import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('../api/client', () => ({
  dashboardApi: {
    createChatThread: vi.fn(),
    saveDraft: vi.fn(),
    listThreads: vi.fn(),
    listProjects: vi.fn(),
    me: vi.fn(),
    options: vi.fn(),
    listActiveRuns: vi.fn(),
    getThread: vi.fn(),
  },
}))
vi.mock('../api/sse', () => ({
  resumeAgentRun: vi.fn(),
  streamAgentMessage: vi.fn(),
}))

import { dashboardApi } from '../api/client'
import { streamAgentMessage } from '../api/sse'
import { useAgentStore } from './agent'

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  dashboardApi.saveDraft.mockResolvedValue({ content: '', revision: 1 })
  dashboardApi.listThreads.mockResolvedValue([])
  dashboardApi.listProjects.mockResolvedValue([])
  dashboardApi.me.mockResolvedValue({ login: 'coding' })
  dashboardApi.options.mockResolvedValue({ models: [{ id: 'deepseek-flash' }], default_agent_model: 'deepseek-flash' })
  dashboardApi.listActiveRuns.mockResolvedValue([])
  streamAgentMessage.mockResolvedValue(undefined)
})

describe('repository-free first chat', () => {
  it('moves a landing draft into a newly created chat', async () => {
    const agent = useAgentStore()
    dashboardApi.createChatThread.mockResolvedValue({
      id: 'chat-from-landing', title: '新聊天', chatOnly: true, messages: [], draftContent: '',
    })
    agent.setDraft(null, '暂存后再开始')

    await agent.createChatThread()

    expect(agent.currentDraft).toBe('暂存后再开始')
    expect(agent.drafts['chat-from-landing']).toBe('暂存后再开始')
  })

  it('keeps the landing draft locally and creates a chat on first send', async () => {
    const agent = useAgentStore()
    dashboardApi.createChatThread.mockResolvedValue({
      id: 'chat-1', title: '新聊天', chatOnly: true, messages: [], draftContent: '',
    })

    agent.setDraft(null, '请解释任务队列如何并发运行')
    expect(agent.currentDraft).toBe('请解释任务队列如何并发运行')
    expect(dashboardApi.saveDraft).not.toHaveBeenCalled()

    await agent.submit(agent.currentDraft)

    expect(dashboardApi.createChatThread).toHaveBeenCalledOnce()
    expect(agent.currentThread.id).toBe('chat-1')
    expect(streamAgentMessage).toHaveBeenCalledWith(
      'chat-1',
      expect.objectContaining({
        content: '请解释任务队列如何并发运行',
        repo: undefined,
        model_id: null,
      }),
      expect.any(Object),
    )
  })

  it('does not create a thread for an empty prompt', async () => {
    const agent = useAgentStore()
    await agent.submit('   ')
    expect(dashboardApi.createChatThread).not.toHaveBeenCalled()
    expect(streamAgentMessage).not.toHaveBeenCalled()
  })
})

// 这四条锁的是「一个接口失败不该伪装成『你没有数据』」这条契约。
// 原来 bootstrap 用 Promise.all：任意一个 reject → 五个赋值全部跳过 →
// `projects` 保持 `[]` → 侧栏把「没读到项目」渲染成「你还没有项目」。
describe('bootstrap 的局部失败', () => {
  it('项目列表挂掉时，其余四个接口的数据仍然落地', async () => {
    const agent = useAgentStore()
    dashboardApi.listProjects.mockRejectedValue(new Error('加载项目列表失败：HTTP 503'))

    await agent.bootstrap()

    expect(agent.projects).toEqual([])
    expect(agent.projectsError).toBe('加载项目列表失败：HTTP 503')
    // 关键断言：另外四个接口的结果没有被一起丢掉
    expect(agent.user).toEqual({ login: 'coding' })
    expect(agent.selectedModel).toBe('deepseek-flash')
    expect(agent.error).toBe('加载项目列表失败：HTTP 503')
    expect(agent.loading).toBe(false)
  })

  it('项目列表成功而别的接口失败时，项目不会被清空', async () => {
    const agent = useAgentStore()
    dashboardApi.options.mockRejectedValue(new Error('options 挂了'))
    dashboardApi.listProjects.mockResolvedValue([{ id: 'p1', name: '工作台', conversations: [] }])

    await agent.bootstrap()

    expect(agent.projects).toHaveLength(1)
    expect(agent.projectsError).toBe('')
    // 主区横幅仍然只报第一条失败，没有变成五条
    expect(agent.error).toBe('options 挂了')
  })

  it('全部成功时 projectsError 是空字符串（读到了、只是没有）', async () => {
    const agent = useAgentStore()
    await agent.bootstrap()
    expect(agent.projectsError).toBe('')
    expect(agent.error).toBe('')
  })

  it('retryProjects 成功后清掉错误并填上项目', async () => {
    const agent = useAgentStore()
    dashboardApi.listProjects.mockRejectedValueOnce(new Error('HTTP 503'))
    await agent.bootstrap()
    expect(agent.projectsError).toBe('HTTP 503')

    dashboardApi.listProjects.mockResolvedValueOnce([{ id: 'p1', name: '工作台', conversations: [] }])
    await agent.retryProjects()

    expect(agent.projects).toHaveLength(1)
    expect(agent.projectsError).toBe('')
    expect(agent.error).toBe('')
  })

  it('retryProjects 再次失败时保留错误文案，不会静默成功', async () => {
    const agent = useAgentStore()
    await agent.bootstrap()
    dashboardApi.listProjects.mockRejectedValueOnce(new Error('还是 503'))

    await agent.retryProjects()

    expect(agent.projectsError).toBe('还是 503')
  })
})
