import { effectScope, nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useSidebarPreferences } from './useSidebarPreferences'

/**
 * 这个 composable 抽出来的理由就是它有**两个会静默炸掉整个组件**的坑，
 * 所以测试锁的正是这两条，而不是"能读能写"：
 * 1. localStorage 在隐私模式/配额满时是**抛异常**，不是返回 null；
 * 2. 存进去的是字符串数组，读回来可能是任意 JSON（手改过、旧版本格式）。
 */
describe('useSidebarPreferences', () => {
  let scope

  beforeEach(() => {
    window.localStorage.clear()
    scope = effectScope()
  })

  afterEach(() => {
    scope.stop()
    vi.restoreAllMocks()
    window.localStorage.clear()
  })

  function setup() {
    return scope.run(() => useSidebarPreferences())
  }

  it('没有存过任何东西时默认展开、没有折叠的项目', () => {
    const { collapsed, collapsedProjectIds } = setup()
    expect(collapsed.value).toBe(false)
    expect(collapsedProjectIds.value).toEqual([])
  })

  it('读回上次存下的收起状态与折叠项目', () => {
    window.localStorage.setItem('coding.sidebar.collapsed', 'true')
    window.localStorage.setItem('coding.sidebar.collapsed-projects', '["p1","p2"]')

    const { collapsed, collapsedProjectIds } = setup()
    expect(collapsed.value).toBe(true)
    expect(collapsedProjectIds.value).toEqual(['p1', 'p2'])
  })

  it('localStorage 读取时抛异常不让组件挂掉，退化成默认展开', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('SecurityError: localStorage 被禁用')
    })

    const { collapsed, collapsedProjectIds } = setup()
    expect(collapsed.value).toBe(false)
    expect(collapsedProjectIds.value).toEqual([])
  })

  it('存的项目列表不是数组时忽略它，而不是把字符串当数组用', () => {
    window.localStorage.setItem('coding.sidebar.collapsed-projects', '{"p1":true}')
    const { collapsedProjectIds } = setup()
    expect(collapsedProjectIds.value).toEqual([])
  })

  it('localStorage 写入时抛异常不影响交互（状态照样变）', async () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceededError')
    })

    const { collapsed, collapsedProjectIds, toggleCollapsed, toggleProject } = setup()
    expect(() => toggleCollapsed()).not.toThrow()
    expect(() => toggleProject('p1')).not.toThrow()

    await nextTick()
    expect(collapsed.value).toBe(true)
    expect(collapsedProjectIds.value).toEqual(['p1'])
  })

  it('改写时会落盘，且 toggleProject 是来回切换而不是只加不减', async () => {
    const { collapsed, collapsedProjectIds, toggleCollapsed, toggleProject } = setup()

    toggleCollapsed()
    toggleProject('p1')
    await nextTick()
    expect(window.localStorage.getItem('coding.sidebar.collapsed')).toBe('true')
    expect(JSON.parse(window.localStorage.getItem('coding.sidebar.collapsed-projects'))).toEqual(['p1'])

    toggleProject('p1')
    await nextTick()
    expect(collapsedProjectIds.value).toEqual([])

    toggleCollapsed()
    await nextTick()
    expect(window.localStorage.getItem('coding.sidebar.collapsed')).toBe('false')
  })
})
