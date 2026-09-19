import { onBeforeUnmount, shallowRef } from 'vue'

const BOTTOM_THRESHOLD = 64
const MAX_UNREAD_COUNT = 99

function isAtBottom(element) {
  if (!element) return true
  return element.scrollHeight - element.scrollTop - element.clientHeight <= BOTTOM_THRESHOLD
}

export function useSmartScroll(containerRef) {
  const isFollowingLatest = shallowRef(true)
  const hasUnreadContent = shallowRef(false)
  const unreadContentCount = shallowRef(0)
  let scrollFrame = 0

  function clearUnread() {
    hasUnreadContent.value = false
    unreadContentCount.value = 0
  }

  function onScroll() {
    if (scrollFrame) cancelAnimationFrame(scrollFrame)
    scrollFrame = requestAnimationFrame(() => {
      const element = containerRef.value
      const atBottom = isAtBottom(element)
      isFollowingLatest.value = atBottom
      if (atBottom) clearUnread()
      scrollFrame = 0
    })
  }

  function scrollToLatest(behavior = 'auto') {
    const element = containerRef.value
    if (!element) return

    isFollowingLatest.value = true
    clearUnread()
    if (behavior === 'smooth') {
      element.scrollTo({ top: element.scrollHeight, behavior })
    } else {
      element.scrollTop = element.scrollHeight
    }
  }

  function notifyContentChanged() {
    const element = containerRef.value
    if (!element || isFollowingLatest.value || isAtBottom(element)) {
      scrollToLatest()
      return
    }

    isFollowingLatest.value = false
    hasUnreadContent.value = true
    unreadContentCount.value = Math.min(MAX_UNREAD_COUNT, unreadContentCount.value + 1)
  }

  function resetToLatest() {
    isFollowingLatest.value = true
    clearUnread()
    scrollToLatest()
  }

  onBeforeUnmount(() => {
    if (scrollFrame) cancelAnimationFrame(scrollFrame)
  })

  return {
    isFollowingLatest,
    hasUnreadContent,
    unreadContentCount,
    onScroll,
    notifyContentChanged,
    scrollToLatest,
    resetToLatest,
  }
}
