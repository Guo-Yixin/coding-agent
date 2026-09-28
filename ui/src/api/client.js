import axios from 'axios'

const http = axios.create({
  baseURL: '/dashboard/api',
  withCredentials: true,
})

export const dashboardApi = {
  async me() {
    const { data } = await http.get('/me')
    return data
  },
  async options() {
    const { data } = await http.get('/options')
    return data
  },
  async listThreads() {
    const { data } = await http.get('/threads')
    return data
  },
  async listProjects() {
    const { data } = await http.get('/projects')
    return data
  },
  async createProject(payload) {
    const { data } = await http.post('/projects', payload)
    return data
  },
  async renameProject(projectId, name) {
    const { data } = await http.patch(`/projects/${projectId}`, { name })
    return data
  },
  async deleteProject(projectId) {
    await http.delete(`/projects/${projectId}`)
  },
  async createChatThread() {
    const { data } = await http.post('/threads')
    return data
  },
  async createProjectThread(projectId) {
    const { data } = await http.post(`/projects/${projectId}/threads`)
    return data
  },
  async saveDraft(threadId, content) {
    const { data } = await http.put(`/threads/${threadId}/draft`, { content })
    return data
  },
  async listActiveRuns() {
    const { data } = await http.get('/runs/active')
    return data
  },
  async getThread(threadId) {
    const { data } = await http.get(`/threads/${threadId}`)
    return data
  },
  async getRunActivity(threadId, runId) {
    const { data } = await http.get(`/threads/${threadId}/runs/${runId}/events`)
    return data
  },
  async cancelRun(threadId, runId) {
    const { data } = await http.post(`/threads/${threadId}/runs/${runId}/cancel`)
    return data
  },
  async deleteThread(threadId) {
    await http.delete(`/threads/${threadId}`)
  },
  async updateThreadTitle(threadId, title) {
    const { data } = await http.patch(`/threads/${threadId}`, { title })
    return data
  },
}
