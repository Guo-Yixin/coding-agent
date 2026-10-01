# DESIGN.md — CODING 工作台视觉契约

> 本文件是**约束**，不是描述。代码与它冲突时，改代码。
> Token 的**值**在 `ui/src/styles/tokens.css`，本文件不重复。

## 1. 定位

一个**长时间使用的开发工作台**：中性、密实、层级分明。详见 `direction.md`。

## 2. 参照物

**Cursor（主）+ Linear（辅）**，逐张的「取 / 不取」写在 `direction.md`。
截图在 `reference/candidates/`。改动前先看那两张图。

## 3. Token 与契约（唯一真相源）

| 层面 | 唯一真相源 | 强制手段 |
|---|---|---|
| 视觉值（颜色 / 间距 / 字号 / 圆角 / 阴影 / 层级） | `ui/src/styles/tokens.css` | `npm run audit`（漂移记分卡）+ `npm run lint:css` |
| 数据形状（接口返回什么） | `ui/src/api/types.js`（JSDoc `@typedef`） | 以**真实响应**为准，形状变了**先改这里** |
| 网络出口 | `ui/src/api/client.js`（axios）、`ui/src/api/sse.js`（流式） | 组件**永远不直接 fetch** |

**任何字面量颜色、字号、间距、圆角都是 bug。** 执行命令：

```
npm run lint:css      # 新代码（components/ui、components/layout）0 error —— 硬门
npm run lint:css:all  # 全部文件，含 legacy；迁移期仅作参考
npm run audit         # 设计系统漂移记分卡（legacy 的收敛进度看这个）
npm run shots         # 截图三个宽度（需先 npm run dev）
```

> **迁移期策略**：`lint:css` 只卡**新代码**。legacy 的 `main.css` 曾经是一地违规，
> 一次性开满会让人习惯性忽略输出 —— 那等于没开。
> **阶段二收敛后 `npm run audit` 已全绿**；但 `lint:css:all` 仍会报几百条格式类问题
> （它管的是写法风格，`audit` 管的才是设计系统漂移），所以 glob 暂不扩大。

### 记分卡的两个指标不要混淆

| 指标 | 判定 | 含义 |
|---|---|---|
| **冗余声明**（同属性重复声明） | **硬门 = 0** | 该声明被更靠后、同上下文、同选择器的声明完全覆盖 → 删掉不改渲染 |
| 同一选择器分散在多块 | 提示（ℹ️） | 同一个选择器出现在多个块里，但属性**并未**重叠。要归零必须合并块，而合并会把声明搬到文件更靠后处、改变它与其它同特异性选择器之间的先后关系 → **有渲染风险，不能当硬门** |

## 4. 布局骨架

单页应用，无路由。一个 CSS Grid 两列：

```
grid-template-columns: var(--layout-sidebar) minmax(0, 1fr)
```

```
┌──────────────────┬──────────────────────────────────────────────┐
│ Sidebar          │ Header   (var(--layout-header) = 52px)        │
│ var(--layout-    │  ┌ thread title (可编辑)   ┌ status badge     │
│ sidebar)=272px   │  └ 仓库全名 (次)           └ branch (次)      │
│                  ├──────────────────────────────────────────────┤
│ ┌ logo    [◀] ┐  │                                              │
│ │ 新聊天   ⌘K │  │ Content  max-width: var(--layout-content-max)│
│ │ 新建项目    │  │           = 960px，居中，上下留白             │
│ ├─────────────┤  │                                              │
│ │ 项目     [4]│  │   空态 → Hero 垂直居中：                      │
│ │  ▾ 分组     │  │     mark / eyebrow / h1 / desc               │
│ │    · 会话   │  │                                              │
│ │    · 会话   │  │   会话态 → 消息列表，向上滚动                  │
│ │ 展开其余 12 │  │                                              │
│ ├─────────────┤  ├──────────────────────────────────────────────┤
│ │ 工作区已就绪│  │ Composer (sticky bottom，卡片式)              │
└──┴─────────────┴──┴──────────────────────────────────────────────┘
```

### 断点：**只允许这 3 个**

| 断点 | 语义 | 侧栏行为 |
|---|---|---|
| `max-width: 860px` | 平板 | 侧栏改为浮层 + backdrop |
| `max-width: 720px` | 窄屏 | composer 底栏折行 |
| `max-width: 560px` | 手机 | 单列，字号不下调 |

> **已收敛**：阶段二把 `600px` 那个只出现 1 次的漂移断点并进了 `560px`。
> 现在除 `@media (hover: none)` 外只有上表 3 个宽度，各有 3 个块；
> 合并前后 375 / 768 / 1440 三个宽度的截图**逐像素一致**。

## 5. 组件白名单

**页面只能使用下表中的组件与 class。新增 class 需要先改本表。**（阶段三后生效）

| 用途 | 组件 | 来源 |
|---|---|---|
| 按钮 | `UiButton` (primary / secondary / ghost / danger) | `@/components/ui/UiButton.vue` |
| 输入框 | `UiInput` | `@/components/ui/UiInput.vue` |
| 多行输入 | `UiTextarea`（`bare` 无框形态 + `autoResize`） | `@/components/ui/UiTextarea.vue` |
| 下拉 | `UiSelect`（`bare` 无框形态 + `prefix`/`suffix` 插槽） | `@/components/ui/UiSelect.vue` |
| 卡片/容器 | `UiCard` | `@/components/ui/UiCard.vue` |
| 状态标记 | `UiBadge` (neutral / accent / success / warning / danger) | `@/components/ui/UiBadge.vue` |
| 空态 | `UiEmptyState` | `@/components/ui/UiEmptyState.vue` |

**业务组件**（保留，但内部必须只使用上面的白名单 + token）：

| 组件 | 文件 | 职责 |
|---|---|---|
| 侧栏 | `SessionSidebar.vue` | 项目分组树、新建、收起 |
| 工作区 | `AgentWorkspace.vue` | Header + 内容区 + composer 编排 |
| 输入区 | `ChatComposer.vue` | 模型/推理/仓库 + 发送 |
| 消息 | `ChatMessage.vue` | 单条消息渲染 |
| 消息操作 | `MessageActions.vue` | 复制/重试等 |
| 运行轨迹 | `RunActivityCard.vue` | 折叠的运行详情 |
| 运行指示 | `ActiveTaskStrip.vue` | 正在跑的任务条 |
| 待办 | `TodoPlan.vue` | 计划清单 |
| 提案 | `ProposalCard.vue` | 计划确认 |
| 人工介入 | `HumanInterventionCard.vue` | 需要用户输入 |
| 新建项目 | `CreateProjectDialog.vue` | 弹窗 |
| 删除项目 | `ConfirmProjectDeleteDialog.vue` | 弹窗 |

**禁止**：在页面里写裸 `<button>` / `<input>` / `<select>` / `<textarea>`（除 `UiButton` 等原语内部）。

**尚未移除的例外**（都是已知、有原因、有后续动作的，不是漏掉）见 §10 末尾的"已知例外"表。
阶段三第四笔之后，`ChatComposer` 的 `<select>` 与 `<textarea>` 都已收回原语，只剩一个只读展示不算控件。

### 状态预览夹具

弹窗、错误态、超长文本这类**不在默认视口里**的状态，靠 `npm run shots` 截不到。
做法是在 `ui/preview/` 下放一个只用于开发的夹具页，把组件的多个形态并排挂载，
再用 `capture.mjs` 一张截图看全：

```
node ui/scripts/capture.mjs http://127.0.0.1:3000/preview/dialogs.html shots --widths 1560 --height 700 --name dialogs
```

夹具只进 dev server（Vite 默认只把 `index.html` 作为构建入口），不会进产物。

**要验窄屏排布时用 iframe 造视口**：media query 认的是**视口宽度**不是容器宽度，
所以把组件塞进一个窄 `div` 不会触发断点。正确做法是外层页面用固定宽度的 `<iframe>`
把同一个组件挂几遍（`ui/preview/composer.html` → `composer-frame.html` 就是这个套路）：

```
node ui/scripts/capture.mjs http://127.0.0.1:3000/preview/composer.html shots --widths 1760 --height 300 --name breakpoints
```

这条在默认截图里验不了 —— 主界面在窄屏下侧栏是覆盖式抽屉，会把 composer 整个盖住。

**要验键盘焦点时必须真的聚焦再读计算样式**：静态截图里看不到 `:focus-visible`。
`ui/preview/focus.html` 逐个聚焦受影响的控件并读 `getComputedStyle`，把结果渲成一张表。
详见 §11 末尾。

**要验「默认数据里根本不出现的状态」时，把每种状态人工种出来**：
`proposal` / `intervention` / `todo` / `error` 这几种消息块**只在特定数据下出现**，
现有会话里一个都没有 —— 既点不出来也截不到。`ui/preview/messages.html`（16 格）与
`ui/preview/states.html`（6 格）就是干这个的：每个格子用独立 `createPinia()` + `$patch()`
种状态，并把 `store.bootstrap` / `store.refreshActiveRuns` 换成空函数（**不覆盖就会真打接口并起轮询**）。

```bash
# 整张矩阵
node ui/scripts/capture.mjs "http://127.0.0.1:3000/preview/messages.html" tmp/msg --widths 1560 --height 2600 --budget 9000 --name before
# 某一格的 1:1 —— 要单格大图就用它，不要在整张合成图上裁（§15 记了三次失败）
node ui/scripts/capture.mjs "http://127.0.0.1:3000/preview/messages.html?cell=8" tmp/msg --widths 900 --height 620 --budget 6000 --name c8
```

> **夹具的查询参数只能有一个。** `capture.mjs` 把 URL 交给 shell，`&` 在那里是命令分隔符 ——
> `?a=1&b=2` 会报 `'b' is not recognized as an internal or external command`，加引号也救不了。
> 所以夹具一律设计成只接受一个参数（`?cell=N` 或 `?only=N`）。

## 6. 页面 × 状态矩阵

**每个格子都必须真的设计过，而且必须能真的渲染出来看。**
✅ = 已设计过并亲眼看过截图；⬜ = 空缺（写下来才算数，不要在心里记）。
矩阵不是文档练习：**本表第一次被真正渲染时，就抓到了 §14 里那个「Hero 五个类名全无 CSS」的缺陷** —— 那两处是终端用户最可能抱怨、却最难被开发者看到的地方。

| 区域 | 空态 | 加载态 | 正常态 | 错误态 | 边界态 |
|---|---|---|---|---|---|
| 侧栏 · 项目列表 | ✅ 无项目引导（虚线框 + 「项目会出现在这里」+ 实心主 CTA） | ✅ spinner + 「正在加载项目…」（**不能与空态同一个样子**） | ✅ 分组树 + 展开/收起 | ✅ 实线警告卡 + 「重新加载」按钮（**不再冒充空态**，见 §18） | ✅ 「展开显示其余 N 个会话」+ 超长项目名/仓库名省略号 |
| 主区 · 内容 | ✅ Hero 三变体（无会话 / 普通聊天 / 项目会话） | ✅ spinner + `role="status"` + `aria-live="polite"` | ✅ 消息列表 | ✅ 错误横幅（**与消息共存，不互相取代**） | ✅ 极长消息：URL 正常折行、宽代码块在气泡内横向滚动、宽表格不破版（见 §18） |
| 主区 · Header | ✅ 新会话标题 | — | ✅ 双击就地编辑标题 | — | ✅ 无空格 120 字符标题：`text-overflow=ellipsis`，实测「被裁=是」，状态徽章不被挤走 |
| Composer | ✅ 正常可用 | ✅ 禁用 + spinner | ✅ 正常 | ✅ 草稿保存失败提示 | ✅ 锁定态（`locked` 提示 + 人工介入；`disabled` 换成「停止运行」）；只读仓库名省略号 |
| 运行轨迹 | ✅ 折叠 | ✅ 进行中 | ✅ 已完成 | ✅ 失败 | ✅ 超长 todo 文本在卡片内折行（见 §18） |
| 弹窗 | — | ✅ 提交中禁用 | ✅ 正常 | ✅ 校验失败 | ✅ 超长输入：输入框内部横向滚动，弹窗不破版 |

> **顺序铁律**：先做空态与错态，再做正常态。理由见 skill 的 `references/build.md`。
> ⬜ 已全部清零。它们不是靠"看了一遍觉得没问题"填上的 —— 每一格都是先用
> `ui/preview/edges.html`（§18）把极端输入真的渲染出来、由探测器给出判定，再动手改的。

### 怎么把任何一格渲染出来

