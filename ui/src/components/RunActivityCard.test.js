// RunActivityCard 的特征测试。
//
// 重点是「深度思考」这一层：`kind === 'think'` 的事件必须**从平铺时间线里消失**，
// 只出现在它自己的折叠块里。这条不变式很容易被以后某次"顺手简化一下 filter"破坏 ——
// 破坏之后界面看起来仍然正常（内容还在），只是模型的推理和工具调用又混回一条列表里，
// 而那种退化不会被任何截图看出来。
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import RunActivityCard from './RunActivityCard.vue'

function activity(overrides = {}) {
  return {
    run_id: 'r1',
    status: 'running',
    started_at: new Date(Date.now() - 5000).toISOString(),
    finished_at: null,
    ...overrides,
  }
}

const THINK = [
  { id: 't1', kind: 'think', title: '先看分布再决定要不要动', status: 'completed', detail: {} },
  { id: 't2', kind: 'think', title: '按频次归一而不是取平均', status: 'completed', detail: {} },
]
const OTHER = [
  { id: 'e1', kind: 'other', title: '读取 main.css', status: 'completed', detail: { text: '1313 行' } },
  { id: 'e2', kind: 'other', title: '运行 audit', status: 'in_progress', detail: {} },
]
const TODO = [{ id: 'd1', kind: 'todo', title: '清单快照', status: 'completed', detail: { todos: [{ content: '第一步', status: 'completed' }] } }]

function mountCard(events) {
  return mount(RunActivityCard, { props: { activity: activity(), events } })
}

describe('RunActivityCard · 深度思考', () => {
  it('没有 think 事件时整块不渲染', () => {
    const wrapper = mountCard(OTHER)
    expect(wrapper.find('.think-block').exists()).toBe(false)
  })

  it('think 事件只进折叠块，不进平铺时间线', () => {
    const wrapper = mountCard([...THINK, ...OTHER])

    expect(wrapper.find('.think-block').exists()).toBe(true)
    expect(wrapper.find('.think-toggle').attributes('aria-expanded')).toBe('false')

    const timelineText = wrapper.find('.run-activity-timeline').text()
    for (const event of THINK) expect(timelineText).not.toContain(event.title)
    for (const event of OTHER) expect(timelineText).toContain(event.title)
  })

  it('收起时不渲染内容，点击后展开', async () => {
    const wrapper = mountCard([...THINK, ...OTHER])
    expect(wrapper.find('.think-list').exists()).toBe(false)

    await wrapper.find('.think-toggle').trigger('click')

    expect(wrapper.find('.think-toggle').attributes('aria-expanded')).toBe('true')
    const thinkText = wrapper.find('.think-list').text()
    for (const event of THINK) expect(thinkText).toContain(event.title)
    for (const event of OTHER) expect(thinkText).not.toContain(event.title)
  })

  it('块上给出段数，而不是让人点开才知道有多少', () => {
    const wrapper = mountCard([...THINK, ...OTHER])
    expect(wrapper.find('.think-count').text()).toBe('2 段')
  })

  it('todo 事件既不进深度思考也不进时间线', () => {
    const wrapper = mountCard([...TODO, ...THINK, ...OTHER])
    expect(wrapper.find('.think-list').exists()).toBe(false)
    const timelineText = wrapper.find('.run-activity-timeline').text()
    expect(timelineText).not.toContain('清单快照')
    expect(wrapper.find('.run-activity-event').exists()).toBe(true)
  })

  it('只有 think 事件时不显示「暂无可展示的执行过程」', () => {
    const wrapper = mountCard(THINK)
    // 空态判定必须把 think 也算进来，否则一条只有推理的运行会被说成"没有过程"。
    expect(wrapper.find('.run-activity-empty').exists()).toBe(false)
    expect(wrapper.find('.think-block').exists()).toBe(true)
  })

  it('确实没有任何事件时才落到空态', () => {
    const wrapper = mountCard([])
    expect(wrapper.find('.run-activity-empty').exists()).toBe(true)
    expect(wrapper.find('.think-block').exists()).toBe(false)
  })
})

describe('RunActivityCard · 展开状态', () => {
  it('completed 默认收起，running 默认展开', () => {
    const done = mount(RunActivityCard, {
      props: { activity: activity({ status: 'completed', finished_at: new Date().toISOString() }), events: OTHER },
    })
    expect(done.find('.run-activity-empty').exists()).toBe(false)
    expect(done.find('.run-activity-content').exists()).toBe(false)

    const running = mountCard(OTHER)
    expect(running.find('.run-activity-content').exists()).toBe(true)
  })
})
