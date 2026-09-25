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
  async getThread(threadId) {
    const { data } = await http.get(`/threads/${threadId}`)
    return data
  },
  async getRunActivity(threadId, runId) {
    const { data } = await http.get(`/threads/${threadId}/runs/${runId}/events`)
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
