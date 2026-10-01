import { describe, expect, it } from 'vitest'

import { formatFullTime, formatRelativeTime } from './useRelativeTime.js'

/**
 * 全部用固定参考时刻，不依赖 `Date.now()` —— 否则这些断言会在某一天的某个钟点
 * 突然失败（"2 小时前"在 00:30 跑会跨天，结果从 HH:MM 变成"昨天 HH:MM"）。
 */
const REF = new Date(2026, 2, 14, 10, 20, 0).getTime() // 2026-03-14 10:20 本地时间

describe('formatRelativeTime', () => {
  it('returns an empty label for a missing or invalid timestamp', () => {
    expect(formatRelativeTime(undefined, REF)).toBe('')
    expect(formatRelativeTime(null, REF)).toBe('')
    expect(formatRelativeTime('', REF)).toBe('')
    expect(formatRelativeTime('not-a-date', REF)).toBe('')
  })

  it('collapses anything under a minute to 刚刚', () => {
    expect(formatRelativeTime(REF, REF)).toBe('刚刚')
    expect(formatRelativeTime(REF - 30_000, REF)).toBe('刚刚')
    expect(formatRelativeTime(REF - 59_999, REF)).toBe('刚刚')
  })

  it('counts minutes within the first hour', () => {
    expect(formatRelativeTime(REF - 60_000, REF)).toBe('1 分钟前')
    expect(formatRelativeTime(REF - 5 * 60_000, REF)).toBe('5 分钟前')
    expect(formatRelativeTime(REF - 59 * 60_000, REF)).toBe('59 分钟前')
  })

  it('falls back to a clock time once the message is over an hour old', () => {
    // 相对粒度到"小时前"就开始失去意义，读者想知道的是"几点"。
    expect(formatRelativeTime(REF - 61 * 60_000, REF)).toBe('09:19')
    expect(formatRelativeTime(REF - 2 * 3600_000, REF)).toBe('08:20')
  })

  it('prefixes 昨天 for the previous calendar day', () => {
    expect(formatRelativeTime(new Date(2026, 2, 13, 22, 5).getTime(), REF)).toBe('昨天 22:05')
    // 跨天但只差 13 小时 —— 判定按日历天，不按小时数。
    expect(formatRelativeTime(new Date(2026, 2, 13, 23, 55).getTime(), REF)).toBe('昨天 23:55')
  })

  it('uses month and day for earlier days in the same year', () => {
    expect(formatRelativeTime(new Date(2026, 2, 1, 9, 0).getTime(), REF)).toBe('3 月 1 日 09:00')
    expect(formatRelativeTime(new Date(2026, 0, 2, 18, 30).getTime(), REF)).toBe('1 月 2 日 18:30')
  })

  it('adds the year for anything older', () => {
    expect(formatRelativeTime(new Date(2025, 11, 31, 23, 59).getTime(), REF)).toBe('2025 年 12 月 31 日')
  })

  it('never renders a negative offset when the server clock runs ahead', () => {
    // 后端比本机快几秒是常态，不能因此显示"-1 分钟前"。
    expect(formatRelativeTime(REF + 60_000, REF)).toBe('刚刚')
    expect(formatRelativeTime(REF + 10 * 60_000, REF)).toBe('刚刚')
  })
})

describe('formatFullTime', () => {
  it('gives an absolute stamp for the title attribute', () => {
    const label = formatFullTime(new Date(2026, 2, 14, 10, 20).getTime())
    expect(label).toContain('2026')
    expect(label).toContain('10:20')
  })

  it('returns an empty label for an invalid timestamp', () => {
    expect(formatFullTime('nope')).toBe('')
    expect(formatFullTime(undefined)).toBe('')
  })
})
