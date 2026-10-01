import { getCurrentInstance, onUnmounted, ref } from 'vue'

/**
 * 应用级共享的"现在"。
 *
 * 消息头上的相对时间（"3 分钟前"）如果不重算，就会永远停在渲染那一刻 ——
 * 一个开着不管的标签页里，十分钟前的消息会一直显示"刚刚"。
 * 所以需要一个定时器把它推进。但**每个消息各起一个定时器是灾难**
 * （一屏 200 条消息就是 200 个 interval），所以做成模块级共享：
 * 全部消费者用同一个 ref、同一个 interval，最后一个消费者卸载时停表。
 *
 * 30 秒一次而不是 1 秒一次：这个标签最细只显示到"分钟"，
 * 30 秒是"分钟数最多晚 30 秒跳变"与"几乎不耗电"之间的取舍。
 */
const TICK_MS = 30_000

const now = ref(Date.now())
let consumers = 0
let timer = null

function start() {
  if (timer !== null) return
  timer = window.setInterval(() => {
    now.value = Date.now()
  }, TICK_MS)
}

function stop() {
  if (timer === null) return
  window.clearInterval(timer)
  timer = null
}

export function useNow() {
  consumers += 1
  now.value = Date.now()
  start()

  // 允许在组件外调用（测试里直接调纯函数时不该炸）。
  if (getCurrentInstance()) {
    onUnmounted(() => {
      consumers = Math.max(0, consumers - 1)
      if (consumers === 0) stop()
    })
  }

  return now
}

const MINUTE = 60_000
const HOUR = 60 * MINUTE

const timeFormatter = new Intl.DateTimeFormat('zh-CN', {
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
})

const fullFormatter = new Intl.DateTimeFormat('zh-CN', {
  dateStyle: 'medium',
  timeStyle: 'short',
})

function startOfDay(date) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime()
}

/**
 * 近期用相对时间、超过一小时退回绝对时间。
 *
 * 为什么不一路相对下去：`1 天前` 这样的粒度在看历史会话时是有害的 ——
 * 用户想知道的是"这次对话发生在什么时候"，而"3 天前"不如"3 月 14 日 10:20"
 * 有用。相对时间真正好用的窗口只有"刚刚"那一段。
 *
 * 为什么不用"昨天/今天"开头而直接给 HH:MM：今天的时间戳不需要说"今天"，
 * 页面上的消息按时间正序排，读者本来就在"今天"的语境里。
 */
export function formatRelativeTime(value, reference = Date.now()) {
  // `new Date(null)` 不是 Invalid Date，是 1970-01-01 —— 不显式挡掉，
  // 缺时间戳的消息会显示成"1970 年 1 月 1 日"。
  if (value === null || value === undefined || value === '') return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''

  const diff = reference - date.getTime()
  // 服务端时钟略快于本机时 diff 会是负数。不显示"负 3 分钟前"，压成"刚刚"。
  if (diff < MINUTE) return '刚刚'
  if (diff < HOUR) return `${Math.floor(diff / MINUTE)} 分钟前`

  const clock = timeFormatter.format(date)
  const dayDelta = Math.round((startOfDay(new Date(reference)) - startOfDay(date)) / 86_400_000)

  if (dayDelta <= 0) return clock
  if (dayDelta === 1) return `昨天 ${clock}`
  if (date.getFullYear() === new Date(reference).getFullYear()) {
    return `${date.getMonth() + 1} 月 ${date.getDate()} 日 ${clock}`
  }
  return `${date.getFullYear()} 年 ${date.getMonth() + 1} 月 ${date.getDate()} 日`
}

/** 悬停时给出的精确时刻 —— 相对时间的代价是丢掉了准确值，用 `title` 补回来。 */
export function formatFullTime(value) {
  if (value === null || value === undefined || value === '') return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return fullFormatter.format(date)
}