真实应用只在特定数据下才进得了某个状态（Hero 尤其：**账号下只要还有一个会话就再也回不去**，手工点不出来）。所以每一格都靠夹具种状态：

```powershell
# 整张矩阵（**7 格**纵向拼版，scale 0.62）
node ui/scripts/capture.mjs "http://127.0.0.1:3000/preview/states.html" tmp/st --widths 920 --height 4200 --budget 9000 --name states
# 单格 1:1（cell 0..6：无会话 / 普通聊天空态 / 项目会话空态 / 加载态 / 错误态 / 正常态 / 活跃任务条）
node ui/scripts/capture.mjs "http://127.0.0.1:3000/preview/states.html?cell=0" tmp/st --widths 1472 --height 940 --budget 6000 --name s1
```

> **拼版图的 `--height` 要用「格数 × 单格高」算出来**（每格 `900 × 0.62 ≈ 558` + 标签 ≈ 586px），
> 不能目测给一个数 —— `--height 2900` 时第 ⑥ 格其实一直被裁掉，而没人会发现（见 §16）。

`ui/preview/states.js` 里每格独立 `createPinia()` + `setActivePinia()` + `$patch()`，并把 `store.bootstrap` / `store.refreshActiveRuns` 换成空函数 —— **不换掉就会真打接口并起一个 3 秒轮询**。

> **★ 夹具的查询参数只能有一个 ★**：`ui/scripts/capture.mjs` 会把 URL 交给 shell，`&` 在那里是命令分隔符 —— `?only=0&scale=1` 会报 `'scale' is not recognized as an internal or external command`（双引号、单引号都不管用）。要加参数就往夹具里加**单参数**分支。

现有夹具清单（`ui/preview/`）：

| 夹具 | 用来验什么 | 命令要点 |
|---|---|---|
| `composer.html` | 底栏在各断点下的排布 | 用固定宽度 `<iframe>` 造真实视口（media query 认视口不认容器） |
| `composer-footer.html` | 底栏的**交互层级**：只有模型选择器是控件，仓库是纯文字。四种数据（长名 / 短名 / 无仓库 / `chatOnly`） | `--widths 900 --height 400 --scale 2`。**≥721px 才验得了截断**（窄屏 `max-width: none` 是故意的） |
| `focus.html` | `:focus-visible` 可见性 | 逐元素 `focus()` 后读 `getComputedStyle`，**必须在 `blur()` 之前读**；环画在祖先上的要趁聚焦时往上找 `boxShadow` |
| `sidebar.html` | 侧栏控件体征 + 键盘可达性 | 表里是**聚焦态**的值（`probe()` 先 `focus()` 再读） |
| `states.html` | 页面 × 状态矩阵（本节） | `?cell=N` 取单格 1:1 |
| `edges.html` | 页面 × 状态矩阵的**边界态那一列** + 自动横向溢出探测（见 §18） | `?cell=N`（0..6）。它自己会跑探测器并把判定画进截图 |
| `messages.html` | `ChatMessage` 能渲染的**每一种 chunk kind 与状态**（16 格） | `?cell=N` 取单格 1:1。**`proposal` / `intervention` / `todo` / `error` 在真实数据里一个都没有**，只能靠它 |
| `active-tasks.html` | 活跃任务条（只在有运行中任务时出现，默认数据里永远看不到） | `--scale 3` 放大看点击区；挂两遍含空数组 |

## 7. 禁止事项

见 `anti-patterns.md`。最常见的三条：
1. 新增 `:root` 块（只允许 `tokens.css` 里那一个）
2. 硬编码颜色 / 字号 / 间距 / 圆角字面量
3. 「顺手优化」未经要求的样式

## 8. 变更流程

```
改视觉前  → 先改本文件（或 direction.md / tokens.css）
          → 再改代码
          → npm run lint:css && npm run audit
          → npm run shots 截图，与 docs/design/baseline/ 里的基线对比
          → 若本次改动应当是"零视觉变化"，核 SHA256 是否逐像素一致
```

**反过来做（先改代码再补文档）视为违规。** 这是这个项目 CSS 膨胀到 1313 行的根本原因。

### `baseline/` 里两组基线的分工

| 文件 | 含义 | 是否刷新 |
|---|---|---|
| `before-{375,768,1440}.png` | **阶段二的入口状态**（改造前） | **永不刷新**，它是整件事的对照原点 |
| `after-{375,768,1440}.png` | **最近一次验收通过的整屏截图** | 每完成一笔、看完图确认变化都是预期的之后刷新 |
| `phase3-*-*.png` | 单笔改动的证据（矩阵、1:1 特写、状态拼版） | 只增不改，过期了也不删 |

**`after-*` 必须跟着刷新**，否则 `npm run shots` 会从"这一笔有没有意外改动"变成
"和三个月前的某一次比"，变成一个恒亮的警报 —— 恒亮的警报等于没有警报。
刷新时机是**看完截图、确认差异都能解释之后**，不是截图那一刻。

刷新命令（`ui/shots/` 是 `npm run shots` 的落点，已 gitignore）：

```bash
cp ui/shots/shot-375.png  docs/design/baseline/after-375.png
cp ui/shots/shot-768.png  docs/design/baseline/after-768.png
cp ui/shots/shot-1440.png docs/design/baseline/after-1440.png
```

### 阶段划分（不许跳步）

| 阶段 | 内容 | 视觉变化 | 功能风险 |
|---|---|---|---|
| **一 · 地基** | token / 契约 / 参照物 / 可执行检查 / 截图基线 | **必须为零** | 无 |
| **二 · 收敛** | 只把 `main.css` 的值归一到 token，**类名与结构不动** | 应该有，且是"变清楚" | 极低 |
| **三 · 迁移** | 换用原语组件、补齐状态矩阵、拆组件 | 大 | 高（逐页截图验证） |

**阶段二之前不要碰 `.vue` 的模板结构；阶段三之前不要改类名。**

---

## 9. 阶段二收敛记录（已完成）

原始记分卡存档在 `baseline/audit-before.json` 与 `baseline/audit-after.json`。

| 指标 | 前 | 后 | 阈值 |
|---|---|---|---|
| 彩色 distinct | 167 | **0** | ≤5 |
| 近白背景 distinct | 17 | **0** | ≤3 |
| border-radius 档位 | 20 | **4** | ≤4 |
| font-size 档位 | 19 | **7** | ≤7 |
| `:root` 块 | 3 | **1** | =1 |
| token 覆盖率 | 3.4% | **99.6%** | ≥90% |
| rgb/rgba 基色 distinct | 19 | **0** | ≤3 |
| 冗余声明 | 27 | **0** | =0 |
| `!important` | 2 | **0** | =0 |
| 同一选择器分散在多块 | 109 | 81 | 提示 |

`main.css` 1313 → **1171** 行。截图对比：`baseline/before-1440.png` → `baseline/after-1440.png`。

> 目标不是"变个样"，而是**"好像没换，但清楚多了"**。若某次改动让你觉得"变了个样"，方向就错了。

---

## 10. 阶段三迁移记录（进行中）

**做法**：每迁移一个组件，先补**特征测试**（只断言行为、id、role、文案，不断言样式类名），
再换原语，然后跑测试 —— 测试不改就绿，就是"功能不变"的证据。
最后删掉被原语取代的 legacy CSS 规则，并截图核对。

| 组件 | 原语替换 | 新增测试 | 状态 |
|---|---|---|---|
| `CreateProjectDialog.vue` | `UiInput` ×2 · `UiSelect` ×1 · `UiButton` ×2 | `CreateProjectDialog.test.js`（7 条） | ✅ 完成 |
| `ConfirmProjectDeleteDialog.vue` | `UiInput` ×1 · `UiButton` ×2 | 已由 `SessionSidebar.test.js` 覆盖（2 条） | ✅ 完成 |
| `ChatComposer.vue` | `UiButton` ×3（取消 / 停止运行 / 发送） | `ChatComposer.test.js`（10 条） | ✅ 完成 |
| `ChatComposer.vue` | `UiTextarea` ×1（bare + autoResize）· `UiSelect` ×1（bare + size=sm） | 同上（原语形态变化由截图验证） | ✅ 完成 |
| `SessionSidebar.vue` | `UiButton` ×9（含新的 `icon` / `align="start"` 两个 prop）+ 行结构重写 | `SessionSidebar.test.js`（11 条） | ✅ 完成（见 §13） |
| `SessionSidebar.vue` | 项目列表的**三种空**分开：加载失败卡 + 重新加载 · 加载中占位 · 真空态 CTA | `SessionSidebar.test.js`（11 → 14 条） | ✅ 完成（见 §18） |
| `stores/agent.js` | `bootstrap()` 由 `Promise.all` 改为 `Promise.allSettled` + 新增 `projectsError` / `retryProjects()` | `agent.test.js`（3 → 8 条） | ✅ 完成（见 §18） |
| `AgentWorkspace.vue` | `UiButton` ×2（Hero 的两个 CTA）+ 加载态重写 + 补上 5 个类名缺失的全部 CSS | `AgentWorkspace.test.js`（10 条，**此前零测试**） | ✅ 完成（见 §14） |
| `AgentWorkspace.vue` | 拆成 `WorkspaceHeader` / `WorkspaceConversation` / `WorkspaceWelcome` + `useSidebarPreferences` / `useProjectDialogs`；**454 → 206 行** | `AgentWorkspace.test.js` 的 10 条**一行未改即通过**；新增 `useSidebarPreferences.test.js` 6 条、`useProjectDialogs.test.js` 8 条 | ✅ 完成（见 §19） |
| `MessageActions.vue` | `UiButton` ×1（ghost / sm / icon） | 无（行为未变，由截图验证） | ✅ 完成（见 §15） |
| `ProposalCard.vue` | `UiButton` ×3（primary / secondary / ghost） | 无（同上；修掉了假禁用与无 hover） | ✅ 完成（见 §15） |
| `HumanInterventionCard.vue` | `UiButton` ×3 + `UiTextarea` ×1 | 无（同上） | ✅ 完成（见 §15） |
| `TodoPlan.vue` | 无（头部文案中文化） | 无 | ✅ 完成（见 §15） |
| `RunActivityCard.vue` | 只补了 `.run-activity-toggle:focus-visible`（**有意不套原语**） | 无 | 🔶 部分完成（见 §15） |
| `ActiveTaskStrip.vue` | `UiButton` ×1（ghost / sm / icon）+ hover 与字号补齐 + style 块规范化 | `ActiveTaskStrip.test.js`（10 条，**此前零测试**） | ✅ 完成（见 §16） |
| `ChatComposer.vue` | 只读仓库展示去边框／去底色 + `<label>`→`<span>` + 清掉 4 条死规则 | 无（行为未变，由 `composer-footer.html` 夹具验证） | ✅ 完成（见 §17） |

**删掉的 legacy 规则**（阶段三第一笔）：`.dialog-input`、`.dialog-input:focus`、
`.project-dialog-v2 .dialog-input`、`.dialog-actions button`、`.button-primary`、
`.button-secondary`、`.button-danger` 及其 hover/disabled。

> 附带修掉一个真实缺陷：`.dialog-input:focus` 原先写的是
> `box-shadow: 0 0 0 3px var(--c-danger-subtle)` —— **红色系的焦点环**。
> 阶段二把它的字面量收敛成了 token，所以记分卡看不出问题（它确实是合法 token），
> 但语义是错的（danger 颜色被当成 focus 颜色用）。
> 换成原语后由 `UiInput` 统一提供 accent 焦点环，这个错误自然消失。
> **教训：记分卡管不了"用错语义"，只有人看图能发现。**

**删掉的 legacy 规则（阶段三第二笔 · ChatComposer）**：`.send-button` / `.stop-button`
的全部外观规则（分布在 `main.css` 的 6 个追加层里），以及
`.send-button:not(:disabled){color;background}`、`:hover/:focus-visible`、`:disabled`。
底栏里只留下一条纯排布规则 `.composer-action { flex: 0 0 auto }`（外加两个断点里的
`order` / `width` / `margin-left`）。

> **同一批里又揪出两个记分卡看不见的真实缺陷：**
> 1. `.send-button:not(:disabled) { background: var(--c-text) }` —— 发送按钮**可点时的底色是近黑的 `#1c2321`**，
>    而 `:hover` 因为特异性更高落到 `.send-button:hover:not(:disabled){background: var(--c-accent-active)}`，
>    **一悬停就从近黑跳到深绿**，两个毫不相干的颜色之间硬切。切到 `UiButton variant="primary"` 后
>    静息态与悬停态同属一条绿色梯度。
> 2. `.send-button:not(:disabled):hover, …:focus-visible { outline: none }` —— **键盘焦点没有可见指示**。
>    原语的 `:focus-visible` 焦点环是内建的，换过来即修复。
>
> 这两个都属于"值全合法、记分卡全绿、但语义是错的"。**结论：记分卡保证不漂移，不保证正确；
> 每迁移一个组件都要真的看图、真的用键盘走一遍。**

