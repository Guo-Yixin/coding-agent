import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import CreateProjectDialog from './CreateProjectDialog.vue'

const editingProject = {
  id: 'project-1',
  name: '开发工作台',
  provider: 'github',
  repo: 'https://github.com/example/app.git',
  repoFullName: 'example/app',
}

// 只断言行为与无障碍锚点（id / role / 文案），不断言样式类名，
// 这样把裸控件换成原语组件时这些测试无需改动 —— 它们就是「功能不变」的证据。
describe('CreateProjectDialog', () => {
  it('creates a project from name, provider and repo (trimmed)', async () => {
    const wrapper = mount(CreateProjectDialog)

    expect(wrapper.get('#project-name').element.value).toBe('')
    expect(wrapper.get('#project-provider').findAll('option').map((option) => option.element.value))
      .toEqual(['github', 'gitee'])

    await wrapper.get('#project-name').setValue('  产品官网重构  ')
    await wrapper.get('#project-provider').setValue('gitee')
    await wrapper.get('#project-repo').setValue('  https://gitee.com/owner/repo  ')
    await wrapper.get('form').trigger('submit')

    expect(wrapper.emitted('save')?.[0]).toEqual([{
      name: '产品官网重构',
      provider: 'gitee',
      repo: 'https://gitee.com/owner/repo',
    }])
  })

  it('blocks submit and reports the first missing field', async () => {
    const wrapper = mount(CreateProjectDialog)

    await wrapper.get('form').trigger('submit')
    expect(wrapper.get('[role="alert"]').text()).toBe('请填写项目名称')
    expect(wrapper.emitted('save')).toBeUndefined()

    await wrapper.get('#project-name').setValue('产品官网重构')
    await wrapper.get('form').trigger('submit')
    expect(wrapper.get('[role="alert"]').text()).toBe('请填写仓库地址')
    expect(wrapper.emitted('save')).toBeUndefined()
  })

  it('switches the repo placeholder with the provider', async () => {
    const wrapper = mount(CreateProjectDialog)

    expect(wrapper.get('#project-repo').attributes('placeholder')).toBe('https://github.com/owner/repo')
    await wrapper.get('#project-provider').setValue('gitee')
    expect(wrapper.get('#project-repo').attributes('placeholder')).toBe('https://gitee.com/owner/repo')
  })

  it('renames an existing project without exposing the repo fields', async () => {
    const wrapper = mount(CreateProjectDialog, { props: { project: editingProject } })

    expect(wrapper.find('#project-repo').exists()).toBe(false)
    expect(wrapper.find('#project-provider').exists()).toBe(false)
    expect(wrapper.get('#project-name').element.value).toBe('开发工作台')
    expect(wrapper.text()).toContain('重命名项目')
    expect(wrapper.text()).toContain('example/app')

    await wrapper.get('#project-name').setValue('新名字')
    await wrapper.get('form').trigger('submit')

    expect(wrapper.emitted('save')?.[0]).toEqual([{ id: 'project-1', name: '新名字' }])
  })

  it('resets the fields when the edited project changes', async () => {
    const wrapper = mount(CreateProjectDialog, { props: { project: editingProject } })

    await wrapper.setProps({ project: { ...editingProject, id: 'project-2', name: '另一个项目' } })

    expect(wrapper.get('#project-name').element.value).toBe('另一个项目')
  })

  it('closes on Escape and on backdrop click, but never while busy', async () => {
    const wrapper = mount(CreateProjectDialog)

    await wrapper.get('.dialog-backdrop').trigger('keydown', { key: 'Escape' })
    expect(wrapper.emitted('close')).toHaveLength(1)

    await wrapper.get('.dialog-backdrop').trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(2)

    await wrapper.setProps({ busy: true })
    await wrapper.get('.dialog-backdrop').trigger('keydown', { key: 'Escape' })
    await wrapper.get('.dialog-backdrop').trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(2)
  })

  it('surfaces the save error raised by the parent', async () => {
    const wrapper = mount(CreateProjectDialog, { props: { errorMessage: '仓库地址已存在' } })

    expect(wrapper.get('[role="alert"]').text()).toBe('仓库地址已存在')
  })
})
