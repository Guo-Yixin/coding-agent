import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('../api/client', () => ({
  dashboardApi: {
    createChatThread: vi.fn(),
    saveDraft: vi.fn(),
    listThreads: vi.fn(),
    listProjects: vi.fn(),
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