**已知例外（写在白名单里，不是遗漏）**：

| 位置 | 未迁移的裸控件 | 原因 |
|---|---|---|
| `ChatMessage.vue:37` | `.code-copy-action`（在 markdown-it `fence` 渲染器返回的 HTML 字符串里） | 经 `v-html` 注入，**永远不可能换成 Vue 组件** —— 硬例外。 |
| `ChatMessage.vue` | `.message-expand-button` | **disclosure，不是动作按钮**：几何由一行文字 + 旋转箭头决定，套不上 28/36/44 的定高档位。已改为把状态补齐。 |
| `RunActivityCard.vue` | `.run-activity-toggle` | 同上（一行内含旋转箭头 + 摘要 + 贴右端状态胶囊）。已补 `:focus-visible`。 |
| `ActiveTaskStrip.vue` | `.active-task-select` | 整块是 chip 内容，外面再包一层按钮会双重边框。 |
| `WorkspaceConversation.vue` | `.new-content-button` | 悬浮在消息流右下角的**浮标**（"↓ 3 条新内容"），不是表单动作；它的定位与出现时机由 `useSmartScroll` 决定，套原语只会把那一套布局规则拆散。 |
| `AgentWorkspace.vue` | `.sidebar-backdrop` | **不可见**的全屏遮罩（窄屏点它关侧栏）。它没有外观，`UiButton` 的边框/底色/高度全都用不上，而且它必须铺满视口 —— 套了反而要一条条覆盖回去。 |
| `SessionSidebar.vue` | `.thread-item` / `.rail-session` / `.rail-action` | **列表行**，不是按钮组：宽度撑满、高度由内容决定、选中态与状态点自己一套。 |
| `SessionSidebar.vue` | `.thread-delete` | 行内删除键，**绝对定位在行右端**（见 §13 的兄弟节点结构）；它要精确叠在行上，不能有自己的尺寸档。 |
| `SessionSidebar.vue` | 项目菜单的 `role="menuitem"` 两项 | 菜单项，`role` 与样式都由菜单容器统一管；`UiButton` 不带 `menuitem` 语义。 |

> 这张表的判据是**「套上原语之后要不要一条条覆盖回去」**：要覆盖的越多，说明它本来就不是
> 设计系统里的那种东西。上面前四条是形态不合，后五条是语义不合（浮标 / 遮罩 / 行 / 菜单项）。

> **§17 已处理掉那条信息架构问题。** 原文记的是：模型选择器与仓库展示是**同一视觉形态**
> （都是带边框的小胶囊），但一个是真控件、另一个只读，视觉上两者一样重，用户会去点那个点不动的。
> 已于阶段三第九笔修掉 —— 只读项去掉了边框与底色，并把 `.repo-provider-select` 等
> 四条死规则一并清除。

---

## 11. 阶段三第三笔 · 键盘焦点可见性（已完成）

**问题**：`ui/src/styles/main.css` 里有 **15 处 `outline: none` / `outline: 0`**，其中 8 处写成了
`:hover, :focus-visible` 合写并且直接 `outline: none` —— 等于**把这些控件的键盘焦点环整个关掉了**。
`ui/stylelint.config.mjs` 早就把 `outline:none` 列为禁止，但 `main.css` 是 legacy、不在
`npm run lint:css` 的门内（只卡 `src/components/ui/**` 与 `layout/**`），所以从来没被拦住。

**三类处理**：

| 类 | 条数 | 情况 | 处理 |
|---|---|---|---|
| A | 8 | `:hover, :focus-visible` 合写 + `outline: none`，焦点完全不可见 | **拆成两条**：`:hover` 保留原视觉并继续抑制鼠标态的环形；`:focus-visible` 复制同样的视觉 + `outline: 2px solid var(--c-accent); outline-offset: 2px` |
| B | 3 | `.repo-field input` / `.composer textarea` / `.project-rename-input`，已有 `box-shadow` 替代环 | 保留 `outline`，**加注释说明为什么可以留** |
| C | 4 | `.workspace-title-input` / `.repo-provider-select` / `.repo-control-input input` / `.model-picker select`，焦点只改 `border-color`，太弱 | 给它们的 `:focus` / `:focus-within` **补 `box-shadow: 0 0 0 3px var(--c-accent-subtle)`**，与 `UiInput`、弹窗保持同一种环 |

A 类涉及的 8 个控件：`.sidebar-toggle`、`.new-button`、`.thread-delete`、`.message-copy-button`、
`.code-copy-action`、`.new-content-button`、`.quick-prompt`、`.rail-session`。

**为什么必须拆开而不是在原规则里补 outline**：`:hover` 和 `:focus-visible` 合写时，
鼠标悬停会连带出现焦点环 —— 那是错的。两者特异性相同（0,2,0），所以拆开后把
`:focus-visible` 放在后面，键盘聚焦且鼠标恰好也悬停时仍然以焦点环为准。

> **附带修掉一个真实缺陷：消息操作区键盘完全够不到。**
> `.message-actions` 原本是 `opacity: 0; visibility: hidden`，靠 `.message:hover` 才显示。
> 但 **`visibility: hidden` 的元素无法获得焦点**，于是 `.message:focus-within`（本来就是为键盘
> 准备的补救）永远不可能触发 —— 鸡生蛋问题，**键盘用户永远够不到「复制」按钮**。
> 改成 `opacity: 0; pointer-events: none`（显示时 `pointer-events: auto`）：看不见也点不到，
> 但仍然可以 Tab 进去，一旦进去 `:focus-within` 就把操作区显示出来。

**验收**：`npm test` 25 passed · `npm run audit` 全部通过（冗余声明 0）· `npm run lint:css` 0 errors ·
`npm run build` ✓ 1.01s · `npm run shots` 3/3，与改动前的字节数完全一致
（39514 / 61696 / 77453）—— **焦点环只在键盘聚焦时出现，默认视口不变**。

**焦点可见性怎么验**（静态截图看不到 `:focus-visible`，必须真的聚焦再读计算样式）：
夹具 `ui/preview/focus.html` + `focus.js` 会逐个聚焦受影响的控件，读 `getComputedStyle` 的
`outline*` 与 `box-shadow`（**必须在 `blur()` 之前读，`getComputedStyle` 返回的是实时对象**），
焦点环画在祖先容器上的（`:focus-within`）要趁元素仍聚焦时往上找一圈，最后把结果渲成一张表：

```
node ui/scripts/capture.mjs http://127.0.0.1:3000/preview/focus.html shots --widths 1180 --height 900 --name focus
```

结果存档：`docs/design/baseline/phase3-focus-visible-1180.png` —— **15 / 15 通过**。

> **又一次印证同一条教训**：把 `:hover, :focus-visible` 拆开之后，`audit` 的「冗余声明」
> 从 0 跳到 2 —— `.thread-delete:hover` 里的 `color`/`background` 早就被更靠后的
> `.thread-delete:hover { color; background }` 覆盖了，只是因为同一规则里还挂着
> `:focus-visible`（它没被覆盖）而查不出来。**收窄共享选择器列表是一种有效的死代码探测手段**，
> 与上一笔 `.new-button` 的情况完全同型。

---

## 12. 阶段三第四笔 · 收回 composer 的两个"已知例外"（已完成）

**为什么原语不够用**：composer 的两个控件都不是"独立的带框控件"，而是
**"整张卡片就是输入区"** 的形态 —— 焦点环画在外层容器上，控件自身不能带边框。
原来的 `UiTextarea`/`UiSelect` 只会画带框的形态，所以这两个控件一度被记为"已知例外"。
这一笔不是"绕过例外"，而是**把原语补到能表达这个形态**。

**新增 `ui/src/components/ui/UiTextarea.vue`**

| 能力 | 说明 |
|---|---|
| `bare` | 去掉边框、背景与内边距，把"框"交给外层容器，焦点由容器用 `:focus-within` 表达 |
| `autoResize` | 随内容增高。**先 `height='auto'` 再读 `scrollHeight`**，否则高度只能单向增长 |
| `minHeight` / `maxHeight` | 增高的上下限（px），由调用方给 —— 这是产品决策，不是设计 token |
| `rows` / `resize` / `invalid` / `size` | 与 `UiInput` 同源 |

**`UiSelect` 增加 `bare` 与 `prefix` / `suffix` 插槽**：`bare` 去掉边框、背景与内边距，
并**关掉自绘箭头**（改由 `suffix` 插槽自己放一个）；插槽做法与 `UiInput` 的前后缀完全同源，
连 `has-affix-start/end` 的 padding 计算都对齐。

**迁移结果**：`ChatComposer.vue` 的 `<textarea>` → `UiTextarea bare auto-resize :min-height="70" :max-height="140"`；
模型选择器 → `UiSelect bare size="sm"` + `#prefix`（orbit 图标）+ `#suffix`（chevron）。
同时删掉 `main.css` 里 4 层追加的 `.composer textarea` 规则，`.model-picker select` 只剩 `max-width: 145px`。

**★ `outline: none` 的正确写法（与 §11 呼应）★**
`bare` 形态下必须压掉控件自己的默认焦点环，否则同一个控件上会出现两圈。
但 `stylelint` 的 `declaration-property-value-disallowed-list` 是硬性禁止 `outline: none`。
正确的做法不是放宽规则，而是**用行内 disable 注释把例外变成可 grep 的一条**：

```css
.ui-textarea.is-bare .ui-textarea__field:focus-visible {
  /* stylelint-disable-next-line declaration-property-value-disallowed-list */
  outline: none;
}
```

规则保持硬性，全项目只有这一处例外、且带理由。**注意 disable 注释要写在声明那一行之前** ——
写在选择器之前只会禁用选择器那一行，声明照样报错（这一版就是这么错的）。

**验收（实跑）**：`npm test` → 25 passed（测试文件一行未改）· `npm run audit` → 全部通过 ·
`npm run lint:css` → 0 errors / 19 warnings · `npm run build` → ✓ 956ms · `npm run shots` → 3/3。

**肉眼核对的可见差异**（用 `mix-blend-mode: difference` 叠图定位，见 §10 的做法）：

1. 模型选择器的 chevron 与文字**贴得更紧**，胶囊整体略窄 —— 原来是 select 自己的 padding 撑开的，
   现在由 `suffix` 插槽 + `padding-inline-end: calc(1em + var(--space-4))` 决定。观感更紧凑，判断为改善。
2. composer 卡片**矮了约 5px**，底栏相对占位文字近了一点 —— 原 `main.css` 给 textarea 的
   `padding: 4px 0` 与 `line-height: 1.55` 由原语的 `padding: 0` + `--leading-normal` 取代。
3. 输入文字字号 `--text-md`(13px) → `--text-base`(12px)，即与 `UiInput`/`UiSelect`/`UiButton` 一致。
   这一条是**有意的收敛**：原先三个控件三种字号（原语 12px、输入区 13px、token 注释里写输入区 16px），
   现在统一到量最大的那一档。

**没有为原语单独写单元测试，理由说清楚**：`autoResize` 依赖真实的 `scrollHeight`、
`bare` 是纯视觉形态，两者在 happy-dom 里都测不出真值 —— 硬写只会得到一条永远通过的假测试。
它们的验收方式是截图，`ChatComposer.test.js` 的 10 条覆盖的是**行为**（v-model、Enter 发送、
IME 合成、禁用态、插槽点击），那才是会被改坏的契约。

**存档**：`docs/design/baseline/phase3-composer-primitives-1480.png`（1.7× 放大前后对比），
`after-{375,768,1440}.png` 已刷新为最新状态。

---

## 13. 阶段三第五笔 · 侧栏迁移（已完成）

侧栏是**全项目控件最密集的一屏**（12 类可交互元素），也是"漂移"最集中的地方。
动手前的第一件事不是改代码，而是**把这 12 类控件的真实体征量出来**——
夹具 `ui/preview/sidebar.html` + `sidebar.js` 挂载真实组件，逐个 `el.focus()`
后读 `getComputedStyle` 与 `getBoundingClientRect`，输出尺寸/边框/背景/字号与可达性表：

