# screenshot-and-qa.md — 截图与验收回路

> **本文回答**："AI 能否为我准备截图？skill 里怎么写清楚去哪里找截图、怎么截图？
> 有没有相应的 MCP 工具？"
>
> 答：**能，而且在当前环境下已经完全实测跑通，零额外依赖。**

---

## 1. 为什么截图是这套方法的核心

前面所有约束（token、lint、清单）都在防止"变烂"。
只有截图能让界面**变好** —— 因为它是唯一能让 AI 察觉自己在做什么的手段。

**没有截图的循环是这样的**：生成代码 → 看代码 → 觉得合理 → 交付。
问题：AI 看代码时看到的是 `padding: var(--space-12)`，而用户看到的是
"这个按钮和旁边那个没对齐"。**代码里没有"对齐"这个信息。**

**有截图的循环**：生成代码 → 截图 → **看图** → 挑出具体问题 → 修 → 再截图。
只有这条回路能闭合"做 → 看 → 改"。

> 用户的项目里 Hero 区那行 `独立会话仓库上下文模型代号`，
> 写代码时看起来完全正常（一行文字嘛），截图看才会发现它是信息架构事故。
> 这类问题**只能通过看图发现**。

---

## 2. 实测可用的截图方案（无依赖）

当前环境已实测：

- Chrome：`C:\Program Files\Google\Chrome\Application\chrome.exe`
- Edge（备用）：`C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`
- 实测命令：

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --headless=new --disable-gpu --hide-scrollbars --no-sandbox `
  --window-size=800,300 `
  --screenshot="A:\path\out.png" `
  "file:///A:/path/page.html"
```

**实测结果：675ms 产出 13557 字节 PNG（800x300），图像内容可读。**
不需要 playwright、不需要 puppeteer、不需要任何 MCP。

### 关键参数

| 参数 | 作用 | 备注 |
|---|---|---|
| `--headless=new` | 新版无头模式 | 旧的 `--headless` 渲染差异较大，别用 |
| `--screenshot=<path>` | 输出路径 | 必须是绝对路径或从 cwd 解析 |
| `--window-size=W,H` | 视口尺寸 | **无头模式只截视口，不截整页** |
| `--hide-scrollbars` | 隐藏滚动条 | 否则右侧多一条，干扰判断 |
| `--virtual-time-budget=5000` | 等待 JS 渲染 | **SPA 必加**，否则截到白屏 |
| `--force-device-scale-factor=2` | 2x 高清 | 需要看清 1px 细节时用 |
| `--default-background-color=FFFFFFFF` | 强制白底 | 默认透明底，PNG 里会变黑 |

### 已知限制

- **只截视口**：长页面需要 `--window-size=1280,4000` 这种超高视口，
  或者分页截。
- **需要交互才出现的状态**（hover、展开的菜单、对话框）截不到 ——
  除非做成静态 HTML fixture。见下面第 4 节。
- **需要登录/真后端的页面**截不到 —— 除非用 mock。

---

## 3. `capture.mjs` 用法

（脚本由阶段一生成，放在 `scripts/capture.mjs`）

**语法：`node capture.mjs <url> <outDir> [选项]`** —— 输出目录是**位置参数**，不是 `--out`。

```bash
# 基础：默认三个宽度 375 / 768 / 1440
node scripts/capture.mjs http://localhost:5173 shots

# 指定宽度
node scripts/capture.mjs http://localhost:5173 shots --widths 375,1280

# 本地静态文件（不需要起服务）
node scripts/capture.mjs ./page.html shots --widths 1440

# 自定义文件名前缀 → shots/home-375.png, shots/home-1280.png
node scripts/capture.mjs http://localhost:5173 shots --widths 375,1280 --name home

# 高清，用于看 1px 级细节
node scripts/capture.mjs http://localhost:5173 shots --scale 2

# 等待 SPA 渲染（虚拟时间预算，毫秒）
node scripts/capture.mjs http://localhost:5173 shots --budget 5000

# 指定浏览器
node scripts/capture.mjs http://localhost:5173 shots --chrome "D:\Chrome\chrome.exe"
```

输出文件名为 `<name>-<width>.png`，默认前缀 `shot`。
退出码 `0` = 全部成功；`1` = 参数错误 / 未找到浏览器 / 任一张失败。

### 脚本必须遵守的两条工程约束

1. **用 `spawnSync(..., { stdio: 'ignore' })`，不要捕获子进程输出。**
   在受限沙箱（如本环境）下，管道会抛 `EPERM`。改为
   **检查输出文件是否存在且非空**来判断成功，而不是读 stdout。
2. **自动探测浏览器**：按 `CHROME_PATH` 环境变量 → Chrome 默认路径 →
   Edge 默认路径 的顺序找。找不到就报清晰的错误，不要静默失败。

