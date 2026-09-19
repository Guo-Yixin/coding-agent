import { defineStore } from 'pinia'

import { dashboardApi } from '../api/client'
import { streamAgentMessage } from '../api/sse'

const DEFAULT_REPO = 'https://gitee.com/clumsypsc/test_coding_repo'

function nowIso() {
  return new Date().toISOString()
}

function createTextMessage(author, text, idPrefix = author) {
  return {
    id: `${idPrefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`,
    author,
    timestamp: nowIso(),
    chunks: text ? [{ kind: 'text', text }] : [],
  }
}

function findLocalUserMessage(messages, text) {
  return [...messages].reverse().find((message) => {
    if (message.author !== 'user' || !String(message.id || '').startsWith('local-user-')) {
      return false
    }
    const content = (message.chunks || [])
      .filter((chunk) => chunk.kind === 'text')
      .map((chunk) => chunk.text || '')
      .join('')
      .trim()
    return content === text
  })
}

function normalizeThreadMessages(messages) {
  if (!Array.isArray(messages)) return []
  return messages
    .filter((message) => message && Array.isArray(message.chunks))
    .map((message) => ({
      id: String(message.id || `${message.author || 'message'}-${Date.now()}`),
      author: message.author || 'agent',
      timestamp: message.timestamp || nowIso(),
      chunks: message.chunks,
      hidden: !!message.hidden,
    }))
}

function ensureAgentMessage(messages, messageId) {
  let message = messages.find((item) => item.id === messageId)
  if (!message) {
    message = {
      id: messageId,
      author: 'agent',
      timestamp: nowIso(),
      chunks: [],
    }
    messages.push(message)
  }
  return message
}

function upsertTodoMessage(messages, messageId, todos) {
  const message = ensureAgentMessage(messages, messageId)
  message.author = 'agent'
  message.chunks = [
    { kind: 'text', text: '任务计划' },
    { kind: 'todo', todos },
  ]
}

function appendTextDelta(messages, messageId, content, mode = 'append') {
  if (!messageId || !content) return
  const message = ensureAgentMessage(messages, messageId)
  const chunk = message.chunks.find((item) => item.kind === 'text')
  if (chunk) {
    chunk.text = mode === 'replace' ? content : `${chunk.text || ''}${content}`
  } else {
    message.chunks.push({ kind: 'text', text: content })
  }
}

function mergeThreadMeta(target, source) {
  if (!target || !source) return
  target.title = source.title || target.title
  target.status = source.status || target.status
  target.branch = source.branch || target.branch
  target.baseBranch = source.baseBranch || target.baseBranch
  target.pr = source.pr || target.pr
  target.updatedAt = source.updatedAt || target.updatedAt
}

