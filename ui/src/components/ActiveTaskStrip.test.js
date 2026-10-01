// ActiveTaskStrip 的特征测试。
//
// 只断言行为、结构不变式与文案，**不锁样式类名以外的外观**（类名只用来定位元素）。
// 这个组件此前零测试，而它只在有正在运行的任务时出现 —— 默认截图永远拍不到它，
// 所以这里的断言是它唯一的自动安全网。
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import ActiveTaskStrip from './ActiveTaskStrip.vue'

function task(overrides = {}) {
  return {
    id: 't1',
    title: '实现并验证 FastAPI Task API',
    repoFullName: 'example/api',
    status: 'running',
    runId: 'r1',
    ...overrides,
  }
}

describe('ActiveTaskStrip', () => {
  it('没有任务时整条不渲染', () => {
    const wrapper = mount(ActiveTaskStrip, { props: { tasks: [] } })
    expect(wrapper.find('.active-task-strip').exists()).toBe(false)
  })

  it('每个任务一个条目，标题与状态文案都在', () => {
    const wrapper = mount(ActiveTaskStrip, {
      props: {
        tasks: [task(), task({ id: 't2', title: '重构首页 Hero 区', status: 'queued', runId: 'r2' })],
      },
    })
    const items = wrapper.findAll('.active-task-item')
    expect(items).toHaveLength(2)
    expect(items[0].text()).toContain('实现并验证 FastAPI Task API')
    expect(items[0].text()).toContain('运行中')
    expect(items[1].text()).toContain('排队中')
  })

  it('三种状态各自的文案', () => {
    const wrapper = mount(ActiveTaskStrip, {
      props: {
        tasks: [
          task({ id: 'a', status: 'queued' }),
          task({ id: 'b', status: 'cancelling' }),
          task({ id: 'c', status: 'running' }),
        ],
      },
    })
    const texts = wrapper.findAll('.active-task-item').map((item) => item.text())
    expect(texts[0]).toContain('排队中')
    expect(texts[1]).toContain('正在取消')
    expect(texts[2]).toContain('运行中')
  })

  it('没有 title 时退回仓库名，两个都没有就用「新任务」', () => {
    const wrapper = mount(ActiveTaskStrip, {
      props: { tasks: [task({ id: 'a', title: '', repoFullName: 'example/api' }), task({ id: 'b', title: '', repoFullName: '' })] },
    })
    const items = wrapper.findAll('.active-task-item')
    expect(items[0].text()).toContain('example/api')
    expect(items[1].text()).toContain('新任务')
  })

  it('activeId 决定哪一个被标记为 selected', () => {
    const wrapper = mount(ActiveTaskStrip, {
      props: { tasks: [task({ id: 't1' }), task({ id: 't2', runId: 'r2' })], activeId: 't2' },
    })
    const items = wrapper.findAll('.active-task-item')
    expect(items[0].classes()).not.toContain('selected')
    expect(items[1].classes()).toContain('selected')
  })

  it('点条目发 select，带的是任务 id', async () => {
    const wrapper = mount(ActiveTaskStrip, { props: { tasks: [task({ id: 't9' })] } })
    await wrapper.find('.active-task-select').trigger('click')
    expect(wrapper.emitted('select')).toEqual([['t9']])
  })

  it('点取消发 cancel，带 threadId 与 runId', async () => {
    const wrapper = mount(ActiveTaskStrip, { props: { tasks: [task({ id: 't9', runId: 'r9' })] } })
    await wrapper.find('.active-task-cancel').trigger('click')
    expect(wrapper.emitted('cancel')).toEqual([[{ threadId: 't9', runId: 'r9' }]])
  })

  it('没有 runId 的条目不渲染取消键（服务端说在跑但本地无 run）', () => {
    const wrapper = mount(ActiveTaskStrip, { props: { tasks: [task({ id: 't1', runId: null })] } })
    expect(wrapper.find('.active-task-select').exists()).toBe(true)
    expect(wrapper.find('.active-task-cancel').exists()).toBe(false)
  })

  it('取消键有可读的 aria-label，不是只有一个 ×', () => {
    const wrapper = mount(ActiveTaskStrip, { props: { tasks: [task({ title: '重构首页' })] } })
    const cancel = wrapper.find('.active-task-cancel')
    expect(cancel.attributes('aria-label')).toBe('取消重构首页')
    expect(cancel.attributes('title')).toBe('取消任务')
  })

  it('取消键在条目内部，且它自己不是嵌套在另一个 button 里的 button', () => {
    const wrapper = mount(ActiveTaskStrip, { props: { tasks: [task()] } })
    const cancel = wrapper.find('.active-task-cancel')
    expect(cancel.element.tagName).toBe('BUTTON')
    expect(cancel.element.closest('button')).toBe(cancel.element)
  })
})
