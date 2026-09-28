import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'

import SessionSidebar from './SessionSidebar.vue'
import ConfirmProjectDeleteDialog from './ConfirmProjectDeleteDialog.vue'
import ChatComposer from './ChatComposer.vue'

const project = {
  id: 'project-1',
  name: '开发工作台',
  provider: 'github',
  repo: 'https://github.com/example/app.git',
  repoFullName: 'example/app',
  conversations: Array.from({ length: 5 }, (_, index) => ({
    id: `thread-${index + 1}`,
    title: `会话 ${index + 1}`,
    status: 'completed',
    updatedAt: 100 - index,
  })),
}

afterEach(() => localStorage.clear())

describe('SessionSidebar', () => {
  it('shows three recent conversations and expands the rest', async () => {
    const wrapper = mount(SessionSidebar, { props: { projects: [project] } })
    expect(wrapper.findAll('.project-thread-item')).toHaveLength(3)
    await wrapper.get('.show-more-button').trigger('click')
    expect(wrapper.findAll('.project-thread-item')).toHaveLength(5)
    await wrapper.get('.show-more-button').trigger('click')
    expect(wrapper.findAll('.project-thread-item')).toHaveLength(3)
  })

  it('collapses projects and emits project-scoped actions', async () => {
    const wrapper = mount(SessionSidebar, { props: { projects: [project] } })
    await wrapper.get('[aria-label="折叠项目 开发工作台"]').trigger('click')
    expect(wrapper.emitted('toggle-project')?.[0]).toEqual(['project-1'])
    await wrapper.get('[aria-label="在 开发工作台 新建会话"]').trigger('click')
    expect(wrapper.emitted('new-thread')?.[0]).toEqual(['project-1'])
  })

  it('supports double-click rename with Enter and the collapsed session rail tooltip', async () => {
    const wrapper = mount(SessionSidebar, {
      props: { projects: [project], collapsed: false },
    })
    await wrapper.get('.project-heading-main strong').trigger('dblclick')
    const input = wrapper.get('.project-rename-input')
    await input.setValue('重新命名')
    await input.trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('rename-project')?.[0]).toEqual([{ id: 'project-1', name: '重新命名' }])

    await wrapper.setProps({ collapsed: true })
    const shortcut = wrapper.get('.rail-session')
    expect(shortcut.attributes('data-tooltip')).toContain('会话 1')
    await shortcut.trigger('click')
    expect(wrapper.emitted('select-thread')?.at(-1)).toEqual(['thread-1'])
  })
})

describe('ConfirmProjectDeleteDialog', () => {
  it('requires an exact project name before confirming deletion', async () => {
    const wrapper = mount(ConfirmProjectDeleteDialog, {
      props: { project: { ...project, conversations: project.conversations.slice(0, 2) } },
    })
    expect(wrapper.text()).toContain('2 个会话')
    expect(wrapper.get('.button-danger').element.disabled).toBe(true)
    await wrapper.get('#confirm-project-name').setValue('另一个项目')
    expect(wrapper.get('.button-danger').element.disabled).toBe(true)
    await wrapper.get('#confirm-project-name').setValue(project.name)
    expect(wrapper.get('.button-danger').element.disabled).toBe(false)
    await wrapper.get('.button-danger').trigger('click')
    expect(wrapper.emitted('confirm')).toHaveLength(1)
  })

  it('closes from Escape unless a delete is in progress', async () => {
    const wrapper = mount(ConfirmProjectDeleteDialog, { props: { project } })
    await wrapper.get('#confirm-project-name').trigger('keydown', { key: 'Escape' })
    expect(wrapper.emitted('close')).toHaveLength(1)
    await wrapper.setProps({ busy: true })
    await wrapper.get('#confirm-project-name').trigger('keydown', { key: 'Escape' })
    expect(wrapper.emitted('close')).toHaveLength(1)
  })
})

describe('ChatComposer', () => {
  it('exposes configured model choices and emits model changes', async () => {
    const wrapper = mount(ChatComposer, {
      props: {
        model: 'deepseek-flash',
        models: [
          { id: 'deepseek-flash', label: 'DeepSeek Flash' },
          { id: 'deepseek-v4-pro', label: 'DeepSeek V4 Pro' },
        ],
      },
    })
    const selector = wrapper.get('select[aria-label="选择模型"]')
    expect(selector.findAll('option')).toHaveLength(2)
    await selector.setValue('deepseek-v4-pro')
    expect(wrapper.emitted('update:model')?.[0]).toEqual(['deepseek-v4-pro'])
  })

  it('uses repository-free chat copy and sends text', async () => {
    const wrapper = mount(ChatComposer, { props: { chatOnly: true, draft: '你好' } })
    expect(wrapper.text()).toContain('普通聊天')
    expect(wrapper.get('textarea').attributes('placeholder')).toContain('技术难题')
    await wrapper.get('.send-button').trigger('click')
    expect(wrapper.emitted('send')?.[0]).toEqual(['你好'])
  })
})