export const useAgentStore = defineStore('agent', {
  state: () => ({
    user: null,
    options: null,
    threads: [],
    currentThread: null,
    messages: [],
    selectedRepo: DEFAULT_REPO,
    selectedModel: '',
    selectedEffort: 'default',
    streaming: false,
    loading: false,
    error: '',
    controller: null,
    activeRunThreadId: null,
  }),
  getters: {
    currentThreadId: (state) => state.currentThread?.id || null,
    modelOptions: (state) => state.options?.models || [],
    canSend: (state) => !state.streaming,
  },
  actions: {
    async bootstrap() {
      this.loading = true
      this.error = ''
      try {
        const [user, options, threads] = await Promise.all([
          dashboardApi.me(),
          dashboardApi.options(),
          dashboardApi.listThreads(),
        ])
        this.user = user
        this.options = options
        this.threads = threads
        this.selectedRepo = options.default_repo || DEFAULT_REPO
        this.selectedModel = options.default_agent_model || options.models?.[0]?.id || ''
        this.selectedEffort = options.default_agent_reasoning_effort || 'default'
        if (!this.currentThread && threads.length) {
          await this.selectThread(threads[0].id)
        }
      } catch (error) {
        this.error = error.message || '初始化前端失败'
      } finally {
        this.loading = false
      }
    },
    async refreshThreads() {
      try {
        this.threads = await dashboardApi.listThreads()
      } catch {
        // 侧边栏刷新失败不影响当前对话继续展示。
      }
    },
    async selectThread(threadId) {
      if (this.streaming) {
        this.controller?.abort()
        this.streaming = false
        this.activeRunThreadId = null
        this.controller = null
      }
      this.error = ''
      const thread = await dashboardApi.getThread(threadId)
      this.currentThread = thread
      this.selectedRepo = thread.repo || thread.repoFullName || DEFAULT_REPO
      this.messages = normalizeThreadMessages(thread.messages)
    },
    async createThread() {
      if (this.streaming) return
      this.currentThread = null
      this.messages = []
      this.error = ''
      this.activeRunThreadId = null
      if (!this.selectedRepo) this.selectedRepo = DEFAULT_REPO
    },
    async deleteThread(threadId) {
      if (this.streaming) return
      await dashboardApi.deleteThread(threadId)
      this.threads = this.threads.filter((thread) => thread.id !== threadId)
      if (this.currentThread?.id === threadId) {
        this.currentThread = null
        this.messages = []
        if (this.threads.length) await this.selectThread(this.threads[0].id)
      }
    },
    async renameThread(threadId, title) {
      const updated = await dashboardApi.updateThreadTitle(threadId, title)
      this.threads = this.threads.map((thread) => (
        thread.id === threadId ? { ...thread, title: updated.title } : thread
      ))
      if (this.currentThread?.id === threadId) {
        this.currentThread = { ...this.currentThread, title: updated.title }
      }
      return updated
    },
    stopStream() {
      this.controller?.abort()
    },
    async submit(content) {
      const prompt = content.trim()
      if (!prompt || this.streaming) return

      this.error = ''
      this.streaming = true
      this.controller = new AbortController()
      const localUserMessage = createTextMessage('user', prompt, 'local-user')
      this.messages.push(localUserMessage)

      try {
        const initialThreadId = this.currentThread?.id || null
        this.activeRunThreadId = initialThreadId || 'pending'
        await this.consumeMessageStream(initialThreadId, prompt)
      } catch (error) {
        if (error.name !== 'AbortError') {
          this.error = error.message || 'Agent 执行失败'
          this.currentThread = {
            ...(this.currentThread || {}),
            status: 'error',
          }
        }
      } finally {
        this.streaming = false
        this.controller = null
        this.activeRunThreadId = null
        await this.refreshThreads()
      }
    },
    async consumeMessageStream(threadId, prompt) {
      await streamAgentMessage(
        threadId,
        {
          content: prompt,
          repo: this.selectedRepo || DEFAULT_REPO,
          model_id: this.selectedModel || null,
          effort: this.selectedEffort || null,
        },
        {
          signal: this.controller.signal,
          onEvent: (event, data) => {
            const eventThreadId = data.thread_id || data.id || threadId
            if (eventThreadId && this.currentThread?.id && this.currentThread.id !== eventThreadId) return

            if (event === 'thread_snapshot' || event === 'thread_done') {
              if (!this.currentThread) {
                this.currentThread = data
                this.selectedRepo = data.repo || data.repoFullName || this.selectedRepo || DEFAULT_REPO
              } else {
                mergeThreadMeta(this.currentThread, data)
              }
              this.activeRunThreadId = data.id || data.thread_id || eventThreadId || this.activeRunThreadId
              return
            }

            if (event === 'user_message') {
              const text = String(data.content || '').trim()
              const local = findLocalUserMessage(this.messages, text)
              if (local) {
                local.id = data.message_id || local.id
                local.timestamp = data.timestamp || local.timestamp
              } else if (text) {
                this.messages.push(createTextMessage('user', text, data.message_id || 'user'))
              }
              return
            }

            if (event === 'todo_delta') {
              upsertTodoMessage(
                this.messages,
                data.message_id || `todo-${Date.now()}`,
                Array.isArray(data.todos) ? data.todos : [],
              )
              return
            }

            if (event === 'message_start') {
              if (data.message_id) ensureAgentMessage(this.messages, data.message_id)
              return
            }

            if (event === 'text_delta') {
              appendTextDelta(
                this.messages,
                data.message_id || `assistant-${Date.now()}`,
                data.content || '',
                data.mode || 'append',
              )
              return
            }

            if (event === 'error') {
              this.error = data.message || data.detail || 'Agent 执行失败'
              if (this.currentThread) this.currentThread.status = 'error'
              return
            }

            if (event === 'done') {
              if (this.currentThread && this.currentThread.status === 'running') {
                this.currentThread.status = 'finished'
              }
            }
          },
        },
      )
    },
  },
})
