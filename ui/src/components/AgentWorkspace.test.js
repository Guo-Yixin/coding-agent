import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import AgentWorkspace from './AgentWorkspace.vue'
import { useAgentStore } from '../stores/agent'

// 这一组测试是主区状态矩阵的安全网：迁移前 AgentWorkspace.vue 有 447 行、零测试，
// 「保持功能不变」在当时是无法验证的。
// 断言一律只碰行为、文案、role、aria —— 不锁外观类名，否则换原语就会假失败。

const thread = (overrides = {}) => ({
  id: 'thread-1',
  projectId: null,
  chatOnly: true,
  title: '会话标题',
  repo: '',
  repoFullName: '',
  provider: 'github',
  branch: '',
  baseBranch: '',
  model: 'deepseek-flash',
  effort: 'default',
  status: 'idle',
  createdAt: 1,
  updatedAt: 1,
  draftContent: '',
  messages: [],
  changedFiles: [],
  ...overrides,
})

let agent
let wrapper

function seed(overrides = {}) {
  agent.$patch(overrides)
}

async function mountWorkspace() {
  wrapper = mount(AgentWorkspace)
  await wrapper.vm.$nextTick()
  return wrapper
}

beforeEach(() => {
  setActivePinia(createPinia())
  agent = useAgentStore()
  // 挂载会触发真实网络请求与 3 秒轮询，这里全部换成空实现。
  vi.spyOn(agent, 'bootstrap').mockResolvedValue(undefined)
  vi.spyOn(agent, 'refreshActiveRuns').mockResolvedValue(undefined)
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  vi.restoreAllMocks()
  localStorage.clear()
})

describe('AgentWorkspace 主区状态', () => {
  it('加载中显示加载态，而不是空态引导', async () => {
    seed({ loading: true })
    await mountWorkspace()

    expect(wrapper.text()).toContain('正在加载会话')
    // 关键：加载中不能同时出现 Hero，否则会先闪一下「开始新聊天」再跳走
    expect(wrapper.find('.welcome-actions').exists()).toBe(false)
  })

  it('无会话时显示 Hero 与两个入口，且点击各自触发对应动作', async () => {
    await mountWorkspace()
    const createChat = vi.spyOn(agent, 'createChatThread').mockResolvedValue(undefined)

    expect(wrapper.text()).toContain('让想法，开始成为产品')
    const actions = wrapper.findAll('.welcome-actions button')
    expect(actions).toHaveLength(2)

    await actions[0].trigger('click')
    expect(createChat).toHaveBeenCalledTimes(1)

    await actions[1].trigger('click')
    // 第二个入口是「创建项目」，开弹窗
    expect(wrapper.findComponent({ name: 'CreateProjectDialog' }).exists()).toBe(true)
  })

  it('普通聊天会话的空态文案与不绑仓库时不同', async () => {
    seed({ currentThread: thread({ chatOnly: true, title: '' }) })
    await mountWorkspace()
    expect(wrapper.text()).toContain('从一个好问题开始')
    // 面包屑的第一级与仓库徽标是两段独立文本，断言也拆开 —— 锁住"信息都在"，
    // 不锁中间用什么分隔符（拼成一个字符串的写法已经被改掉了）。
    expect(wrapper.text()).toContain('普通聊天')
    expect(wrapper.text()).toContain('未连接仓库')
  })

  it('项目会话的空态把项目名写进标题', async () => {
    seed({
      currentThread: thread({ chatOnly: false, projectId: 'p1', repoFullName: 'example/app' }),
      projects: [{ id: 'p1', name: '开发工作台', repoFullName: 'example/app', conversations: [] }],
    })
    await mountWorkspace()
    expect(wrapper.text()).toContain('准备好继续构建开发工作台')
    expect(wrapper.text()).toContain('开发工作台')
    expect(wrapper.text()).toContain('example/app')
  })

  it('有消息时渲染消息列表且不再出现 Hero', async () => {
    seed({
      currentThread: thread(),
      messages: [
        { id: 'm1', author: 'user', timestamp: 1, chunks: [{ kind: 'text', text: '你好' }] },
        { id: 'm2', author: 'agent', timestamp: 2, chunks: [{ kind: 'text', text: '收到' }] },
      ],
    })
    await mountWorkspace()

    expect(wrapper.findAll('.message')).toHaveLength(2)
    expect(wrapper.find('.welcome-actions').exists()).toBe(false)
  })

  it('错误态显示横幅，且与消息列表共存而不是互相取代', async () => {
    seed({
      currentThread: thread(),
      messages: [{ id: 'm1', author: 'user', timestamp: 1, chunks: [{ kind: 'text', text: '你好' }] }],
      error: '创建聊天失败',
    })
    await mountWorkspace()

    const banner = wrapper.find('.error-banner')
    expect(banner.exists()).toBe(true)
    expect(banner.text()).toBe('创建聊天失败')
    expect(wrapper.findAll('.message')).toHaveLength(1)
  })

  it('标题双击进入编辑，Enter 保存，Escape 取消且不调接口', async () => {
    seed({ currentThread: thread({ title: '原标题' }) })
    await mountWorkspace()
    const rename = vi.spyOn(agent, 'renameThread').mockResolvedValue(undefined)

    await wrapper.get('.workspace-header h1').trigger('dblclick')
    const input = wrapper.get('.workspace-title-input')
    expect(input.element.value).toBe('原标题')

    await input.setValue('新标题')
    await input.trigger('keydown', { key: 'Escape' })
    expect(rename).not.toHaveBeenCalled()
    expect(wrapper.find('.workspace-title-input').exists()).toBe(false)

    await wrapper.get('.workspace-header h1').trigger('dblclick')
    await wrapper.get('.workspace-title-input').setValue('新标题')
    await wrapper.get('.workspace-title-input').trigger('keydown', { key: 'Enter' })
    expect(rename).toHaveBeenCalledWith('thread-1', '新标题')
  })

  it('标题为空或未改动时不发请求', async () => {
    seed({ currentThread: thread({ title: '原标题' }) })
    await mountWorkspace()
    const rename = vi.spyOn(agent, 'renameThread').mockResolvedValue(undefined)

    await wrapper.get('.workspace-header h1').trigger('dblclick')
    await wrapper.get('.workspace-title-input').setValue('   ')
    await wrapper.get('.workspace-title-input').trigger('keydown', { key: 'Enter' })
    expect(rename).not.toHaveBeenCalled()
  })

  it('输入法合成期间的回车不触发保存', async () => {
    seed({ currentThread: thread({ title: '原标题' }) })
    await mountWorkspace()
    const rename = vi.spyOn(agent, 'renameThread').mockResolvedValue(undefined)

    await wrapper.get('.workspace-header h1').trigger('dblclick')
    await wrapper.get('.workspace-title-input').setValue('新标题')
    await wrapper.get('.workspace-title-input').trigger('keydown', { key: 'Enter', isComposing: true })
    expect(rename).not.toHaveBeenCalled()
  })

  it('没有会话时标题不可编辑（双击无效）', async () => {
    await mountWorkspace()
    await wrapper.get('.workspace-header h1').trigger('dblclick')
    expect(wrapper.find('.workspace-title-input').exists()).toBe(false)
  })
})