---

## 4. 截不到的时候怎么办（降级策略）

按优先级：

1. **起本地 dev server**（Vite/Next 都有一条命令），用 `http://localhost:5173`。
   **这是最好的方式**，因为渲染的是真实组件。
2. **静态 HTML fixture**：把组件的关键状态手写成一个独立 HTML 文件，
   直接 `file://` 截图。适合截 hover / 展开 / 错误态 ——
   因为这些在真实页面里难以复现。**这是最被低估的技巧**：
   做一个 `fixtures/states.html` 把所有状态平铺出来，一次截完。
3. **mock 数据 + 强制状态**：在开发模式下加 URL 参数
   （`?state=empty` / `?state=error` / `?state=loading`），
   让页面能强制进入各个状态。然后批量截图。
4. **人工截图**：确实需要登录/复杂交互时，让用户截，然后 AI 用
   `read_image` 读。**这是完全合法的路径** —— 不要因为不能自动截就跳过验收。

> ⚠️ 无论用哪种方式，**AI 必须真的读那张图再评论**。
> 声称"我看到界面很整洁"但没有调用读图工具，是编造。
> 这一点要写进 skill 的行为约束里。

---

## 5. 验收回路的四步

```
截图 → 看图挑刺 → 改 → 再截图
 ↑___________________________|
```

### 第 1 步：截图
用 `capture.mjs`，至少覆盖：正常态、空态、错误态、375px、1280px。

### 第 2 步：挑刺（关键步骤，不能跳）

对照 `qa-checklist.md`，**按顺序**过 8 组。
必须输出**具体**的问题，不是印象：

| ❌ 无效反馈 | ✅ 有效反馈 |
|---|---|
| "看起来不够精致" | "工具栏三个控件高度分别是 28/36/32px，不齐" |
| "颜色有点乱" | "同行出现 #1f7667 和亮青 #2ec4b6 两个绿" |
| "间距不太对" | "卡片间距 16px，但卡片内 padding 24px，比例反了" |
| "有点空" | "空态只有一行灰字，没有引导操作" |

**判断标准**：这条反馈能不能直接翻译成一行 CSS 改动？
不能就是无效反馈，重写。

### 第 3 步：改
**一次只改一个维度。** 同时改对齐+颜色+间距，出问题时无法归因。

### 第 4 步：再截图
**必须重新截图。** 改完不截图 = 没改完。
（这一条要写死，因为跳过它的诱惑最大。）

---

## 6. 独立审查者：一个被低估的技巧

让**生成界面的那个 agent 去审自己**，效果有限 —— 它会倾向于认为
自己写的是对的（同一份上下文里的自我一致性偏差）。

更有效的做法：**开一个全新的 subagent，只给它截图和 qa-checklist，
不告诉它是谁写的**，让它独立挑刺。

```
任务：这是一张界面截图（附路径）。请对照 docs/design/qa-checklist.md
逐条检查，列出所有不合格项。不要评价优点，只找问题。
对每一条给出：问题位置（哪个元素）、具体数值差距、建议改法。
```

**为什么有效**：它的上下文里没有"我刚才这么写是有道理的"这笔账。
它只看图。

成本很低（一次 subagent 调用），但抓到的对齐/一致性问题的数量
通常显著高于自审。

---

## 7. 有没有现成的 MCP 可以用

当前 DSH 会话**没有**注册任何浏览器/截图类 MCP。已调研的同类方案：

| 方案 | 能做什么 | 代价 |
|---|---|---|
| [Playwright MCP](https://apify.com/nexgendata/playwright-mcp-server#1) | 真实浏览器交互、可点击后截图、可读 DOM/无障碍树 | 需要装 playwright + 配 MCP |
| [chrome-devtools-mcp](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/136da6a3/docs/cli.md?plain=1#L75-L79#1) | 直连 Chrome DevTools 协议，性能追踪 + 截图 | 需要 Node + Chrome |
| [Playwright 视觉测试实践](https://argos-ci.com/blog/playwright-mcp-visual-testing) | 截图快照基线对比（回归检测） | 适合已有稳定 UI 的项目 |

**建议**：
- **现在就用零依赖的 `capture.mjs`** —— 它已经实测跑通，覆盖 90% 需求。
- 需要**交互后截图**（点开菜单再截）或**读 DOM 结构**时，再上
  Playwright MCP。它比 `capture.mjs` 强的地方就是"能操作"。
- 视觉回归（防止改 A 页面弄坏 B 页面）是另一个问题，
  属于 CI 范畴，等界面稳定了再上。

> 不要因为"有更好的工具"而推迟截图。`capture.mjs` 今天就能用，
> 而"等配好 Playwright 再开始验收"通常意味着永远不开始。
