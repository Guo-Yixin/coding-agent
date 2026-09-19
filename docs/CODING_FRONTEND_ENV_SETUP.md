# CODING 前端运行环境安装说明

本文只说明前端环境。Python 虚拟环境、后端依赖、`.env`、Gitee Token、SQLite 数据库等后端内容不在本文展开。

## 1. 当前前端项目是什么

当前 CODING 前端是一个 **Vue 3 + JavaScript + Vite** 项目。

前端目录：

```text
B:\my_project\CODING\ui
```

核心文件：

| 文件 | 作用 |
|---|---|
| `ui/package.json` | 前端依赖和启动脚本 |
| `ui/yarn.lock` | 锁定依赖版本，保证换目录后安装结果一致 |
| `ui/vite.config.js` | Vite 配置 |
| `ui/index.html` | Vite 入口 HTML |
| `ui/src` | Vue + JavaScript 源码 |

当前前端不使用 TypeScript，因此不需要安装 `typescript`、`vue-tsc` 或 `@types/*`。

## 2. 为什么还需要 Vite

不用 TypeScript 不等于可以直接用 `node src/main.js` 启动前端。

原因是前端代码不是普通 Node 后端脚本。前端会使用：

```js
import { createApp } from "vue"
import App from "./App.vue"
import "./styles/main.css"
```

Node 不能直接处理：

| 内容 | 是否能被 Node 直接运行 |
|---|---|
| `.js` 普通脚本 | 可以 |
| `.vue` 单文件组件 | 不可以 |
| CSS import | 不可以 |
| 浏览器 DOM 代码 | 不适合直接在 Node 中执行 |
| Vite 热更新 | 需要 Vite |

所以前端开发时仍然需要 Vite。Vite 负责：

- 解析 `.vue` 文件；
- 处理 CSS；
- 解析 npm 依赖；
- 启动本地开发服务器；
- 支持浏览器热更新；
- 注入 `VITE_DASHBOARD_API_BASE_URL` 等前端环境变量。

## 3. 复制项目后的目录要求

假设你把项目复制到新目录，例如：

```text
B:\my_project\CODING_New
```

复制后应该确认目录结构类似：

```text
B:\my_project\CODING_New
├─ agent
├─ docs
├─ scripts
├─ ui
│  ├─ package.json
│  ├─ yarn.lock
│  ├─ vite.config.js
│  ├─ index.html
│  └─ src
└─ ...
```

注意：`node_modules` 可以不复制。推荐在新目录重新安装依赖。

## 4. 安装 Node.js

前端依赖 Node.js。建议使用 Node.js LTS 版本。

检查当前机器是否已经安装：

```powershell
node -v
npm -v
```

能看到版本号就说明 Node.js 已安装，例如：

```text
v20.x.x
10.x.x
```

如果没有安装，可以安装 Node.js LTS。安装完成后重新打开 PowerShell 或 PyCharm。

## 5. 启用 Corepack

当前项目使用 `yarn.lock` 锁定依赖。建议通过 Corepack 使用 Yarn。

在项目根目录执行：

```powershell
corepack enable
```

然后检查 Yarn 是否可用：

```powershell
corepack yarn -v
```

如果能输出版本号，说明 Yarn 可用。

## 6. 安装前端依赖

进入前端目录：

```powershell
cd B:\my_project\CODING_New\ui
```

安装依赖：

```powershell
corepack yarn install
```

安装成功后，`ui` 目录下会出现：

```text
node_modules
```

当前前端需要的依赖来自 `ui/package.json`：

| 依赖 | 作用 |
|---|---|
| `vue` | Vue 3 前端框架 |
| `vite` | 前端开发服务器和构建工具 |
| `@vitejs/plugin-vue` | 让 Vite 支持 `.vue` 文件 |
| `pinia` | 前端状态管理 |
| `axios` | HTTP 请求 |
| `markdown-it` | Markdown 渲染 |
| `dompurify` | HTML 内容安全清洗 |

当前没有 TypeScript 依赖。

## 7. 单独启动前端验证

如果只想验证前端能不能启动，可以在 `ui` 目录执行：

```powershell
corepack yarn dev
```

项目里的 `package.json` 已经定义了：

```json
{
  "scripts": {
    "dev": "vite --host 127.0.0.1 --port 3000"
  }
}
```

所以 `corepack yarn dev` 等价于启动：

```powershell
vite --host 127.0.0.1 --port 3000
```

浏览器访问：

```text
http://127.0.0.1:3000
```

如果后端没有启动，页面可以打开，但调用接口时会失败。这属于正常现象。

## 8. 前端如何找到后端

前端通过环境变量找到 FastAPI 后端：

