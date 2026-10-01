import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ChatComposer from './ChatComposer.vue'

// 只断言行为与无障碍锚点，不断言样式类名 —— 换成原语组件后这些断言无需改动。
function sendButton(wrapper) {
  return wrapper.get('.ui-btn--primary')
}

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
    await sendButton(wrapper).trigger('click')
    expect(wrapper.emitted('send')?.[0]).toEqual(['你好'])
  })

  it('keeps send disabled until the draft has non-whitespace content', async () => {
    const wrapper = mount(ChatComposer, { props: { draft: '   ' } })
    expect(sendButton(wrapper).element.disabled).toBe(true)
    await wrapper.setProps({ draft: '写一个 FastAPI 接口' })
    expect(sendButton(wrapper).element.disabled).toBe(false)
  })

  it('keeps send disabled while locked, and blocks the emit', async () => {
    const wrapper = mount(ChatComposer, { props: { draft: '写一个接口', locked: true } })
    expect(sendButton(wrapper).element.disabled).toBe(true)
    await sendButton(wrapper).trigger('click')
    expect(wrapper.emitted('send')).toBeUndefined()
  })

  it('trims the payload before sending', async () => {
    const wrapper = mount(ChatComposer, { props: { draft: '  写一个接口  ' } })
    await sendButton(wrapper).trigger('click')
    expect(wrapper.emitted('send')?.[0]).toEqual(['写一个接口'])
  })

  it('sends on Enter and keeps Shift+Enter for a newline', async () => {
    const wrapper = mount(ChatComposer, { props: { draft: '第一行' } })
    await wrapper.get('textarea').trigger('keydown', { key: 'Enter', shiftKey: true })
    expect(wrapper.emitted('send')).toBeUndefined()
    await wrapper.get('textarea').trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('send')?.[0]).toEqual(['第一行'])
  })

  it('ignores Enter while an IME composition is in flight', async () => {
    const wrapper = mount(ChatComposer, { props: { draft: '中文输入' } })
    await wrapper.get('textarea').trigger('keydown', { key: 'Enter', isComposing: true })
    expect(wrapper.emitted('send')).toBeUndefined()
  })

  it('swaps send for stop while a run is active, and locks the textarea', async () => {
    const wrapper = mount(ChatComposer, { props: { draft: '继续', disabled: true } })
    expect(wrapper.find('.ui-btn--primary').exists()).toBe(false)
    expect(wrapper.get('textarea').element.disabled).toBe(true)
    const stop = wrapper.get('.ui-btn--danger')
    expect(stop.text()).toContain('停止运行')
    await stop.trigger('click')
    expect(wrapper.emitted('stop')).toHaveLength(1)
  })

  it('shows the locked hint on the placeholder and disables the textarea', async () => {
    const wrapper = mount(ChatComposer, {
      props: { locked: true, lockedHint: '等待人工介入答复' },
    })
    expect(wrapper.get('[role="status"]').text()).toBe('等待人工介入答复')
    expect(wrapper.get('textarea').element.disabled).toBe(true)
    expect(wrapper.get('textarea').attributes('placeholder')).toContain('人工介入卡片')
  })

  it('offers an explicit cancel for a pending interaction', async () => {
    const wrapper = mount(ChatComposer, {
      props: { interactionHint: '请确认方案调整', draft: '调整后的方案' },
    })
    expect(wrapper.text()).toContain('请确认方案调整')
    expect(wrapper.get('textarea').attributes('placeholder')).toContain('如何调整方案')
    await wrapper.get('button[aria-label="取消方案调整"]').trigger('click')
    expect(wrapper.emitted('cancel-interaction')).toHaveLength(1)
  })
})
