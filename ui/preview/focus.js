// 开发期检查：逐个把受影响的控件聚焦，读它的「计算样式」，
// 把结果渲染成一张表 —— 这样一张截图就能证明焦点环到底有没有出现。
// 静态截图看不到 :focus-visible，所以必须真的聚焦再读计算值。
import '../src/styles/tokens.css'
import '../src/styles/main.css'

/** 每个条目：控件 class、外层包装 HTML（有些规则依赖祖先）、显示名 */
const CASES = [
  { name: '.sidebar-toggle', cls: 'sidebar-toggle', html: '<button class="sidebar-toggle">‹</button>' },
  { name: '.new-button', cls: 'new-button', html: '<button class="new-button"><span class="new-button-icon">+</span>新建项目</button>' },
  {
    name: '.thread-delete',
    cls: 'thread-delete',
    html: '<div class="thread-item"><span>会话标题</span><button class="thread-delete">×</button></div>',
  },
  {
    name: '.message-copy-button',
    cls: 'message-copy-button',
    html: '<div class="message"><div class="message-actions"><button class="message-copy-button">⧉</button><span class="message-copy-feedback">复制</span></div></div>',
  },
  {
    name: '.code-copy-action',
    cls: 'code-copy-action',
    html: '<div class="code-window"><header class="code-window-header"><span class="code-window-language">js</span><div class="code-window-actions"><button class="code-window-action code-copy-action">⧉</button></div></header></div>',
  },
  {
    name: '.new-content-button',
    cls: 'new-content-button',
    html: '<div style="position:relative;height:60px"><button class="new-content-button"><span>↓</span>有新内容</button></div>',
  },
  { name: '.quick-prompt', cls: 'quick-prompt', html: '<button class="quick-prompt">总结这个仓库</button>' },
  {
    name: '.rail-session',
    cls: 'rail-session',
    html: '<div class="rail"><button class="rail-session">会话</button></div>',
  },
  { name: '.repo-field input', cls: 'repo-field', html: '<label class="repo-field"><span>仓库</span><input value="owner/repo" /></label>', pick: 'input' },
  {
    name: '.repo-provider-select',
    cls: 'repo-provider-select',
    html: '<select class="repo-provider-select"><option>GitHub</option></select>',
  },
  {
    name: '.repo-control-input input',
    cls: 'repo-control-input',
    html: '<div class="repo-control-input"><input value="owner/repo" /></div>',
    pick: 'input',
  },
  {
    name: '.workspace-title-input',
    cls: 'workspace-title-input',
    html: '<input class="workspace-title-input" value="会话标题" />',
  },
  {
    name: '.model-picker select',
    cls: 'model-picker',
    html: '<div class="model-picker"><select><option>deepseek-flash</option></select></div>',
    pick: 'select',
  },
  { name: '.composer textarea', cls: 'composer', html: '<div class="composer"><textarea>草稿</textarea></div>', pick: 'textarea' },
  {
    name: '.project-rename-input',
    cls: 'project-rename-input',
    html: '<input class="project-rename-input" value="项目名" />',
  },
]

const host = document.getElementById('cases')
const table = document.getElementById('table')
const rows = []

for (const c of CASES) {
  const wrap = document.createElement('div')
  wrap.className = 'case'
  wrap.innerHTML = c.html
  host.append(wrap)

  const el = wrap.querySelector(c.pick || `.${c.cls}`)
  if (!el) {
    rows.push({ name: c.name, ok: false, detail: '元素没找到' })
    continue
  }

  el.focus()
  // 注意：getComputedStyle 返回的是实时对象，必须在 blur 之前把值读出来。
  const cs = getComputedStyle(el)
  const focused = document.activeElement === el
  const width = cs.outlineWidth
  const style = cs.outlineStyle
  const color = cs.outlineColor
  const shadow = cs.boxShadow

  const hasOutline = style !== 'none' && parseFloat(width) > 0
  const hasShadowRing = /rgb/.test(shadow) && shadow !== 'none'

  // 有些控件的焦点环画在祖先容器上（:focus-within 的 box-shadow），
  // 所以必须趁元素还聚焦时往上找一圈。
  let ringOwner = ''
  let ringValue = ''
  if (!hasOutline && !hasShadowRing) {
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      const pcs = getComputedStyle(p)
      if (/rgb/.test(pcs.boxShadow) && pcs.boxShadow !== 'none') {
        ringOwner = p.className
        ringValue = pcs.boxShadow
        break
      }
    }
  }
  el.blur()

  const hasFocusStyle = hasOutline || hasShadowRing || Boolean(ringOwner)

  rows.push({
    name: c.name,
    ok: hasFocusStyle,
    focusable: focused,
    detail: hasOutline
      ? `outline: ${width} ${style} ${color}`
      : hasShadowRing
        ? `box-shadow: ${shadow.slice(0, 56)}`
        : ringOwner
          ? `容器焦点环 .${ringOwner}: ${ringValue.slice(0, 44)}`
          : focused
            ? `没有可见焦点样式（outline: ${style} ${width} / shadow: ${shadow.slice(0, 24)}）`
            : '元素无法获得焦点 —— 可能是祖先 visibility: hidden',
  })
}

table.innerHTML = rows
  .map(
    (r) =>
      `<tr class="${r.ok ? 'ok' : 'bad'}">` +
      `<td>${r.ok ? '✅' : '❌'}</td>` +
      `<td>${r.name}</td>` +
      `<td>${r.detail}</td></tr>`,
  )
  .join('')

document.getElementById('summary').textContent =
  `${rows.filter((r) => r.ok).length} / ${rows.length} 个控件在聚焦时有可见指示`