```
node ui/scripts/capture.mjs http://127.0.0.1:3000/preview/sidebar.html shots --widths 1320 --height 760 --budget 6000 --name vitals
```

**量出来的问题（迁移前）**：

| 现象 | 具体 |
|---|---|
| 不在尺寸档上 | 两个新建按钮 **40px**，而 `UiButton` 的档位是 28 / 36 / 44 |
| 圆角漂移 | 两个新建按钮 **10px**，原语是 6px |
| 同类控件差 1px | 收起态 `.rail-action` 39×36 与 `.rail-session` 40×36 |
| 字号跌破可读下限 | `.show-more-button` 与空项目里的「新建」只有 **10px** |
| **非法 HTML** | `.thread-delete` 是 `<span role="button" tabindex="0">`，**嵌在 `<button class="thread-item">` 内部** —— `<button>` 的内容模型禁止交互式后代 |

> 关于最后一条，**实测纠正了一个想当然的判断**：12/12 候选项 `el.focus()` 全部成功
> （Chrome 允许 button 内带 tabindex 的元素被程序化聚焦），所以这不是"够不到"，
> 而是"**程序化可聚焦 ≠ 能按 Tab 到达**"，外加结构本身违规。
> **这正是夹具的价值：它推翻了一个靠读代码得出的结论。**

**给 `UiButton` 补的两个能力**（迁移过程中被逼出来的）：

| prop | 作用 | 为什么必须是 prop |
|---|---|---|
| `icon` | 方形图标按钮，宽高相等、去掉横向内边距，并按档覆盖宽度（sm/md/lg 各自等于对应的 `--control-h-*`） | 28px 是最小档，低于它点击区就不够用 |
| `align="start"` | 块级按钮内容靠左，配合尾随的 `kbd` 用 `margin-left: auto` 推到最右 | **在页面层用单类压不住原语**：Vue scoped style 产出的是 `.ui-btn[data-v-x]`（特异性 0,2,0），全局单类只有 (0,1,0)。**原语的可调项要进 props，不要在外面覆盖。** |

**行结构重写**：`<div class="thread-row">` 包住 `<button class="thread-item">` 与**兄弟节点**
`<button class="thread-delete">`，删除键用 `position: absolute` 叠在行右端。
副作用是好事：**不再需要 `@click.stop` / `@keydown.enter.stop.prevent`**，
`select-thread` 天然不会被误触发；删除键也从 20×20 长到 24×24。
`active` 类保留在 `.thread-item` 上（既有 `.thread-item.active` 系列规则一条都不用改），
另在 `.thread-row` 上挂 `is-active` 供行操作使用。

**★ 这里差点漏掉一个回归，是截图比对抓出来的 ★**
`.thread-delete` 的可见性判据里原本有 `.thread-item.active .thread-delete { opacity: 1 }`。
删除键搬成兄弟节点后这条**后代选择器不再匹配**，于是**当前选中的会话行上的删除键消失了**——
代码能跑、测试全绿、记分卡全绿，只有把迁移前后的截图并排看才发现。
修法：给 `.thread-row` 加 `is-active`，判据改为 `.thread-row.is-active .thread-delete`。
**教训：结构重写会让"依赖 DOM 层级"的选择器静默失效，这类失效只能靠看图，测试抓不到。**

**同时修掉一个上一笔埋下的真缺陷**：`@media (hover: none)` 里原来写的是
`.message-actions { opacity: 1; visibility: visible }`，但 §11 已把可点性改成用 `pointer-events` 控制
—— 触屏上这些按钮**看得见却点不动**。已改为 `.message-actions, .thread-delete { opacity: 1; pointer-events: auto }`
（顺带让触屏也能看到行删除键，原先它只能靠 hover 浮出）。

**顺带清出的死代码**（在 `ui/src` 全域 grep 命中 0 个文件）：`.new-button` 全家族（6 条）、
`.new-button-icon`、`.thread-list-inner`、`.collapsed-thread-label`，以及**收起态的一整片**
`.sidebar.collapsed .thread-item` / `.collapsed-thread-icon` 等 11 条 ——
收起态渲染的是 `.rail-*`、而 `.thread-list` 带 `v-if="!collapsed"`，**这些规则永远不会生效**。
`main.css` **1139 → 997 行**。

**页面上保留的规则只剩"原语管不到的东西"**：`.new-chat-button > span:first-child` 的图标色号与字号、
`.new-chat-button kbd` 快捷键胶囊、三个项目行图标按钮的 `flex: 0 0 auto`（不加会被标题挤瘦）、
svg 的几何参数、以及各处 `margin` / `justify-self` 排布。

**验收（实跑）**：`npm test` → **4 files / 31 tests passed** · `npm run audit` → 全部通过
（token 覆盖率 99.6% / `var()`=1054 / 硬编码色 0 / 硬编码 px 4 / 冗余声明 0）·
`npm run lint:css` → 0 errors / 19 warnings · `npm run build` → ✓ 945ms · `npm run shots` → 3/3。

**一条测试的改法本身是结论**：原测试 `'deletes a thread by click and by keyboard…'` 用
`trigger('keydown', { key: 'Enter' })` 模拟键盘删除。删除键改成真 `<button>` 之后，
**Enter 由浏览器原生触发 click**，而 happy-dom 不会合成 —— 这条测试失败是**正确的**。
新断言改为守结构不变式：`expect(deletes[0].element.tagName).toBe('BUTTON')` 且
`expect(deletes[0].element.closest('button')).toBe(deletes[0].element)`（证明外面没有别的 button 祖先）。

**有意为之的可见变化**：两个新建按钮 40→36px、圆角 10→6、字重 650→500；
`.sidebar-toggle` 从有框有底的 30×30 变成 ghost 的 28×28；
三个项目行图标从 23–25px 变成 28×28 方形（**点击区变大是刻意的**）；
`.show-more-button` 10→12px、高 27→28；空项目的「创建第一个项目」从无框强调字变成实心 primary 小按钮。

**存档**：`docs/design/baseline/phase3-sidebar-760.png`（左右并排：同一视口各裁左侧 320px，
左为迁移前、右为迁移后），`after-{375,768,1440}.png` 已刷新。

## 14. 阶段三第六笔 · 补齐 §6 状态矩阵，抓到 Hero 全无样式（已完成）

**起因**：§6 的矩阵此前只是「设想」，格子里的字没有任何人验过。补矩阵意味着**每一格都得真的渲染出来**，
于是先给零测试的主区 `AgentWorkspace.vue`（447 行）补安全网，再搭 `ui/preview/states.html` 种状态。

### 抓到的主缺陷：主区 Hero 有 5 个类名在全 `ui/src` 里没有任何 CSS

```
grep 'welcome-primary|welcome-secondary|welcome-actions|welcome-capabilities|welcome-mark' ui/src
→ 只命中 AgentWorkspace.vue（模板）与新建的 AgentWorkspace.test.js，零条 CSS 规则
```

后果两条，都在**新用户的第一屏**：

1. 「开始新聊天」/「创建项目」两个 CTA 一直以**浏览器默认按钮**（系统灰底描边）渲染 ——
   全应用唯一两个原生外观的控件。
2. 「独立会话 / 纯对话模式 / {模型}」三个能力标签挤成一行**无分隔连续文字**
   （截图里就是 `独立会话仓库上下文deepseek-flash` —— 这个现象在更早的真实截图里就出现过，当时没解释）。

**为什么之前没人发现**：这一屏只在 `!agent.currentThread` 时出现，
**账号下只要还有一个会话就再也回不去**。手工点不出来，测试不渲样式，记分卡只量颜色/字号/圆角——
而这两个缺陷恰好只违反「排布与层级」，不违反其中任何一项。
**这是「状态矩阵必须能真的渲染」这句话的第一个实证。**

**连带缺陷**：`:last-child` 脆弱。原样式是 `.empty-state p:last-child`，
但无会话分支里 `<p>` 后面还有 `.welcome-actions`，于是那一屏的段落拿不到 `max-width: 510px`。
已加 `.empty-copy` 类，判据改为 `.empty-state p:last-child, .empty-copy`。

### 修法

| 位置 | 之前 | 现在 |
|---|---|---|
| 两个 CTA | 裸 `<button>`，无样式 | `<UiButton variant="primary">开始新聊天` / `<UiButton variant="secondary">创建项目` |
| 能力标签 | 三个连续 `<span>`，无样式 | 胶囊（1px `--c-border` 边框 + `--radius-full` + `--text-xs` + `700`），**与既有的 `.empty-state .hero-kicker` 同一套语汇** |
| 加载态 | `<div class="empty-state">正在加载会话...</div>` 裸文字 | `role="status" aria-live="polite"` + 纯 CSS spinner + 文案 |

新增的 CSS：`.welcome-mark`（居中）/ `.welcome-actions`（居中 + `gap` + `margin-top`）/
`.welcome-capabilities`（居中 + `wrap`）/ `.welcome-capabilities span`（胶囊）/
`.loading-state`（纵向居中 + `gap`）/ `.loading-spinner`（`1.5em` 见方、`0.125em` 边框、
`border-top-color: var(--c-accent)`、`animation: loading-spin calc(var(--dur-base) * 3) linear infinite`）/
`@keyframes loading-spin` / `@media (prefers-reduced-motion: reduce)` 关掉动画。
**spinner 的尺寸用 `em` 不用 `px`** —— 与 `UiButton` 内部那个指示器同源，跟随字号缩放。

### 顺带修掉的一处工具缺陷：`audit-css.mjs` 把 `@keyframes` 步骤当成选择器

我加了第二个 `@keyframes`（`loading-spin`）之后，「冗余声明」从 0 变成 1。二分（`tmp/bisect-redun.mjs`）证明元凶就是它。

根因：`ui/scripts/audit-css.mjs:274` 对 `@keyframes` 走 `walk(..., 'keyframes', ...)`，
内层 `to` / `from` / `0%` 被 push 成 `{ selector: 'to', atRule: true }`（`:286`）；
但 `:629` 构造 decl 时**丢掉了 `atRule`**，于是 `:872` 的冗余检查把
`UiButton.vue` 与 `main.css` 里各自的 `to { transform: rotate(360deg) }` 当成同一个选择器的重复声明。
**事实是错的：不同 `animation-name` 的关键帧互不覆盖。**

修法：`:629` 的 decl 增加 `atRule: !!rule.atRule`；`:872` 改为 `if (!d.selector || d.atRule) continue`。
修后「规则块 536」与修改前完全一致，证明没有影响别的计数。
**已同步回 `.agents/skills/frontend-craft/scripts/audit-css.mjs`**（两边 SHA256 均为 `AE757CDE…A51`）——
否则 skill 里那份会继续对每个「再加一个动画」的人误报。

**二分方法（可复用）**：逐条把新增规则替换成注释、在**完整 `src` 语料**上跑 audit。两个坑：
①`execFileSync` 在有未通过项时会抛异常，JSON 在 `error.stdout` 里，必须 catch；
②**只审单个文件没有意义**，冗余判据是跨文件聚合的（把 `main.css` 单独审会得到 0）。

### 验收（实跑）

`npm test` → **5 files / 41 tests passed**（新增 `AgentWorkspace.test.js` 10 条：加载态不闪 Hero、
两个 CTA 各自的路由、三种 Hero 文案、错误横幅与消息共存、标题就地编辑的三条路径、空白标题不发请求、
`isComposing` 期间回车不保存、无会话时不可编辑）· `npm run audit` → 全部通过
（token 覆盖率 99.6% / `var()`=1070 / 硬编码色 0 / 硬编码 px 4 / **冗余声明 0**）·
`npm run lint:css` → 0 errors / 19 warnings · `npm run build` → ✓ 941ms ·
`npm run shots` → 3/3（40166 / 61370 / 76814 B）。**截图与 `after-*` 基线不同是预期的** ——
真实应用此刻正处在 Hero 状态，能力标签的胶囊化直接反映在截图里。

**存档**：`docs/design/baseline/phase3-states-920.png`（6 格纵向拼版：无会话 / 普通聊天空态 /
项目会话空态 / 加载态 / 错误态 / 正常态）、`phase3-states-empty-1472.png`（第一屏 1:1）。

**新增的工程约束（记在 §6 里）**：`ui/scripts/capture.mjs` 把 URL 交给 shell，
**`&` 在那里是命令分隔符** —— 夹具的查询参数只能有一个；`?a=1&b=2` 会报
`'b' is not recognized as an internal or external command`，加引号也救不了。

---

## 15. 阶段三第七笔 · 消息块迁移（已完成）

