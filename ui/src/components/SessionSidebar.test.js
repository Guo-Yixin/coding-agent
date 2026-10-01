import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'

import SessionSidebar from './SessionSidebar.vue'
import ConfirmProjectDeleteDialog from './ConfirmProjectDeleteDialog.vue'

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
  // 「没读到项目列表」与「你还没有项目」必须长得不一样、也必须有出路。
  it('shows a retry card instead of the empty state when the project list failed to load', async () => {
    const wrapper = mount(SessionSidebar, {
      props: { projects: [], projectsError: '加载项目列表失败：HTTP 503' },
    })

    expect(wrapper.find('.project-error').exists()).toBe(true)
    // 空态引导不能同时出现 —— 否则用户会去点一个必然失败的「创建第一个项目」
    expect(wrapper.find('.project-empty').exists()).toBe(false)
    expect(wrapper.get('.project-error').text()).toContain('加载项目列表失败：HTTP 503')
    expect(wrapper.get('.project-error').attributes('role')).toBe('alert')

    await wrapper.get('.project-error button').trigger('click')
    expect(wrapper.emitted('retry-projects')).toHaveLength(1)
  })

  it('shows a loading placeholder (not the empty-state CTA) while the list is still loading', async () => {
    const wrapper = mount(SessionSidebar, { props: { projects: [], projectsLoading: true } })

    expect(wrapper.find('.project-loading').exists()).toBe(true)
    expect(wrapper.find('.project-empty').exists()).toBe(false)
    expect(wrapper.find('.project-error').exists()).toBe(false)
    expect(wrapper.get('.project-loading').attributes('role')).toBe('status')
  })

  it('keeps showing the empty-state CTA when the list loaded and is genuinely empty', async () => {
    const wrapper = mount(SessionSidebar, { props: { projects: [], projectsError: '' } })

    expect(wrapper.find('.project-error').exists()).toBe(false)
    expect(wrapper.find('.project-empty').exists()).toBe(true)
    await wrapper.get('.project-empty button').trigger('click')
    expect(wrapper.emitted('new-project')).toHaveLength(1)
    expect(wrapper.emitted('retry-projects')).toBeUndefined()
  })

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

  // 下面这些是迁移到 UiButton 之前的特征测试：
  // 只断言行为、aria 与文案，不断言外观类名，这样换原语后测试不改也应当全绿。
  it('emits the top-level create actions', async () => {
    const wrapper = mount(SessionSidebar, { props: { projects: [project] } })
    await wrapper.get('.new-chat-button').trigger('click')
    await wrapper.get('.new-project-button').trigger('click')
    await wrapper.get('[aria-label="折叠侧栏"]').trigger('click')
    expect(wrapper.emitted('new-chat')).toHaveLength(1)
    expect(wrapper.emitted('new-project')).toHaveLength(1)
    expect(wrapper.emitted('toggle-collapse')).toHaveLength(1)
  })

  it('keeps the create actions reachable from the collapsed rail', async () => {
    const wrapper = mount(SessionSidebar, { props: { projects: [project], collapsed: true } })
    await wrapper.get('[aria-label="新聊天"]').trigger('click')
    await wrapper.get('[aria-label="新建项目"]').trigger('click')
    expect(wrapper.emitted('new-chat')).toHaveLength(1)
    expect(wrapper.emitted('new-project')).toHaveLength(1)
  })

  it('deletes a thread by click without selecting it, from a real unnested button', async () => {
    const wrapper = mount(SessionSidebar, { props: { projects: [project] } })
    const deletes = wrapper.findAll('[aria-label="删除会话"]')
    expect(deletes).toHaveLength(3)

    // 行操作必须是真的 <button>，而且不能嵌在另一个 <button> 里。
    // 嵌套写法下内层既进不了 Tab 序，键盘事件还会被外层吞掉 —— 这正是迁移前的状态，
    // 那时靠手写 keydown.enter 兜底，现在是浏览器原生行为，测试要守住的是结构本身。
    expect(deletes[0].element.tagName).toBe('BUTTON')
    expect(deletes[0].element.closest('button')).toBe(deletes[0].element)

    await deletes[0].trigger('click')
    expect(wrapper.emitted('delete-thread')?.[0]).toEqual(['thread-1'])
    // 点删除不能顺带切换会话
    expect(wrapper.emitted('select-thread')).toBeUndefined()

    await deletes[1].trigger('click')
    expect(wrapper.emitted('delete-thread')?.[1]).toEqual(['thread-2'])
    expect(wrapper.emitted('select-thread')).toBeUndefined()
  })

  it('disables the project-scoped create action for a legacy project without a repo', () => {
    const legacy = { ...project, id: 'project-legacy', name: '历史项目', legacy: true, repo: '' }
    const wrapper = mount(SessionSidebar, { props: { projects: [legacy] } })
    expect(wrapper.get('[aria-label="在 历史项目 新建会话"]').element.disabled).toBe(true)
  })

  it('opens the project menu and routes rename and delete from it', async () => {
    const wrapper = mount(SessionSidebar, { props: { projects: [project] } })
    await wrapper.get('[aria-label="开发工作台 项目菜单"]').trigger('click')
    const menu = wrapper.get('[role="menu"]')
    expect(menu.findAll('[role="menuitem"]')).toHaveLength(2)

    await menu.findAll('[role="menuitem"]')[0].trigger('click')
    expect(wrapper.find('.project-rename-input').exists()).toBe(true)

    await wrapper.get('[aria-label="开发工作台 项目菜单"]').trigger('click')
    await wrapper.get('[role="menu"]').findAll('[role="menuitem"]')[1].trigger('click')
    expect(wrapper.emitted('delete-project')?.[0]?.[0].id).toBe('project-1')
  })

  it('offers a create action inside an empty project and in the empty project list', async () => {
    const empty = { ...project, id: 'project-empty', name: '空项目', conversations: [] }
    const wrapper = mount(SessionSidebar, { props: { projects: [empty] } })
    await wrapper.get('.project-no-conversations button').trigger('click')
    expect(wrapper.emitted('new-thread')?.[0]).toEqual(['project-empty'])

    const none = mount(SessionSidebar, { props: { projects: [] } })
    await none.get('.project-empty button').trigger('click')
    expect(none.emitted('new-project')).toHaveLength(1)
  })
})

describe('ConfirmProjectDeleteDialog', () => {
  it('requires an exact project name before confirming deletion', async () => {
    const wrapper = mount(ConfirmProjectDeleteDialog, {
      props: { project: { ...project, conversations: project.conversations.slice(0, 2) } },
    })
    expect(wrapper.text()).toContain('2 个会话')
    expect(wrapper.get('.ui-btn--danger').element.disabled).toBe(true)
    await wrapper.get('#confirm-project-name').setValue('另一个项目')
    expect(wrapper.get('.ui-btn--danger').element.disabled).toBe(true)
    await wrapper.get('#confirm-project-name').setValue(project.name)
    expect(wrapper.get('.ui-btn--danger').element.disabled).toBe(false)
    await wrapper.get('.ui-btn--danger').trigger('click')
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
