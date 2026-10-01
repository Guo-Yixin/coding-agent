import { defineStore } from 'pinia'

import { dashboardApi } from '../api/client'
import { resumeAgentRun, streamAgentMessage } from '../api/sse'

const TERMINAL_RUN_STATUSES = new Set(['completed', 'failed', 'cancelled', 'interrupted'])
const draftTimers = new Map()
let selectionRevision = 0

function createId(prefix) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

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
    if (message.author !== 'user' || !String(message.id || '').startsWith('local-user-')) return false
    const content = (message.chunks || []).filter((chunk) => chunk.kind === 'text')
      .map((chunk) => chunk.text || '').join('').trim()
    return content === text
  })
}

function normalizeThreadMessages(messages) {
  if (!Array.isArray(messages)) return []
  return messages.filter((message) => message && Array.isArray(message.chunks)).map((message) => ({
    id: String(message.id || `${message.author || 'message'}-${Date.now()}`),
    author: message.author || 'agent',
    timestamp: message.timestamp || nowIso(),
    chunks: message.chunks,
    hidden: !!message.hidden,
    metadata: message.metadata || {},
  }))
}

function ensureAgentMessage(messages, messageId) {
  let message = messages.find((item) => item.id === messageId)
  if (!message) {
    message = { id: messageId, author: 'agent', timestamp: nowIso(), chunks: [] }
    messages.push(message)
  }
  return message
}

function appendTextDelta(messages, messageId, content, mode = 'append') {
  if (!messageId || !content) return
  const message = ensureAgentMessage(messages, messageId)
  const chunk = message.chunks.find((item) => item.kind === 'text')
  if (chunk) chunk.text = mode === 'replace' ? content : `${chunk.text || ''}${content}`
  else message.chunks.push({ kind: 'text', text: content })
}

function mergeThreadMeta(target, source) {
  if (!target || !source) return
  for (const field of ['title', 'status', 'branch', 'baseBranch', 'pr', 'provider', 'updatedAt']) {
    if (source[field]) target[field] = source[field]
  }
  if (Object.hasOwn(source, 'pendingIntervention')) target.pendingIntervention = source.pendingIntervention
}

function cursorKey(runId) {
  return `coding.run-cursor.${runId}`
}

