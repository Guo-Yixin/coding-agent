# 反模式清单（本项目版）

> 每一条都锚定 `main.css` 里**真实存在的**违规，数字来自 `baseline/audit-before.json`。
> 通用版 22 条在 skill 的 `templates/anti-patterns.md`；这里是**这个项目**的负面清单。

---

## AP-01 新增第二个 `:root` 块 🔴

**现状**：`main.css` 有 **3 个** `:root` 块（约 `:3`、`:561`、`:1117`），互相静默覆盖。

```css
:root { --accent-strong: #245f59; }   /* 死代码 */
:root { --accent-strong: #1f7667; }   /* 生效 */
```

**为什么坏**：读代码时你看到的是第一个，浏览器用的是最后一个。**同一语义出现两种颜色**，且没有任何提示。
**正确做法**：全项目只有一个 `:root`，在 `tokens.css`。
**机器可查**：`audit-css.mjs` → `:root 块 = 1`

---

## AP-02 硬编码颜色 🔴

**现状**：`var()` 只出现 **31 次**，而硬编码颜色字面量 **488 处**、硬编码 px **539 处** → **token 覆盖率 2.9%**。

**为什么坏**：token 写在 `:root` 里但没人用，等于没有。改主色要动 488 个地方。
**正确做法**：所有颜色/字号/间距/圆角引用 `var(--…)`。
**机器可查**：`audit-css.mjs` → `token 覆盖率 ≥ 90%`；stylelint → `declaration-property-value-disallowed-list`

---

## AP-03 「再微调一下」的追加覆盖块 🔴

**现状**：文件里有 6 段追加式注释，就是迭代史本身：

```
/* Composer refinement: context, task input, and explicit actions. */
/* Codex-inspired neutral workspace and compact composer. */
/* Session header: show conversation context instead of repeating the product brand. */
/* Collapsed sidebar: a clean icon rail without truncated session titles. */
/* Editable session title and explicit branch context. */
/* Refined workspace navigation and conversation composer. */
```

**503 个规则块只覆盖 408 个选择器 → 108 个选择器被重复声明**，靠「后写覆盖先写」生效。重复最多：`.composer-footer` ×4。

**为什么坏**：每次迭代不是**修改**而是**追加并覆盖**。文件只增不减，同一个选择器散落在多个位置，改一处不敢删另一处。
**正确做法**：修改已有规则，不新建同名覆盖块。
**机器可查**：`audit-css.mjs` → `重复声明选择器 = 0`；stylelint → `no-duplicate-selectors`

---

## AP-04 近似色爆炸 🟠

**现状**：**294 种 hex / 457 次**，聚类出 **17 组近重复**：

| 聚类 | 颜色数 | 例子 |
|---|---|---|
| 近白 | **105** | `#f4f5f3` `#edf4f2` `#f7f8f6` `#e8edeb` … |
| 灰 | 83 | `#9aa39f` `#a0aaa5` `#a0a4aa` `#738079` … |
| 蓝 | 27 | Tailwind 的 `#94a3b8` `#64748b` 混着自定义灰 |
| 青 | 10 | `#356b63` `#2f6d64` `#286f5f` `#347b67` `#246b5d` `#1f7667` |
| 红 | 10 | — |

**为什么坏**：105 个「差不多的白」在屏幕上不是 105 个颜色，而是**一片浑浊**。眼睛找不到节奏。
**正确做法**：近白只留 3 档（`--c-bg` / `--c-bg-subtle` / `--c-surface`），绿只留 1 个主色族。
**机器可查**：`audit-css.mjs` → `彩色 distinct ≤ 5`、`近白背景 ≤ 3`

---

## AP-05 `rgb(...)` 与 `rgba(...)` 各造一套基色 🟠

**现状**：24 种 rgba，**19 种不同基色**。其中包括同一深绿的两个不同写法：

```css
rgb(27 40 34 / 13%)     /* 这一轮发明的 */
rgb(31 45 39 / 13%)     /* 下一轮又发明了一个 */
```