**范围**：`ChatMessage.vue` 分发的五个子组件里的四个 —— `MessageActions.vue`、`ProposalCard.vue`、
`HumanInterventionCard.vue`、`TodoPlan.vue`。

### 为什么要先建夹具

`ChatMessage` 能渲染六种 chunk kind，但**现有会话数据里只有 `text` 和 `run_activity`**：
`proposal` / `intervention` / `todo` / `error` 这四种块**既点不出来也截不到**。
所以在动模板之前先建了 `ui/preview/messages.html` + `ui/preview/messages.js`，
把 16 种情况铺开成一张矩阵（用户短消息 / 用户 >7 行 / 助手 Markdown + 代码块 /
执行记录折叠·运行中·失败 / 清单部分完成·全部完成 / 方案待确认·已批准·已拒绝 /
人工介入待答复·正在恢复·已答复 / 错误块共存·单独）。

夹具同样支持 `?cell=N` 只渲染第 N 格（1:1、单列）——**这是拿某一格大图的唯一正确方法**，
见下面「一条失败的尝试」。运行中的用例必须用相对现在的起点
（`new Date(Date.now() - 74000).toISOString()`），否则「用时」会算出几百天。

```bash
# 整张矩阵（迁移前后各截一次）
node ui/scripts/capture.mjs "http://127.0.0.1:3000/preview/messages.html" tmp/msg --widths 1560 --height 2600 --budget 9000 --name before
# 单格 1:1（0..15）
node ui/scripts/capture.mjs "http://127.0.0.1:3000/preview/messages.html?cell=8" tmp/msg --widths 900 --height 620 --budget 6000 --name c8
```

### 迁移前量到的问题

| # | 现象 | 根因 |
|---|---|---|
| 1 | 清单头是英文 `2 out of 4 tasks completed` | `TodoPlan.vue` 模板里直接写死英文，在一个 100% 中文的界面里 |
| 2 | 方案卡「调整方案」与「拒绝实施」两个次要按钮**几乎分辨不出来** | 两者共用 `.proposal-button` 一套外观 |
| 3 | 方案的三个按钮**禁用态与可点态一模一样**（假禁用） | 模板传了 `:disabled`，但 `.proposal-button` 家族**完全没有 `:disabled` 规则** |
| 4 | 次要按钮**没有任何 hover 反馈** | `.proposal-button:hover` 把 `border-color` / `background` 设成了与静息态**完全相同**的值 |
| 5 | 主按钮一悬停**从品牌绿跳到另一个绿** | `.proposal-button-primary:hover` 用的是 `--c-success`，与 `--c-accent` 不是同一条梯度（与早期发送按钮同型） |
| 6 | 人工介入的选项按钮是**小胶囊**、提交按钮是**琥珀实心** | 各写各的；且 `.intervention-options button:disabled { cursor: default }` 只改光标不改外观 |
| 7 | `.intervention-options button` / `.intervention-reply button` / `.run-activity-toggle` **没有 `:focus-visible`** | §11 那轮只修了「写成 `outline: none`」的 15 处，这三个是「压根没写过」 |
| 8 | `.message-expand-button` 的规则**分散在两块**（结构在 `main.css:207-213`，颜色在 `main.css:542-549`） | 追加式修改的遗留 |

### 分类原则（这一笔的核心决策）

**设计系统的按钮是给「动作」的；disclosure 与文内链接是另一种控件。**

据此**刻意不套 `UiButton`** 的三处，改为「把状态补齐 + 补注释说明为什么」：

- `.message-expand-button` —— 气泡里的一行文字 + 旋转箭头；
- `.run-activity-toggle` —— 一行的容器，内含旋转箭头 + 摘要 + 贴右端状态胶囊，
  几何**由内容决定**，套不上 28 / 36 / 44 的定高档位；
- `.active-task-select` —— 整块就是 chip 内容，外面再包一层会双重边框。

**硬例外（永远不可能迁移）**：

- `.code-copy-action` —— 它写在 markdown-it 的 `fence` 渲染器返回的 **HTML 字符串里**
  （`ChatMessage.vue:37`），经 `v-html` 注入，**永远不可能换成 Vue 组件**；
- `.repo-control-input` —— 只读的仓库展示。

### 改动

| 文件 | 改动 |
|---|---|
| `MessageActions.vue` | `.message-copy-button` → `UiButton variant="ghost" size="sm" icon`（svg 进默认插槽；`UiButton` 未声明 `inheritAttrs: false`，`aria-label` / `title` 正常透传） |
| `ProposalCard.vue` | 三个按钮 → `primary` / `secondary` / `ghost`，都带 `:disabled` |
| `HumanInterventionCard.vue` | 选项 → `UiButton variant="secondary" size="sm"`；textarea → `UiTextarea`（`rows=2`）；提交 → `UiButton type="submit" variant="primary"` |
| `TodoPlan.vue` | 头部改 `已完成 {{ n }} / {{ total }} 项`；`☷` 加 `aria-hidden="true"` |

**提交按钮从琥珀改成品牌绿**：警告色表示「小心」，不表示「确认」。
在琥珀色的卡片里放一个品牌绿主按钮，比用琥珀色实心按钮更对 —— 卡片本身已经在说「注意」。

`main.css` 1025 → 1017 行，花括号 418/418 平衡。删掉 `.proposal-button` 全家族 5 条、
`.intervention-options button`（含 `:disabled`）、`.intervention-reply textarea` 与 `button`、
`.message-copy-button` 的外观三块（只留 `svg { width: 17px; height: 17px }`）、
`.composer-interaction-hint button`；合并 `.message-expand-button` 的两块；
新增 `.intervention-input { flex: 1; min-width: 0 }` 与 `.run-activity-toggle:focus-visible`。

### 验收（实跑）

`npm test` → **5 files / 41 tests passed**（测试一行未改）· `npm run audit` → 全部通过
（token 覆盖率 99.6% / `var()`=1029 / 硬编码色 0 / 硬编码 px 4 / 冗余声明 0；
**规则块 536 → 523**、「同一选择器分散在多块」64 → 62）· `npm run lint:css` → 0 errors / 19 warnings ·
`npm run build` → ✓ 985ms · `npm run shots` → 3/3（40166 / 61370 / 76814 B，**与本轮改动前完全一致**）。

> 截图字节完全一致是**预期**的：真实应用此刻在 Hero 态，消息块没有出现在任何一屏里。
> **这正是这个夹具存在的理由 —— 改动最需要看的那部分，恰恰是默认截图永远拍不到的。**

**存档**：
`docs/design/baseline/phase3-messages-before-1560.png`（16 格整张，迁移前）、
`phase3-messages-after-1560.png`（迁移后）、
`phase3-proposal-900.png`（方案卡 1:1）、`phase3-intervention-900.png`（人工介入卡 1:1）、
`phase3-todoplan-900.png`（清单卡 1:1）。

### 一条失败的尝试（别再走一遍）

想做「迁移前后并排图」，用 `overflow: hidden` 的窗口从两张 1560 整屏截图里裁同一区域。
**失败了三次**：各行的 y 偏移靠目测估，估的比实际小约 200px，三次都截到了错误的行；
中途想用 PowerShell 改那个 HTML 又踩了下面那条 mojibake 教训。

**结论：要某一格的 1:1 图，用夹具的 `?cell=N` 直接渲染，不要在合成图上裁。**
整张 before / after 各存一份作证据即可。

### ★ 一条必须记住的工程教训（这次真的把文件写坏了）★

```powershell
# ❌ 会破坏 UTF-8 中文，且写出时带 BOM
(Get-Content file -Raw) -replace 'a','b' | Set-Content file -Encoding utf8
```

实测把 `ui/preview/messages-ab.html` 的 `<title>消息块迁移前后</title>` 写成
`娑堟伅鍧楄縼绉诲墠鍚?/title>`（`?` 处是被吃掉的 `<`），写出时还带上 BOM
（`s.charCodeAt(0) === 0xFEFF`），**页面整个渲染成空白**。

根因：这台机器上 `pwsh` 工具跑的是 **Windows PowerShell 5.1**，
`Get-Content -Raw` 默认按 **ANSI / GBK** 解码。

**结论：绝不用 PowerShell 对 UTF-8 文本文件做「读-改-写」，一律用 `edit` / `write` 工具。**
（此前的几次 `-replace` 之所以没出事，是因为都在流式处理短 ASCII 串。）

> **同族的第三次数错**：`(Get-Content file).Count` 在这个仓库上**也不可信** ——
> 它给 `docs/design/DESIGN.md` 报 463 行，而用 `read` 工具读是 **716 行**
> （`[System.IO.File]::ReadAllText` 数出 716 个 LF、0 个 CRLF，与 `read` 一致）。
> 这已经是第三次遇到「PowerShell 报的行号/行数 ≠ 文件真实行号/行数」
> （前两次分别是差 ±4 与差 ±9）。**要行数或行号，只信 `read` / `grep` 工具。**

### 还欠的三件事

1. `ui/src/api/types.js` **缺 `todo` / `error` / `intervention` 三种 chunk kind 的形状** ——
   `ChatMessage.vue` 实际在分发六种，契约文件只记了三种。契约文件不完整比没有更危险：
   它会让人以为「没有别的了」。
2. `.run-activity-toggle` 只补了焦点环，未换原语（按上面的分类原则，这是有意的）。
3. `.active-task-cancel` / `.active-task-select` 所在的 `ActiveTaskStrip.vue` 尚未处理。

---

## 16. 阶段三第八笔 · 活跃任务条（已完成）

**为什么到现在才做它**：这个组件**只在有正在运行的任务时出现**（`v-if="tasks.length"`），
而 `activeRuns` 在默认数据里恒为 `[]`。**它从来没出现在任何一张截图里**，
所以之前七笔都没碰到它 —— 不是漏了，是看不见。

做法照旧：**先建可渲染它的夹具，再写测试，最后才动模板。**

### 先补夹具

给 `ui/preview/states.js` 加了第 ⑦ 格：四个任务，覆盖三种状态
（`running` / `queued` / `cancelling`）+ 一个超长标题 + 一个边界
（`thread.status` 说在跑、但本地 `activeRuns` 里没有 runId → 取消键不渲染）。

> 顺带发现：旧的 `phase3-states-920.png` 用的是 `--height 2900`，
> 而每格高 `900 × 0.62 = 558` 加标签约 586px —— **第 ⑥ 格「正常态」其实一直被裁掉了**，
> 我却按"6 格纵向拼版"写进了文档。现在改成 `--height 4200`，7 格全部可见。
> **教训：拼版图的 `--height` 要用「格数 × 单格高」算出来，不能目测给一个数。**

又新建了 `ui/preview/active-tasks.html` + `active-tasks.js` —— **只挂这一个组件**，
这样能用 `capture.mjs --scale 3` 把它放大三倍看点击区。整屏夹具做不到这件事
（1440×900 放三倍会超出图片尺寸上限）。这块挂两遍：四个真实任务，和一个空数组
（**肉眼确认「空数组时整条不渲染」，而不是只信断言**）。

```bash
node ui/scripts/capture.mjs http://127.0.0.1:3000/preview/active-tasks.html tmp/at --widths 740 --height 260 --scale 3 --budget 5000 --name tasks
```

### 先写测试（对着旧代码跑，必须全绿）

新建 `ui/src/components/ActiveTaskStrip.test.js`（**10 条，对着未改动的组件跑就全绿**）：
空数组整条不渲染 · 每个任务一个条目且标题与状态文案都在 · 三种状态各自的文案 ·
没有 title 退回 repoFullName、都没有就用「新任务」 · `activeId` 决定哪个是 `selected` ·
点条目发 `select` 带任务 id · 点取消发 `cancel` 带 `{threadId, runId}` ·
**没有 runId 的条目不渲染取消键** · 取消键有可读的 `aria-label`（不是只有一个 `×`）·
**取消键在条目内部且它自己不是嵌套在另一个 button 里的 button**。

### 量到的问题

| # | 现象 | 根因 |
|---|---|---|
| 1 | 取消键**悬停时零反馈** | 全文没有 `.active-task-cancel:hover` —— 和 `.proposal-button:hover` 同型 |
| 2 | 整条是按钮，**悬停也没有反馈** | 没有 `.active-task-item:hover` |
| 3 | `×` **紧贴在状态文字上**，点击区只有大约 10px 宽 | `.active-task-cancel { padding-left: var(--space-4) }`，除此之外没有任何内边距 |
| 4 | 状态文字靠**浏览器默认**的 `<small>` 尺寸 | `.active-task-select small` 只写了 `color`；这份样式表里其它每一处 `small` 都写了字号 |
| 5 | 这个组件是全项目唯一带 scoped `<style>` 的，却**过不了自己的 stylelint** | 规则之间没有空行（10 个 `rule-empty-line-before`）+ 声明顺序倒置 |