export const useAgentStore = defineStore('agent', {
  state: () => ({
    user: null,
    options: null,
    threads: [],
    projects: [],
    currentThread: null,
    draftId: createId('draft'),
    drafts: {},
    messages: [],
    threadMessages: {},
    activeRuns: {},
    controllers: {},
    selectedModel: '',
    selectedEffort: 'default',
    loading: false,
    error: '',
    // 与 `error` 分开：`error` 是给主区顶部横幅用的「刚才那件事失败了」，
    // 而 `projectsError` 回答的是一个结构性是非题 —— **侧栏到底有没有成功拿到项目列表**。
    // 没有它的话，加载失败与「你确实一个项目都没有」在界面上完全一样，
    // 于是失败时应用会热情地引导用户去「创建第一个项目」（见 DESIGN.md §18）。
    projectsError: '',
    runActivityEvents: {},
    runActivityLoading: {},
  }),
  getters: {
    currentThreadId: (state) => state.currentThread?.id || null,
    modelOptions: (state) => state.options?.models || [],
    streaming: (state) => !!state.activeRuns[state.currentThread?.id],
    canSend: (state) => !!state.currentThread && !state.activeRuns[state.currentThread.id],
    currentDraft: (state) => state.drafts[state.currentThread?.id || state.draftId] || '',
    currentProject: (state) => state.projects.find((project) => project.id === state.currentThread?.projectId) || null,
    standaloneThreads: (state) => state.threads.filter((thread) => !thread.projectId),
    activeTasks: (state) => state.threads
      .filter((thread) => ['queued', 'running', 'cancelling'].includes(thread.status) || !!state.activeRuns[thread.id])
      .map((thread) => ({
        ...thread,
        status: state.activeRuns[thread.id]?.status || thread.status,
        runId: state.activeRuns[thread.id]?.runId || null,
      })),
  },
  actions: {
    messagesFor(threadId) {
      if (!this.threadMessages[threadId]) this.threadMessages[threadId] = []
      return this.threadMessages[threadId]
    },
    setDraft(threadId, content) {
      const targetId = threadId || this.draftId
      if (!targetId) return
      this.drafts[targetId] = content
      if (targetId === this.draftId && !this.currentThread) return
      const previous = draftTimers.get(targetId)
      if (previous) clearTimeout(previous)
      draftTimers.set(targetId, setTimeout(() => {
        draftTimers.delete(targetId)
        dashboardApi.saveDraft(targetId, this.drafts[targetId] || '').catch((error) => {
          if (this.currentThread?.id === targetId) this.error = error.message || '草稿保存失败'
        })
      }, 350))
    },
    async flushDraft(threadId) {
      if (!threadId) return
      const timer = draftTimers.get(threadId)
      if (timer) clearTimeout(timer)
      draftTimers.delete(threadId)
      await dashboardApi.saveDraft(threadId, this.drafts[threadId] || '')
    },
    syncVisibleMessages(threadId) {
      if (this.currentThread?.id === threadId || (!this.currentThread && this.draftId === threadId)) {
        this.messages = this.messagesFor(threadId)
      }
    },
    async bootstrap() {
      this.loading = true
      this.error = ''
      // 用 allSettled 而不是 all：五个接口是彼此独立的，其中一个挂掉不该把
      // 已经拿到的四份数据一起丢掉。原来的 `Promise.all` 会让任意一个失败 →
      // `this.projects` 保持 `[]` → 侧栏显示「项目会出现在这里」，
      // 用户看到的是「你没有项目」而不是「没读到项目」。
      const [user, options, threads, projects, activeRuns] = await Promise.allSettled([
        dashboardApi.me(), dashboardApi.options(), dashboardApi.listThreads(), dashboardApi.listProjects(), dashboardApi.listActiveRuns(),
      ])
      if (user.status === 'fulfilled') this.user = user.value
      if (options.status === 'fulfilled') {
        this.options = options.value
        const savedModel = window.localStorage.getItem('coding.selected-model')
        const validModels = (options.value.models || []).map((item) => item.id)
        this.selectedModel = validModels.includes(savedModel)
          ? savedModel
          : options.value.default_agent_model || options.value.models?.[0]?.id || ''
        this.selectedEffort = options.value.default_agent_reasoning_effort || 'default'
      }
      if (threads.status === 'fulfilled') this.threads = threads.value
      if (projects.status === 'fulfilled') {
        this.projects = projects.value
        this.projectsError = ''
      } else {
        this.projectsError = projects.reason?.message || '项目列表加载失败'
      }
      if (activeRuns.status === 'fulfilled') {
        for (const run of activeRuns.value) this.resumeRun(run)
      }
      // 主区横幅保持原样：仍然只显示**第一条**失败信息，不变成五条。
      const [firstFailure] = [user, options, threads, projects, activeRuns].filter((item) => item.status === 'rejected')
      this.error = firstFailure ? (firstFailure.reason?.message || '初始化前端失败') : ''
      this.loading = false
      if (this.error) return
      if (!this.currentThread && this.threads.length) await this.selectThread(this.threads[0].id)
    },
    // 侧栏「重新加载」按钮的落点。刻意只重取项目列表 ——
    // 用户点这个按钮的唯一动机就是「项目没出来」。
    async retryProjects() {
      try {
        this.projects = await dashboardApi.listProjects()
        this.projectsError = ''
        // 项目回来了，主区那条「加载项目列表失败」的横幅也该消失。
        if (this.error) this.error = ''
      } catch (error) {
        this.projectsError = error.message || '项目列表加载失败'
      }
    },
    async refreshThreads() {
      try {
        const [threads, projects] = await Promise.all([dashboardApi.listThreads(), dashboardApi.listProjects()])
        this.threads = threads
        this.projects = projects
      } catch { /* Keep the visible task usable. */ }
    },
    async refreshActiveRuns() {
      try {
        const [threads, projects, activeRuns] = await Promise.all([
          dashboardApi.listThreads(), dashboardApi.listProjects(), dashboardApi.listActiveRuns(),
        ])
        this.threads = threads
        this.projects = projects
        for (const run of activeRuns) this.resumeRun(run)
      } catch {
        // Task streams remain available if a cross-window refresh misses one poll.
      }
    },
    async selectThread(threadId) {
      const revision = ++selectionRevision
      const previousId = this.currentThread?.id
      if (previousId && this.drafts[previousId] !== undefined) {
        try { await this.flushDraft(previousId) } catch { /* The local draft remains available. */ }
      }
      this.error = ''
      const thread = await dashboardApi.getThread(threadId)
      if (revision !== selectionRevision) return
      this.currentThread = thread
      this.drafts[threadId] = this.drafts[threadId] ?? thread.draftContent ?? ''
      this.threadMessages[threadId] = this.threadMessages[threadId]?.length
        ? this.threadMessages[threadId]
        : normalizeThreadMessages(thread.messages)
      this.messages = this.threadMessages[threadId]
      this.runActivityEvents = {}
      this.runActivityLoading = {}
    },
    async createProject(name, provider, repo) {
      const project = await dashboardApi.createProject({ name, provider, repo })
      this.projects.unshift(project)
      await this.createThread(project.id)
      return project
    },
    async createThread(projectId) {
      if (!projectId) throw new Error('请先选择项目或新建项目')
      const thread = await dashboardApi.createProjectThread(projectId)
      this.threads.unshift(thread)
      const project = this.projects.find((item) => item.id === projectId)
      if (project) project.conversations.unshift({
        id: thread.id, projectId, title: thread.title, status: thread.status,
        updatedAt: thread.updatedAt, repo: thread.repo,
      })
      this.drafts[thread.id] = thread.draftContent || ''
      this.threadMessages[thread.id] = normalizeThreadMessages(thread.messages)
      this.currentThread = thread
      this.messages = this.threadMessages[thread.id]
      this.error = ''
    },
    async createChatThread() {
      const fromLanding = !this.currentThread
      const landingDraftId = this.draftId
      const landingDraft = fromLanding ? this.drafts[landingDraftId] || '' : ''
      const thread = await dashboardApi.createChatThread()
      this.threads.unshift(thread)
      this.drafts[thread.id] = thread.draftContent || landingDraft
      this.threadMessages[thread.id] = normalizeThreadMessages(thread.messages)
      this.currentThread = thread
      this.messages = this.threadMessages[thread.id]
      if (fromLanding) {
        delete this.drafts[landingDraftId]
        this.draftId = createId('draft')
      }
      this.error = ''
      return thread
    },
    setSelectedModel(modelId) {
      if (!this.modelOptions.some((model) => model.id === modelId)) return
      this.selectedModel = modelId
      try { window.localStorage.setItem('coding.selected-model', modelId) } catch { /* optional preference */ }
    },
    async renameProject(projectId, name) {
      const updated = await dashboardApi.renameProject(projectId, name)
      const project = this.projects.find((item) => item.id === projectId)
      if (project) project.name = updated.name
      return updated
    },
    async deleteProject(projectId) {
      const project = this.projects.find((item) => item.id === projectId)
      if (!project) return
      const removedIds = new Set((project.conversations || []).map((thread) => thread.id))
      if ([...removedIds].some((id) => this.activeRuns[id])) {
        throw new Error('项目中仍有运行中的任务，请先停止或等待任务完成。')
      }
      await dashboardApi.deleteProject(projectId)
      this.projects = this.projects.filter((item) => item.id !== projectId)
      this.threads = this.threads.filter((thread) => !removedIds.has(thread.id))
      removedIds.forEach((id) => {
        delete this.threadMessages[id]
        delete this.drafts[id]
      })
      if (removedIds.has(this.currentThread?.id)) {
        this.currentThread = null
        this.messages = []
        const next = this.threads[0]
        if (next) await this.selectThread(next.id)
      }
    },
    async deleteThread(threadId) {
      if (this.activeRuns[threadId]) {
        this.error = '运行中的任务请先取消，完成后再删除。'
        return
      }
      await dashboardApi.deleteThread(threadId)
      this.threads = this.threads.filter((thread) => thread.id !== threadId)
      this.projects.forEach((project) => { project.conversations = project.conversations.filter((thread) => thread.id !== threadId) })
      delete this.threadMessages[threadId]
      delete this.drafts[threadId]
      if (this.currentThread?.id === threadId) {
        this.currentThread = null
        this.messages = []
        if (this.threads.length) await this.selectThread(this.threads[0].id)
      }
    },
    async renameThread(threadId, title) {
      const updated = await dashboardApi.updateThreadTitle(threadId, title)
      this.threads = this.threads.map((thread) => thread.id === threadId ? { ...thread, title: updated.title } : thread)
      if (this.currentThread?.id === threadId) this.currentThread = { ...this.currentThread, title: updated.title }
      return updated
    },
    async loadRunActivity(runId) {
      const threadId = this.currentThread?.id
      if (!threadId || !runId || this.runActivityEvents[runId] || this.runActivityLoading[runId]) return
      this.runActivityLoading[runId] = true
      try {
        const result = await dashboardApi.getRunActivity(threadId, runId)
        if (this.currentThread?.id === threadId) this.runActivityEvents[runId] = Array.isArray(result.events) ? result.events : []
      } catch (error) {
        this.error = error.message || '读取运行过程失败'
      } finally {
        this.runActivityLoading[runId] = false
      }
    },
    async cancelRun(threadId, runId) {
      if (!threadId || !runId) return
      try {
        await dashboardApi.cancelRun(threadId, runId)
      } catch (error) {
        this.error = error.message || '取消任务失败'
      }
    },
    stopStream() {
      const threadId = this.currentThread?.id
      const run = this.activeRuns[threadId]
      if (run?.runId) this.cancelRun(threadId, run.runId)
    },
    async submit(content, interaction = null) {
      const prompt = content.trim()
      if (!prompt || this.streaming) return
      this.error = ''
      let initialThreadId = this.currentThread?.id
      if (!initialThreadId) {
        try {
          await this.createChatThread()
          initialThreadId = this.currentThread?.id
        } catch (error) {
          this.error = error.message || '创建聊天失败'
          return
        }
      }
      const viewKey = initialThreadId
      const controller = new AbortController()
      const payload = {
        content: prompt,
        repo: this.currentThread.repo || this.currentThread.repoFullName || undefined,
        provider: this.currentThread.provider,
        model_id: this.selectedModel || null,
        effort: this.selectedEffort || null,
        interaction_action: interaction?.interaction_action || null,
        plan_id: interaction?.plan_id || null,
        intervention_id: interaction?.intervention_id || null,
      }
      const messages = this.messagesFor(viewKey)
      this.drafts[viewKey] = ''
      try { await this.flushDraft(viewKey) } catch { /* Task submission remains authoritative. */ }
      messages.push(createTextMessage('user', prompt, 'local-user'))
      this.syncVisibleMessages(viewKey)
      this.activeRuns[viewKey] = { status: 'submitting', runId: null }
      this.controllers[viewKey] = controller
      try {
        await streamAgentMessage(initialThreadId, payload, {
          signal: controller.signal,
          onEvent: (event, data, seq) => this.handleRunEvent(viewKey, event, data, seq),
        })
      } catch (error) {
        if (error.name !== 'AbortError') {
          this.error = error.message || 'Agent 执行失败'
          const entry = this.activeRuns[viewKey]
          if (entry) entry.status = 'failed'
        }
      } finally {
        for (const [key, activeController] of Object.entries(this.controllers)) {
          if (activeController !== controller) continue
          const entry = this.activeRuns[key]
          if (!entry || TERMINAL_RUN_STATUSES.has(entry.status)) delete this.activeRuns[key]
          delete this.controllers[key]
        }
        await this.refreshThreads()
      }
    },
    async resumeRun(run) {
      const { thread_id: threadId, run_id: runId, status } = run
      if (!threadId || !runId || this.controllers[threadId]) return
      const controller = new AbortController()
      this.controllers[threadId] = controller
      if (!this.threadMessages[threadId]) {
        try {
          const thread = await dashboardApi.getThread(threadId)
          this.threadMessages[threadId] = normalizeThreadMessages(thread.messages)
        } catch { this.threadMessages[threadId] = [] }
      }
      if (this.controllers[threadId] !== controller) return
      let storedCursor = 0
      try { storedCursor = Number(sessionStorage.getItem(cursorKey(runId)) || 0) } catch { /* Optional. */ }
      this.activeRuns[threadId] = { runId, status, cursor: storedCursor }
      resumeAgentRun(threadId, runId, {
        signal: controller.signal,
        after: storedCursor,
        onEvent: (event, data, seq) => this.handleRunEvent(threadId, event, data, seq),
      }).catch((error) => {
        if (error.name !== 'AbortError' && this.currentThread?.id === threadId) {
          this.error = error.message || '恢复运行事件失败'
        }
      }).finally(() => {
        const entry = this.activeRuns[threadId]
        if (!entry || TERMINAL_RUN_STATUSES.has(entry.status)) delete this.activeRuns[threadId]
        if (this.controllers[threadId] === controller) delete this.controllers[threadId]
        this.refreshThreads()
      })
    },
    handleRunEvent(viewKey, event, data, seq) {
      const eventThreadId = data.thread_id || data.id || viewKey
      let key = viewKey
      if (event === 'thread_snapshot' || event === 'thread_done') {
        if (key !== eventThreadId) {
          this.threadMessages[eventThreadId] = this.threadMessages[key] || []
          delete this.threadMessages[key]
          if (this.activeRuns[key]) {
            this.activeRuns[eventThreadId] = this.activeRuns[key]
            delete this.activeRuns[key]
          }
          if (this.controllers[key]) {
            this.controllers[eventThreadId] = this.controllers[key]
            delete this.controllers[key]
          }
          key = eventThreadId
        }
        if (data.run_id && this.activeRuns[key]) this.activeRuns[key].runId = data.run_id
        if (this.activeRuns[key]) this.activeRuns[key].status = data.status || (event === 'thread_done' ? 'completed' : 'queued')
        const thread = this.threads.find((item) => item.id === eventThreadId)
        if (thread) mergeThreadMeta(thread, data)
        else this.threads.unshift({ ...data, id: eventThreadId })
        if (this.currentThread?.id === eventThreadId) mergeThreadMeta(this.currentThread, data)
      }
      const messages = this.messagesFor(eventThreadId)
      if (event === 'user_message') {
        const text = String(data.content || '').trim()
        const local = findLocalUserMessage(messages, text)
        if (local) {
          local.id = data.message_id || local.id
          local.timestamp = data.timestamp || local.timestamp
        } else if (
          text
          && !messages.some((message) => message.id === data.message_id)
          && (messages.findLast((message) => message.author === 'user')?.chunks || [])
            .filter((chunk) => chunk.kind === 'text').map((chunk) => chunk.text || '').join('').trim() !== text
        ) {
          messages.push(createTextMessage('user', text, data.message_id || 'user'))
        }
      } else if (event === 'todo_delta') {
        const message = ensureAgentMessage(messages, data.message_id || `todo-${Date.now()}`)
        message.author = 'agent'
        message.chunks = [{ kind: 'text', text: '任务计划' }, { kind: 'todo', todos: Array.isArray(data.todos) ? data.todos : [] }]
      } else if (event === 'message_start') {
        if (data.message_id) ensureAgentMessage(messages, data.message_id)
      } else if (event === 'text_delta') {
        appendTextDelta(messages, data.message_id || `assistant-${Date.now()}`, data.content || '', data.mode || 'append')
      } else if (event === 'error') {
        if (this.currentThread?.id === eventThreadId) this.error = data.message || data.detail || 'Agent 执行失败'
        const thread = this.threads.find((item) => item.id === eventThreadId)
        if (thread) thread.status = 'failed'
      } else if (event === 'run_status' && this.activeRuns[eventThreadId]) {
        this.activeRuns[eventThreadId].status = data.status
        if (data.status === 'running') {
          const runId = data.run_id || this.activeRuns[eventThreadId].runId
          if (runId) {
            appendTextDelta(
              messages,
              `${eventThreadId}-assistant-startup-${runId}`,
              '任务已开始执行，正在准备工作区…\n\n',
              'replace',
            )
          }
        }
      } else if (event === 'done') {
        const run = this.activeRuns[eventThreadId]
        if (run) run.status = data.status || 'completed'
        if (TERMINAL_RUN_STATUSES.has(data.status || 'completed')) delete this.activeRuns[eventThreadId]
        const thread = this.threads.find((item) => item.id === eventThreadId)
        if (thread) thread.status = data.status || 'completed'
        if (this.currentThread?.id === eventThreadId) {
          dashboardApi.getThread(eventThreadId).then((threadDetail) => {
            if (this.currentThread?.id === eventThreadId) {
              this.currentThread = threadDetail
              const normalized = normalizeThreadMessages(threadDetail.messages)
              if (normalized.length) this.threadMessages[eventThreadId] = normalized
              this.messages = this.threadMessages[eventThreadId] || []
            }
          }).catch(() => {})
        }
      }
      if (seq) {
        const runId = data.run_id || this.activeRuns[eventThreadId]?.runId
        if (runId) {
          if (this.activeRuns[eventThreadId]) this.activeRuns[eventThreadId].cursor = Number(seq)
          try { sessionStorage.setItem(cursorKey(runId), String(seq)) } catch { /* Session storage is optional. */ }
        }
      }
      this.syncVisibleMessages(eventThreadId)
    },
  },
})