**为什么坏**：这是「每一轮重新发明值」最赤裸的证据——连同一个颜色都懒得复用。
**正确做法**：阴影/边框基色统一为 `rgba(20, 28, 25, ·)`，只调透明度。
**机器可查**：`audit-css.mjs` → `rgb/rgba 基色 distinct ≤ 3`

---

## AP-06 圆角与字号失控 🟠

**现状**：
- **20 种圆角**：4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,22,999,50%,0，还有 `16px 16px 4px 16px`
- **19 种字号**，且**分布倒挂**：`12px`×32 次、`11px`×23、`10px`×20、`13px`×14 …… 还有 `10.5px`、`8px`、`9px`

**为什么坏**：2px 的圆角差肉眼分不出，但会让边界看起来**发毛**。10.5px 这种值说明是「看着调」而不是「选一个数」。
**正确做法**：圆角 4 档（6/10/16/999），字号 7 档（11/12/13/15/18/24/32）。
**机器可查**：`audit-css.mjs` → `border-radius ≤ 4`、`font-size ≤ 7`

---

## AP-07 断点漂移 🟡

**现状**：**4 种宽度**（560 / 600 / 720 / 860），11 个 `@media` 块。其中 `600px` 只出现 **1 次**——明显是随手写的。

**为什么坏**：5px 的断点差意味着两套规则在 590px 屏幕上同时命中，行为不可预测。
**正确做法**：只用 860 / 720 / 560 三个（见 `DESIGN.md` 第 4 节）。
**机器可查**：`audit-css.mjs`（待补断点项）

---

## AP-08 组件内私有 `<style>` 泄漏第四种配色 🟡

**现状**：`.vue` 的 `<style>` 块基本为空，只有 `ActiveTaskStrip.vue` 有 938 字符，里面出现：

```css
#6366f1   /* Tailwind indigo-500 */
#e5e7eb   /* Tailwind gray-200 */
```

**为什么坏**：主样式在 `main.css` 用自定义绿，组件里偷偷用了 Tailwind 的靛蓝——**没人会发现，直到它出现在屏幕上**。
**正确做法**：组件内只能用 token；跨组件的样式放在 `main.css`。
**机器可查**：stylelint 扫 `**/*.vue`

---

## AP-09 `!important` 🟡

**现状**：2 处。

**为什么坏**：它是「我不知道为什么这条规则不生效」的投降声明。有了第一个就有第二个。
**正确做法**：查清优先级冲突的根因，通常是 AP-03（选择器被重复声明）。
**机器可查**：stylelint → `declaration-no-important`

---

## AP-10 把控件状态当正文写 🔴

**现状**：Hero 里那行（见 `baseline/before-1440.png`）：

```
独立会话仓库上下文deepseek-flash
```

**为什么坏**：三层问题——
1. **信息架构错**：模型名是**控件状态**，不是文案；而且 composer 里已经有一个模型下拉在显示同样的值
2. **缺失分隔**：`上下文` `deepseek-flash` 直接粘在一起，像是渲染 bug
3. **层级错**：它是三行里唯一没有视觉角色的元素

**正确做法**：控件状态留在控件里。Hero 只留 mark / eyebrow / h1 / desc 四层。
**机器可查**：截图人工核对（见 `qa-checklist.md`）

---

## AP-11 「顺便优化」🟡

**现状**：这是 `main.css` 涨到 1313 行的**机制**——每一轮 AI 迭代都顺手改了没被要求的东西，于是产生了 AP-03 的追加覆盖块。

**为什么坏**：它让「这次改了什么」不可知，也让回滚不可能。
**正确做法**：提示词里明确写「发现其他问题请单独列出，**不要顺手改**」。
**机器可查**：`git diff` 范围是否超出要求

---

## AP-12 在页面里写裸控件 🟡

**现状**：目前 `<button>` / `<input>` 直接写在业务组件里，各自带样式。

**为什么坏**：同一个「按钮」在 composer、侧栏、弹窗里有三套实现和三套 hover 行为。
**正确做法**：用 `DESIGN.md` 第 5 节的白名单组件。
**机器可查**：阶段三加 lint 规则