### 改动

- 取消键 → `UiButton variant="ghost" size="sm" icon`：拿到 **28×28 点击区**、原语自带的
  hover（`color: var(--c-text)` + `background: var(--c-surface-hover)`）与 `:focus-visible` 焦点环。
  只覆盖焦点环偏移：原语默认 `outline-offset: 2px`，而按钮已经贴到条目的圆角边框上，
  `+2px` 会画到边框外，收成 `-2px`。
- `.active-task-item:hover { border-color: var(--c-border-strong) }` —— **只改边框色不铺底色**，
  因为铺底色会和里面 ghost 按钮自带的 hover 底色撞成一片，看不出取消键自己被指到了。
- `.active-task-item` 加 `padding-right: var(--space-2)`，让 28px 的按钮不贴着圆角边框。
- `.active-task-select small { font-size: var(--text-xs) }` —— 显式给字号。
  **靠 UA 默认值等于没有设计。**
- style 块按原语那一套重排（规则之间空行、状态按 default → hover → focus → selected 排序）。

### 验收（实跑）

`npx vitest run src/components/ActiveTaskStrip.test.js` → **10 passed**（迁移前后都全绿 = 行为未变）·
`npm test` → **6 files / 51 tests passed** · `npm run audit` → 全部通过
（`var()` 1029 → 1031，其余不变）· `npx stylelint "src/components/*.vue"` → **0 problems**
（迁移前 11 problems）· `npm run build` → ✓ 1.00s ·
`npm run shots` → 3/3，字节 **40166 / 61370 / 76814，与改动前逐字节相同**（预期 —— 没有活跃任务）。

**存档**：`docs/design/baseline/phase3-active-tasks-740.png`（1:1 挂载 + `--scale 3`，
含「四个任务」与「空数组不渲染」两块）、`phase3-states-920.png`（重截为 7 格 / 4200px）。

---

## 17. 阶段三第九笔 · 只读的仓库展示不该长得像控件（已完成）

**这是组件迁移全部做完之后剩下三条里最该先做的一条**，因为它在**每一屏**都出现：
底栏右半部分那个「仓库」胶囊。

### 缺陷：两个并排的胶囊，一个真能点，一个点了没反应

```
.model-picker        { border: 1px solid var(--c-border); border-radius: var(--radius-sm); background: var(--c-surface); height: 30px }   ← 真的 <select>
.repo-control-input  { border: 1px solid var(--c-border); border-radius: var(--radius-sm); background: var(--c-surface); min-height: 30px } ← 只读文字
```

**同形不同能**。用户看到两个一模一样的胶囊并排，自然会去点右边那个，然后什么都不会发生。
这与最初诊断里「底栏三种交互层级视觉重量相同」是同一个病的残留。

### 顺带清出的死代码：那个位置本来是一个真的输入框

`.repo-provider-select`（含 `:focus`）、`.repo-control-input:focus-within`、
`.repo-control-input input`、`.repo-control-input input::placeholder` —— 四条规则全部
**在 `ui/src` 全域 grep 命中 0 次**。它们是「仓库曾经可编辑」那一版的遗留：
后来改成只读展示，模板换了、样式没删。**模板改成只读的那一刻，这四条就死了**，
但因为渲染出来"看起来正常"，一直没人发现。

### 改动

- **`.repo-control-input` 去掉边框与底色**。只读的事实不该长得像控件。
  底栏于是变成「**一个带框的控件（模型选择器）+ 两组纯文字（推理 / 仓库）**」，
  交互层级一眼可辨。`.repo-provider-label` 与 `.repo-fixed-name` 一起降到
  `--c-text-muted` / `--c-text-secondary`，即"上下文"那一档。
- **`<label>` → `<span>`**。它本来是 `<label>`，因为里面曾经有一个真 `<input>`；
  现在里面只有文字，**一个不指向任何控件的 `<label>` 是错语义**。改成 `<span>`。
- **加 `tabindex="0"`**：长仓库名会被 ellipsis 截断，鼠标能靠 `title` 看到全名，
  键盘用户却聚焦不到一个普通 `<span>`。加一个 tab 停靠点让 `title` 对键盘也可达。
- 删掉上面那四条死规则。
- **`.repo-fixed-name` 补 `min-width: 0`** —— 见下。

### ★ 新夹具当场抓到的第二个缺陷：那个 ellipsis 从来没有生效过 ★

`overflow: hidden; text-overflow: ellipsis; white-space: nowrap` 三件套写得都对，
但**父级的 `max-width` 从来没约束住它**：`.repo-fixed-name` 是 flex 子项，
flex 子项的 `min-width` 默认是 `auto`（= 不得小于内容宽度），
于是长仓库名把父级顶破、自己溢出去，**ellipsis 永远不触发**。
`min-width: 0` 一行修好。**这是"三件套齐全但就是不生效"的经典成因，
只有拿一个超长字符串去渲染才会暴露** —— 真实数据里的仓库名都很短，
所以这个缺陷在改前改后都不影响任何一张真实截图。

### 新夹具：`ui/preview/composer-footer.html` + `.js`

整屏截图里底栏只有几十像素高，看不清那两个胶囊到底像不像。这个夹具单独挂
`ChatComposer`，给了 620px 的宿主和**四种数据**（长仓库名 / 短仓库名 / 没有仓库 /
`chatOnly`），配合 `--scale 2` 就能把底栏放大到能直接下判断。

```bash
node ui/scripts/capture.mjs http://127.0.0.1:3000/preview/composer-footer.html tmp/rc --widths 900 --height 400 --scale 2 --budget 7000 --name footer
```

> `--widths 700` 时截不到截断效果，因为 `@media (max-width: 720px)` 里
> `.repo-control-input { max-width: none; flex: 1 }` 会生效（窄屏下仓库行占满整行，
> **不该截断**，这是对的）。要验截断必须用 ≥ 721px 的视口。

### 验收（实跑）

`npm test` → **6 files / 51 tests passed**（测试一行未改）· `npm run audit` → 全部通过
（规则块 523 → 520、`var()` 1031 → 1009、token 覆盖率 99.6% / 硬编码色 0 / 硬编码 px 4 /
冗余声明 0）· `npm run lint:css` → 0 errors / 19 warnings · `npm run build` → ✓ 1.06s ·
`npm run shots` → 3/3，字节 **40113 / 61029 / 76581**（与上一笔的 40166 / 61370 / 76814 不同 ——
预期，底栏变了）。`after-{375,768,1440}.png` 已刷新。

**存档**：`docs/design/baseline/phase3-repo-readonly-900.png`（1:1 夹具 + `--scale 2`，
四种数据同屏）。

---

## 18. 阶段三第十笔 · 补齐边界态，并抓到「加载失败冒充空态」（已完成）

这一笔把 §6 的**边界态那一列**从「写了个词」变成「真的渲染过、量过」。做法不是逐格肉眼
看一遍，而是**新建一张带自动探测器的夹具** `ui/preview/edges.html` ——
它把六种极端输入渲染出来，每格跑一次几何探测，并把判定结果画在截图下方。
`⬜` 就是这样被清零的。

### 新夹具：`ui/preview/edges.html` + `.js`

六格极端输入（全是真实数据里几乎不会出现、手工点不出来的）：

| 格 | 输入 | 期望 |
|---|---|---|
| ① | 300 字符不换行 URL + 200 字符宽代码行 + 宽表格，同一条助手消息 | 气泡内自己滚，视口不被撑破 |
| ② | 无空格的 120 字符会话标题 | 省略号，状态徽章不被挤走 |
| ③ | 60 字项目名 + 80 字会话名 + 超长仓库名 | 各自省略号 |
| ④ | 超长 todo 文本与日志行 | 卡片内折行 |
| ⑤ | 仓库地址塞 260 字符（**该输入没有 `maxlength`**） | 输入框内部滚动，弹窗不破版 |
| ⑥ | 项目列表加载失败 | 有出路，且不冒充空态 |
| ⑦ | 项目列表加载中 | 不冒充空态 |

```bash
node ui/scripts/capture.mjs "http://127.0.0.1:3000/preview/edges.html" tmp/ed --widths 1500 --height 8400 --budget 12000 --name edges
node ui/scripts/capture.mjs "http://127.0.0.1:3000/preview/edges.html?cell=3" tmp/ed --widths 1500 --height 1250 --budget 7000 --name e3
```

**探测器问三个问题**（每个都配了排除规则，否则报告里全是假阳性）：

1. **有没有元素越出 1440 视口**。排除「被祖先 `overflow-x` 裁掉的」——
   `pre { overflow-x: auto }` 里的 `<code>` 天然比视口宽，但用户看不到任何越界。
   只保留最内层的违规元素。
2. **有没有文字越出自己那张卡片**（只看叶子文本节点）。这条是必需的：外面的滚动容器
   一兜，第 1 条就报不出来了，可用户看到的是**一行字从卡片边框穿出去、在别处被切断**。
3. **有没有 `text-overflow: ellipsis` 写在 flex/grid 容器上**。
   `text-overflow` 只对块级/行内块容器及其行内内容生效；一旦元素是 flex/grid 容器，
   它的文本变成匿名 flex/grid 项，**省略号永远不会出现**，外观上是「被硬生生切断」。
   这是纯静态判据，不需要长内容也能查。

### 抓到的三个真缺陷

**A. 「项目列表加载失败」与「你还没有项目」在界面上完全一样。**
根因在 `ui/src/stores/agent.js` 的 `bootstrap()`：它用 `Promise.all` 并发取五个接口，
**任意一个 reject → 五个赋值全部跳过** → `this.projects` 保持 `[]` →
侧栏渲染的是「项目会出现在这里 / 创建项目并绑定仓库 / **创建第一个项目**」。
用户看到的是一句假话，而且他会去点那个必然也失败的按钮。主区虽然有一条错误的横幅，
但侧栏这块"权威指引"完全盖过了它。

改法三件：
- `bootstrap()` 换成 `Promise.allSettled`，**各自成败各自落地**，其中一个挂掉不再
  把已经拿到的四份数据一起丢掉。主区横幅仍然只显示第一条失败（行为不变）。
- 新增 `projectsError` 状态。它与 `error` 分开：`error` 是「刚才那件事失败了」，
  `projectsError` 回答的是结构性是非题「**到底有没有成功拿到项目列表**」。
- 新增 `retryProjects()` 动作，以及侧栏的**实线警告卡 + 「重新加载」按钮** ——
  与空态的虚线框刻意长得不一样（虚线读作"这里以后会有东西"，实线读作"这里出问题了"），
  并且那句「这不代表你还没有项目」直接写给用户看。

**B. 「还在读」是第三种空。** `projects` 为空还有一种成因：请求还没回来。
原来这三种共用同一个空态，于是首屏会先闪一下「创建第一个项目」再跳走。
新增 `projectsLoading` prop 与 `.project-loading`（虚线框 + spinner + 「正在加载项目…」），
与主区的「正在加载会话…」同一套语汇。

**C. 省略号写在了 flex 容器上，从来没用过。**
`main.css` 的 `.project-heading-main small { display: flex; … text-overflow: ellipsis }`
—— `small` 是 flex 行（左边 provider 角标、右边仓库名），**省略号静默失效**，
长仓库名被硬切。修法是把仓库名包一层 `<span class="repo-name">`，省略号落在它身上。
这个缺陷在默认数据下**看得见**（侧栏那三个项目的仓库名都超宽），修前是
`clumsyspc/test_coding_r`、修后是 `clumsyspc/test_codi…` —— 也就是`after-*` 基线
这一笔变化的原因。

**另修一处同型的**：`.todo-card li` 是 flex 行，装文字的那个 `<span>` 是 flex 项，
flex 项的 `min-width` 默认是 `auto`（不得小于内容宽度），于是一段不含空格的长串
（超长路径、超长标识符）会直接顶出卡片边框。补 `min-width: 0; overflow-wrap: anywhere`
后折行正常。**注意这份样式表里 `overflow-wrap: anywhere` 已经用了 4 处
（`.plain-text` / `.markdown-body` / 两条运行轨迹），`.todo-card li` 只是漏了** ——
同一类防护要么成体系，要么就会漏。

### 验收（实跑）

