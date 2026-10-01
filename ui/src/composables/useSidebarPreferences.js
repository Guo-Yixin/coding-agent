import { ref, watch } from 'vue'

const SIDEBAR_STORAGE_KEY = 'coding.sidebar.collapsed'
const PROJECT_COLLAPSE_STORAGE_KEY = 'coding.sidebar.collapsed-projects'

/**
 * 侧栏的两项本地偏好：整体收起、以及哪些项目被折叠。
 *
 * 抽出来的理由不是行数，而是**它有两处容易写错的地方**：
 * 1. `localStorage` 在隐私模式/禁用 cookie 时会**抛异常**（不是返回 null），
 *    读写都必须包起来，否则整个组件挂不上；
 * 2. 存的是一个字符串数组，反序列化可能拿到任意 JSON（手改过、旧版本格式），
 *    必须 `Array.isArray` 校验后再用。
 *
 * 读取放在 setup 里而不是 `onMounted`：这样首帧就是用户上次的状态，不会先闪一下展开态。
 */
export function useSidebarPreferences() {
  const collapsed = ref(false)
  const collapsedProjectIds = ref([])

  try {
    collapsed.value = window.localStorage.getItem(SIDEBAR_STORAGE_KEY) === 'true'
    const saved = JSON.parse(window.localStorage.getItem(PROJECT_COLLAPSE_STORAGE_KEY) || '[]')
    if (Array.isArray(saved)) collapsedProjectIds.value = saved
  } catch {
    // 本地存储不可用时保持默认展开状态。
  }

  function toggleCollapsed() {
    collapsed.value = !collapsed.value
  }

  function toggleProject(projectId) {
    const next = new Set(collapsedProjectIds.value)
    // 用新数组而不是原地 push：`watch` 默认不深入监听，原地改动不会触发写回。
    if (next.has(projectId)) next.delete(projectId)
    else next.add(projectId)
    collapsedProjectIds.value = [...next]
  }

  watch(collapsed, (value) => {
    try {
      window.localStorage.setItem(SIDEBAR_STORAGE_KEY, String(value))
    } catch {
      // 写不进去不影响交互。
    }
  })

  watch(collapsedProjectIds, (value) => {
    try {
      window.localStorage.setItem(PROJECT_COLLAPSE_STORAGE_KEY, JSON.stringify(value))
    } catch {
      // 同上。
    }
  })

  return { collapsed, collapsedProjectIds, toggleCollapsed, toggleProject }
}