```text
VITE_DASHBOARD_API_BASE_URL=http://127.0.0.1:2024
```

当前 `scripts/start_all.py` 在启动前端时会注入这个环境变量：

```python
env={"VITE_DASHBOARD_API_BASE_URL": "http://127.0.0.1:2024"}
```

所以只要用 `scripts/start_all.py` 启动，前端会自动请求：

```text
http://127.0.0.1:2024
```

## 9. 使用 start_all.py 同时启动前后端

前提：

- Python 后端环境已经装好；
- 前端已经在 `ui` 目录执行过 `corepack yarn install`；
- `ui\node_modules` 存在；
- 端口 `2024` 和 `3000` 没有被其他程序占用。

在项目根目录执行：

```powershell
B:\my_project\CODING_New\.venv\Scripts\python.exe scripts\start_all.py
```

或者在 PyCharm 中右键运行：

```text
scripts/start_all.py
```

启动后会同时拉起：

| 服务 | 地址 | 说明 |
|---|---|---|
| FastAPI 后端 | `http://127.0.0.1:2024` | Agent API 和 SSE |
| Vite 前端 | `http://127.0.0.1:3000` | Vue 页面 |

当前 `start_all.py` 中前端启动命令是：

```python
["node", ".\\node_modules\\vite\\bin\\vite.js", "dev", "--host", "127.0.0.1", "--port", "3000"]
```

它本质上就是用 Node 启动本地安装的 Vite。只要 `ui\node_modules` 存在，这个命令就能运行。

## 10. 推荐的前端启动方式

虽然当前命令可以运行，但开发时更推荐讲成：

```powershell
corepack yarn dev
```

原因：

- 开发者更容易理解；
- 不需要记住 `node_modules\vite\bin\vite.js` 这种内部路径；
- 和 `package.json` 的脚本保持一致；
- 后续如果 Vite 启动参数调整，只改 `package.json` 即可。

如果后续要优化 `scripts/start_all.py`，可以把前端启动命令改为：

```python
["corepack", "yarn", "dev"]
```

工作目录仍然必须是：

```python
PROJECT_ROOT / "ui"
```

## 11. 复制项目后最小操作清单

假设新项目目录是：

```text
B:\my_project\CODING_New
```

前端只需要执行：

```powershell
cd B:\my_project\CODING_New
corepack enable
cd ui
corepack yarn install
corepack yarn dev
```

确认前端能启动后，再回到项目根目录，通过后端脚本统一启动：

```powershell
cd B:\my_project\CODING_New
.\.venv\Scripts\python.exe scripts\start_all.py
```

## 12. 常见问题

### 12.1 `node` 不是内部或外部命令

说明 Node.js 没安装，或者安装后没有重新打开终端。

处理：

```powershell
node -v
```

如果仍然找不到，重新安装 Node.js LTS。

### 12.2 `corepack` 不是内部或外部命令

说明 Node.js 版本太旧，或者 Node.js 安装不完整。

处理：

- 优先升级 Node.js LTS；
- 或临时使用 npm 安装依赖：

```powershell
cd ui
npm install
npm run dev
```

但项目中建议统一使用 `corepack yarn install`，因为项目有 `yarn.lock`。

### 12.3 启动时报 `Cannot find module vite`

说明没有安装前端依赖，或者不在 `ui` 目录安装。

处理：

```powershell
cd B:\my_project\CODING_New\ui
corepack yarn install
```

### 12.4 端口 3000 被占用

说明已有前端服务正在运行。

处理：

- 先停止旧服务；
- 或运行项目里的停止脚本；
- 或临时改 `package.json` / `start_all.py` 中的端口。

### 12.5 页面能打开，但接口请求失败

通常是后端没有启动，或者后端端口不是 `2024`。

检查后端健康接口：

```text
http://127.0.0.1:2024/health
```

如果后端端口改了，也要同步调整：

```text
VITE_DASHBOARD_API_BASE_URL
```

### 12.6 可以删除 node_modules 后重新安装吗

可以。`node_modules` 是安装产物，不是源码。

如果依赖异常，可以删除：

```text
ui\node_modules
```

然后重新执行：

```powershell
cd ui
corepack yarn install
```

## 13. 结论

复制项目到新目录后，前端能否运行主要取决于三件事：

1. 机器上安装了 Node.js；
2. 在 `ui` 目录执行过 `corepack yarn install`；
3. `start_all.py` 启动前端时工作目录是 `ui`，并且端口 `3000` 可用。

当前项目不用 TypeScript，但仍然需要 Vite，因为 Vite 负责 Vue 单文件组件、浏览器模块、CSS 和开发服务器。