`npm test` → **6 files / 59 tests passed**（51 → 59：agent store +5、SessionSidebar +2、
加载态 +1）· `npm run audit` → 全部通过（规则块 530、distinct 选择器 517、
`var()` 1038、token 覆盖率 99.6% / 硬编码色 0 / 硬编码 px 4 / 冗余声明 0 / `!important` 0）·
`npm run lint:css` → 0 errors / 19 warnings · `npm run build` → ✓ 1.02s ·
`npm run shots` → 3/3，字节 **39961 / 60846 / 76400**（与上一笔的 40113 / 61029 / 76581 不同 ——
预期，就是缺陷 C 导致的仓库名省略号）。`after-{375,768,1440}.png` 已刷新。

**新增测试**（锁的是契约，不是实现）：
- `ui/src/stores/agent.test.js` 新增 5 条 —— 项目列表挂掉时其余四个接口的数据仍然落地 ·
  项目列表成功而别的接口失败时项目不被清空 · 全部成功时 `projectsError` 是空字符串
  （**「读到了、只是没有」必须与「没读到」区分得开**）· `retryProjects` 成功后清错并填数据 ·
  再次失败时保留错误文案。
- `ui/src/components/SessionSidebar.test.js` 新增 3 条 —— 加载失败时是重试卡而不是空态 CTA
  且点按钮发 `retry-projects` · 还在读时是 loading 占位而不是空态 CTA ·
  真正为空时仍是空态 CTA 且不发 `retry-projects`。

**存档**：`docs/design/baseline/phase3-edges-1500.png`（七格整张 + 每格判定表）、
`phase3-edges-message-1500.png`、`phase3-edges-sidebar-1500.png`、
`phase3-edges-todo-1500.png`、`phase3-edges-loadfail-1500.png`、
`phase3-edges-loading-1500.png`。

---

## 19. 阶段三第十一笔 · 拆 `AgentWorkspace.vue`（已完成）

阶段三里最后一个结构性动作。**顺序是先补测试再拆** —— 这个文件此前**零测试**，
直接拆等于没有安全网。所以上一笔先给它写了 10 条 `AgentWorkspace.test.js`
（断言的是 DOM 与文案，不是内部实现），这一笔拆完那 10 条**一行没改就通过**。

### 拆出来的五个单元

| 新文件 | 行数 | 为什么是它 |
|---|---|---|
| `ui/src/components/WorkspaceHeader.vue` | 136 | 标题改名有自己的一套状态（编辑中/保存中/保存失败），而且它同时是**状态胶囊文案**的唯一去处 |
| `ui/src/components/WorkspaceConversation.vue` | 165 | 消息区、未读按钮、输入框三者**共享同一个滚动上下文**（`useSmartScroll` 的未读数只在"不贴底"时累加），拆开任何一半状态都要穿过组件边界 |
| `ui/src/components/WorkspaceWelcome.vue` | 37 | 空态三条分支，且**只在没有会话时出现**——手工点不出来，必须能单独渲染 |
| `ui/src/composables/useSidebarPreferences.js` | 49 | 侧栏两项本地偏好；抽出来的理由是它有**两个会静默炸掉整个组件的坑**（见下） |
| `ui/src/composables/useProjectDialogs.js` | 77 | 项目增删改两个弹窗；两条**错误通道的分工**值得有个家（见下） |

`AgentWorkspace.vue` 因此从 **454 行降到 206 行**，剩下的只有三件事：
摆位置、接事件、管跨区域的那一点状态（标题保存态、弹窗开关）。

### 拆的时候定的两条分工

**一、受控组件 vs 自己管异步。** `WorkspaceHeader` 只持有"正在编辑"，改名要打接口，
异步与"保存失败"归父级 —— 因为 `titleSaving` / `titleError` 要显示在 Header 上，
数据却在父级。父级通过 `@rename` 接事件、通过 `:saving` / `:error-message` 传回来。
这**与 `SessionSidebar` 的项目改名不同**：那里组件自己管编辑态也自己发请求，
因为侧栏的项目改名没有"保存中/保存失败"两个可见状态要渲染。
**同一个仓库里两种分工并存是有意的**，判据是"失败要不要在控件旁边显示出来"。

**二、两条错误通道不能合并。** 新建/重命名失败写 `agent.error`（主区横幅），
删除失败写 `projectDeleteError`（留在确认框里）。原因很实在：确认框一关，
主区横幅会被下一次操作清空，用户就**再也看不到删除为什么失败**了。
这条分工此前没有任何测试，现在 `useProjectDialogs.test.js` 里有一条专门锁它
（断言删除失败时 `agent.error` 仍是空字符串、且确认框还开着）。

### 顺带修掉的两处

- **`localStorage` 抛异常**。它在隐私模式/配额满时是**抛异常**，不是返回 `null`。
  原来的读写各包了一层 `try`，但两处都在组件里，拆的时候差点漏掉。
  现在 `useSidebarPreferences.test.js` 里有两条直接让 `Storage.prototype.getItem` /
  `setItem` 抛 `SecurityError` / `QuotaExceededError`，断言组件不会挂。
- **存进去的是字符串数组，读回来可能是任意 JSON**（手改过、旧版本格式）。
  原来没有 `Array.isArray` 校验 —— 一个对象会被当成"折叠项目列表"用。
  现在补了校验，也有测试。

另外把"编辑到一半切会话"用 `:key="agent.currentThreadId"` 处理掉了：强制重挂
`WorkspaceHeader`，输入框不会跨会话留着。这比让子组件 `defineExpose` 一个
`resetDraft()` 再让父级去调它干净。

### 验收（实跑）

- `npm test` → **8 files / 73 tests passed**（59 → 73：新增 `useSidebarPreferences` 6 条 /
  `useProjectDialogs` 8 条；`AgentWorkspace.test.js` 的 10 条**一行未改**）
- `npm run audit` → 全部通过（范围 24 个文件 · 3732 行 · 规则块 530 · distinct 选择器 517 ·
  `var()` 1038 · 覆盖率 99.6% / 硬编码色 0 / 硬编码 px 4 / 冗余声明 0）
- `npm run lint:css` → 0 errors / 19 warnings
- `npm run build` → ✓ 1.04s
- `npm run shots` → 3/3，字节 **39961 / 60846 / 76400** —— 与改动前 **逐字节完全相同**。
  **这是一次纯搬家，最强的证据就是这个数字没动。**

状态矩阵夹具（`preview/states.html`，七格）重截后七格全部正常；
`phase3-states-920.png` 已刷新 —— 它比上一版少了约 3.6 KB，差的是**上一笔**
（§18）给侧栏加的"正在加载项目…"虚线占位，与本次拆分无关。
**注意它与 `phase3-*` 其他图的性质不同**：那些是"某一笔改动的存证"（append-only），
这一张是 §6 的**现役参照图**，所以随迭代刷新。

---

## 20. 视觉改版第一步 · 暖色调 + 近黑主色（已完成）

> 这一节起不再是"零视觉变化"的迁移，而是**有意的改版**。
> §1–§19 的每笔验收标准是"截图逐字节相同"；从这里开始标准换成
> "每个状态都重新看过、且对比度真的量过"。

### 起因

用户在看完阶段三之后说"感觉界面也没啥变化"。归因是对的：前 19 节动的是**结构与约束**，
主色、布局骨架、字体一个字没动 —— 那是刻意的（"零视觉变化"是当时的验收标准），
但它的代价是**把整个重构的视觉上限压低了**。

### 定调

用户选定：**米白底 + 近黑主色**（m03558）。

### 改了什么

**`ui/src/styles/tokens.css` 第 1 节（中性色阶）→ 暖灰。**
色相偏橙黄（约 35°），饱和度极低 —— 暖体现在灰里，不在主色里。
只把主色改暖而灰还是冷灰，结果是一块发暖的东西贴在发青的底上，读起来是脏。

| token | 旧 | 新 | 说明 |
|---|---|---|---|
| `--c-bg` | `#ffffff` | `#faf7f2` | 米白 |
| `--c-bg-subtle` | `#f7f8f8` | `#f1ebe2` | 用户气泡、代码块、状态胶囊底 |
| `--c-surface` | `#ffffff` | `#ffffff` | **刻意保持纯白** |
| `--c-surface-hover` | `#f2f4f3` | `#f4efe7` | |
| `--c-border` | `#e4e7e6` | `#e6dfd4` | |
| `--c-border-strong` | `#d3d8d6` | `#d3c8b9` | |
| `--c-text` | `#1c2321` | `#1f1b16` | 暖黑 |
| `--c-text-secondary` | `#525d59` | `#574f47` | |
| `--c-text-muted` | `#656e6a` | `#6b6259` | |
| `--c-text-inverse` | `#ffffff` | `#faf7f2` | 反白用米白，避免在暖底上发灰 |

**`--c-surface` 保持纯白是关键**：它与 `--c-bg` 的 4% 明度差就是"卡片浮在页面上"的
全部来源。把两者调成同一个值，所有卡片会立刻失去边界感。

**第 2 节（主色）→ 近黑。** `--c-accent: #1f7667` → `#231e18`，
hover `#1a655a` → `#3b342b`，active `#155349` → `#4e4539`，subtle `#eef5f3` → `#efe9df`。

两条决策写进了注释：

- **为什么是近黑而不是彩色**：暖米白底上放彩色主色，两者会互相拉低 ——
  冷色在暖底上发脏，暖色在暖底上糊成一片。近黑没有色相，不参与这场打架。
- **hover/active 是变亮而不是变暗**（与常见的彩色主色相反）：近黑几乎没有变暗的
  余地，`#231e18` 再暗就跟正文分不开了。做成"越交互越亮"的单向梯度，反馈反而更清楚。
- **代价（已知且有意）**：主色不再是品牌识别的载体。绿色彻底退出，
  logo 里的绿成了全应用唯一的彩色。

**第 3 节（语义色）→ 暖化降饱和。** `--c-success` `#2f7d5b` → `#3d6b4c`、
`--c-warning` `#8f6119` → `#8a5a1c`、`--c-danger` `#a8453f` → `#a4483c`，浅底同步暖化。
饱和的绿/红铺在暖米白上会往外跳，看起来像贴上去的。

**遮罩与阴影的基色跟着暖灰走**：`rgba(20, 28, 25, …)` → `rgba(31, 26, 21, …)` /
`rgba(38, 30, 22, …)`。冷黑阴影落在米白上会发青。

**`ui/src/styles/main.css`：把 `--c-surface` 换成 `--c-bg` 的四处**
（`body, .app-shell, .workspace, .message-list` 那一块、`.workspace`、`.workspace-header`、
`.sidebar`）—— 不改这几处，米白根本不会出现，因为它们是最后生效的那一层。

### 对比度：真的量过

新建 `tmp/contrast.mjs`（WCAG 计算器，19 组配对，未通过则 exit 1），**19/19 全部通过**：

| 配对 | 对比度 |
|---|---|
| 正文 / 页面底 · 次级底 · 卡片 | 16.02 / 14.45 / 17.12 |
| 次级说明 / 三种底（取最差） | 6.78 |
| 弱化文字 / 三种底（取最差） | 5.04 |
| 反白 / 主色实心按钮 | 15.47 |
| 成功色 / 成功浅底 | 5.33 |
| 警告色 / 警告浅底 | 5.31 |
| 危险色 / 危险浅底 | 5.09 |

### ★ 换主色逼出来的一个语义问题：`--c-success-subtle` 被当成"浅底"用了 14 处 ★

改完主色之后全应用到处是淡绿块。根因不是配色，是**语义**：
`--c-success-subtle` 一直在兼任两个角色 ——
"真正的成功语义"和"随便一个浅色底"。旧主色是绿的，所以用淡绿当浅底看不出来；
主色一变近黑，这个借用立刻暴露。

按下面三条重新归属（`tmp/warm-fix.mjs`，17 条替换，每条断言恰好匹配 1 次，写出前断言花括号平衡）：

| 角色 | token | 落到哪些地方 |
|---|---|---|
| 选中 / 强调的浅底 | `--c-accent-subtle` | `.thread-item.active`、`.rail-session.active`、`.new-content-button`、`.dialog-icon`、`.bound-repository-mark` |
| 普通的次级浅底 | `--c-bg-subtle` | `.markdown-body code`、`.run-activity-toggle:hover`、`.run-activity-status`、`.quick-prompt:hover`、`.proposal-status`（待确认）、`.composer-interaction-hint` |
| 只留给真正的成功 | `--c-success-subtle` | `.status-pill.finished/.completed` 的**小圆点**、`.todo-icon`、`.repo-status.ready`、`.proposal-status-approved` |

**「已完成」状态胶囊本身改成中性**（底 `--c-bg-subtle`、字 `--c-text-secondary`），
只留那个小圆点是绿的：消息区里一屏能出现四五个「已完成」，全绿等于没有重点。

另外两处：`.model-picker-orbit` 的 `✳` 从 `--c-success` 改成 `--c-text-muted`（它是装饰，
不是状态）；`.thread-item` 给绝对定位的删除键多留了 4px（`--space-32 + --space-4` →
`--space-32 + --space-8`），原来视觉间距只有 1px。

---

## 21. 视觉改版第二步 · 面包屑 / 消息头时间 / 工具胶囊 / 消息列对齐（已完成）

### 面包屑

**改前的症状**：Header 副标题是 `` `${项目名} · ${repoFullName}` ``，而真实数据里
**项目名与仓库名经常完全相同**（项目基本就是按仓库建的），于是渲染出
`clumsyspc/test_coding_repo · clumsyspc/test_coding_repo` —— 同一句话写两遍。

**改法**：拆成两级面包屑 `[文件夹图标] <项目名> / <会话标题>`，仓库单独作为下面的徽标。

- `AgentWorkspace.vue` 拆出两个 computed：`crumb`（项目名 / `'普通聊天'` / `''`）
  与 `repoLabel`（仓库全名 / `'未连接仓库'` / `''`）。
- `WorkspaceHeader.vue` 新增 `crumb` prop，并新增
  `const showRepo = computed(() => !!props.repoLabel && props.repoLabel !== props.crumb)`
  —— **两者相同时整个隐掉徽标**。这不是边界情况，是常态。
- 两级分量必须不同：`crumb` 用 `--c-text-muted` / 550，标题用 `--c-text` / 650
  并升到 `--text-lg`（原来 13px，与输入态的 `--workspace-title-input` 不一致）。
- 项目名**不指向任何页面**（这个应用还没有"项目页"这个路由），所以它是标签不是链接。
- `AgentWorkspace.test.js` 的两条 `toContain('普通聊天 · 未连接仓库')` /
  `toContain('开发工作台 · example/app')` 改成**拆开断言两段文本** ——
  锁住"信息都在"，不锁中间用什么分隔符。

### 消息头时间

`ChatMessage.vue` 的助手/用户消息头加了 `<time class="message-time">`（`HH:MM`）。

**为什么是绝对时刻而不是相对时间**（"3 分钟前"）：相对时间需要一个每分钟重算的计时器，
而这个列表可能很长；而且它只在"刚刚"那一段比绝对时间好读，几小时、跨天之后反而更难对齐。
`hourCycle: 'h23'` 是为了避免 12 小时制在中文环境里出现"下午 2:32"这种比时间本身还长的标签。
`.message-time` 用最弱的灰 + 最轻的字重 —— 它是"扫读时可有可无、需要时能找到"的信息，
不能和名字抢重心。

### 工具胶囊

**改前的症状**：`.run-activity` 是一条**占满整行的卡片**（`--c-surface` 底 + 边框 +
1200px 宽）。于是"这次运行了 4 秒"这件事占了和一条消息一样大的版面 ——
**形态远大于信息量**。四个运行轨迹叠起来，消息区基本被空条占满。

**改法**：`.run-activity-toggle` 从 `display: flex; width: 100%` 改成
`display: inline-flex` + `border-radius: var(--radius-full)` —— **一个贴着内容的胶囊**。
展开的内容落到胶囊下面单独成块（`.run-activity-content { margin-top; border; radius-md }`），
所以圆角不会跟着撑开。

胶囊内部用 `::before { content: '·' }` 分节，**而不是给状态再套一个胶囊**：
嵌套胶囊会让一行出现三级圆角，读起来很碎。状态色只保留在失败/等待介入时（改成彩色文字，
不再是一整块彩色底）。图标从 18px 缩到 14px，字重从 700 降到 600。

### 消息列与输入框同宽同列

**改前的症状**：`.message-list` 的左右内边距是固定的 48px，而 `.composer` 是
`width: min(900px, calc(100% - 72px))` 居中。在 1440 宽下消息列从 385 开始、
输入框从 415 开始 —— **差 30px**。说不清哪里不对，但就是不正。
这是 `qa-checklist.md` 第 1 项「对齐栅格」的典型失败。

**改法**：两边都从 `--layout-content-max`（960px，之前定义了但**从来没人用**）反推：

```css
.composer      { width: min(var(--layout-content-max), calc(100% - 96px)); }
.message-list  { padding-inline: max(var(--space-48), calc((100% - var(--layout-content-max)) / 2)); }
```

两个公式在宽屏与窄屏下等价（消息列宽度 = `100% - 2 × max(48, (100% - 960) / 2)`
恰好等于 `min(960, 100% - 96)`），改 token 一处两边同时跟着走。
**顺带让 `--layout-content-max` 有了第一个真实消费者。**

### 验收（实跑）

- `npm test` → **8 files / 73 tests passed**（测试只改了 `AgentWorkspace.test.js` 的两条断言）
- `npm run audit` → 全部通过（规则块 530 → **535** · distinct 选择器 517 → **523** ·
  `var()` 1038 → **1051** · 覆盖率 99.6% / 硬编码色 0 / 硬编码 px **4** / 冗余声明 0 / `!important` 0）
- `npm run lint:css` → 0 errors / 19 warnings
- `npm run build` → ✓ 953ms
- `npm run shots` → 3/3，字节 **18287 / 28687 / 71528**（这一笔本来就是改视觉，与基线必然不同）
- `tmp/contrast.mjs` → 19/19 通过

### 存档

- `phase3-warm-states-920.png`（260927 B）—— 七格状态矩阵的暖色版，**与
  `phase3-states-920.png`（250463 B）是同一份夹具、同一份数据**，可以直接并排比对
- `phase3-warm-empty-1472.png`（50612 B）· `phase3-warm-breadcrumb-1472.png`（53733 B）
- `after-{375,768,1440}.png` 已刷新

### 仍未做的（用户明确说第三步不做）

侧栏导航段重构（项目/会话两层的分组与主次）· 悬浮提问卡 · 项目名与仓库名在侧栏里
仍然是同一串文字显示两遍（Header 修了，侧栏没修）。

---

## 22. 视觉改版第二步补完 · 相对时间 + 可折叠「深度思考」（已完成）

§21 遗漏了 objective 里明确列出的两项，这一节补齐。两项都不是调样式，
是**行为**，所以都配了单元测试。

### 相对时间（`ui/src/composables/useRelativeTime.js`，新增）

§21 做成了绝对时刻 `18:07`，理由是"相对时间要一个定时器"。**那个理由是错的** ——
它把"实现成本"当成了"设计取舍"。正确做法是解决那个成本：

- **模块级共享一个 `now` ref + 一个 30 秒 interval**（不是每条消息一个）。
  消费者按引用计数，最后一个卸载时停表。一屏 200 条消息仍然只有一个定时器。
- 30 秒而不是 1 秒：这个标签最细只显示到"分钟"，
  30 秒是"数字最多晚 30 秒跳变"与"几乎不耗电"之间的取舍。
  不做定时器的话，一个开着不管的标签页会让十分钟前的消息永远显示"刚刚"。

**粒度**：`刚刚` → `N 分钟前` → 超过一小时退回 `HH:MM` → 跨天加 `昨天`
→ 同年内 `M 月 D 日 HH:MM` → 跨年 `YYYY 年 M 月 D 日`。

为什么不一路相对下去：`3 天前` 这个粒度在看历史会话时是**有害的**。
用户想知道的是"这次对话发生在什么时候"，而"3 天前"不如"3 月 1 日 09:00"有用。
相对时间真正好用的窗口只有"刚刚"那一段。

**`title` 补回精确时刻**：相对时间的代价是丢掉准确值，悬停给出完整时间戳，
"扫读快"和"查得到"两件事就都成立了。

**★ 顺手抓到一个真 bug ★**：`new Date(null)` 不是 `Invalid Date`，是 `1970-01-01`。
原来的守卫只查了 `Number.isNaN`，所以**缺时间戳的消息会显示成「1970 年 1 月 1 日」**。
已显式挡掉 `null / undefined / ''`。测试里有一条专门盯它。

时钟漂移也处理了：后端比本机快几秒是常态，`diff` 为负时压成"刚刚"，
不显示"负 1 分钟前"。

### 可折叠「深度思考」（`RunActivityCard.vue`）

**改前的症状**：`timelineEvents` 的过滤条件是 `kind !== 'todo'`，所以
`kind === 'think'`（模型的推理）和 `kind === 'other'`（工具调用/步骤）
被混在**同一条平铺列表**里，视觉上完全没有区别 ——
而那恰恰是最长、最需要折叠的一类内容。

**改法**：把 `think` 从 `timelineEvents` 里拿掉，单独成一层次级折叠。

- `timelineEvents = events.filter(e => e.kind !== 'todo' && e.kind !== 'think')`
- `thinkEvents = events.filter(e => e.kind === 'think')`
- 默认收起（推理经常比整条运行轨迹还长），标题上直接给段数
  `深度思考 2 段` —— 不让人点开才知道有多少
- **不落盘持久化**：运行轨迹的展开状态要记住，因为它决定"这里有没有内容"；
  深度思考记不记无所谓，每次回到这条消息重新看一遍反而更符合预期

**为什么不挂在助手消息头下面**（objective 把它和"名字 + 时间"列在一起）：
`think` 事件属于某一次 run，而 run 的事件是**按需拉取**的
（只有展开运行轨迹时才 `loadRunActivity`）。挂到消息头意味着每条助手消息
一挂载就要为它所有的 run 各发一次请求。放在运行轨迹里面，数据在哪就长在哪。

**空态判定也要跟着改**：`!latestTodos.length && !timelineEvents.length && !thinkEvents.length`
—— 漏掉最后一项的话，一条"只有推理、没有工具调用"的运行会被说成"暂无可展示的执行过程"，
而它明明有内容。测试里有一条专门盯它。

**两个视觉决定**：
- **不用 `font-style: italic`**：中文没有真斜体，浏览器靠切变字形伪造，
  读起来是歪的。这一层的"旁白感"交给**浅底 + 左侧竖线**表达。
- **右边不给圆角**：`border-radius: 0 var(--radius-sm) var(--radius-sm) 0` 这种简写
  会被 audit 当成**一个新的取值**，直接把 `border-radius distinct` 从 4 顶到 5（上限 4）。
  这已经是同一个坑第二次踩（第一次是 `UiTextarea` 的 `border-radius: 0`）——
  `0` 也是取值。凡是简写里带 `0`，先想一下能不能干脆不要圆角。

### 夹具

`ui/preview/messages.js` 之前给 `runActivityEvents` 传的是 `{}`，
所以执行记录永远显示"暂无可展示的执行过程"，**深度思考这一层根本渲染不出来**。
已补上真实的 think / other 事件，并新增一格「深度思考展开」——
夹具里没有点击能力，靠挂载后一次 `setTimeout(0)` 点名 `click()` 补上。

### 验收（实跑）

- `npm test` → **9 files / 91 tests passed**（73 → 91：`useRelativeTime.test.js` 10 条 +
  `RunActivityCard.test.js` 8 条。**后者是新增的安全网** —— RunActivityCard 此前零测试，
  而"think 不能混进时间线"这条不变式一旦被破坏，界面看起来仍然正常，截图看不出来）
- `npm run audit` → 全部通过（规则块 535 → **547** · distinct 选择器 523 → **535** ·
  `var()` 1051 → **1076** · `border-radius distinct=4` · 覆盖率 99.6% / 硬编码色 0 / px 4）
- `npm run lint:css` → 0 errors / 19 warnings
- `npm run build` → ✓ 974ms
- `npm run shots` → 3/3，字节 18287 / 28687 / **72980**（1440 变大是因为消息头多了一段相对时间）

### 存档

- `phase3-warm-think-1000.png`（117068 B）—— 「深度思考」展开态的 2× 放大
- `phase3-warm-messages-1240.png`（404798 B）—— 消息块矩阵全量（16 格）
- `after-{375,768,1440}.png` 已刷新

### 这一节之后，objective 里剩下的

**没有了。** 第一步（暖色调 + 近黑主色 + 对比度校验）与第二步
（面包屑 / 名字 + 相对时间 + 可折叠深度思考 / 工具调用内联胶囊）全部落地并验收。
第三步（侧栏导航段重构、悬浮提问卡）按用户要求不做。





