# CODING Linux 服务器安装与运行手册

本文档用于把 CODING 部署到 Linux 服务器，例如 Alibaba Cloud Linux。重点覆盖实际运行所需的 Git、Node.js、Python/Conda、前端依赖、后端依赖、`.env`、工作区目录、启动命令和常见错误。

特别注意：当前项目代码按 `deepagents==0.6.11` 编写。不要安装 `deepagents 0.7+`，否则会出现 backend factory 和 permissions 兼容错误。

## 1. 推荐目录结构

服务器上推荐统一使用：

```bash
/opt/coding
  app/                      # 项目代码
  data/                     # SQLite 数据库
  logs/                     # 后端日志和 Agent 日志
  workspace/                # Agent 工作区
    projects/               # Gitee 仓库克隆目录
    skills/                 # DeepAgents skills
    policies/               # 规则文件
    reviews/                # 代码审查结果
    tmp/                    # 临时文件
    logs/                   # 工作区日志
    runtimes/               # 共享运行环境
```

创建目录：

```bash
sudo mkdir -p /opt/coding/{app,data,logs,workspace}
sudo mkdir -p /opt/coding/workspace/{projects,skills,policies,reviews,tmp,logs,runtimes}
sudo chown -R $USER:$USER /opt/coding
```

如果使用 `root` 运行服务，可以不执行 `chown`，但生产环境更建议使用独立普通用户。

## 2. 安装 Git

Agent 需要执行 `git clone`、`git fetch`、`git status`、`git commit`、`git push`。

Alibaba Cloud Linux 通常执行：

```bash
sudo yum install -y git
git --version
```

如果系统使用 `dnf`：

```bash
sudo dnf install -y git
git --version
```

配置 Git 提交身份：

```bash
git config --global user.name "CODING"
git config --global user.email "coding@example.com"
git config --global --list
```

## 3. 安装 Node.js 22

前端是 Vue + Vite，需要 Node.js。Alibaba Cloud Linux 可以优先使用系统源安装；如果默认安装出来就是 Node.js 22，就不需要额外接入 NodeSource。

```bash
sudo dnf install -y nodejs npm
node -v
npm -v
```

确认版本类似：

```text
v22.x.x
```

如果你的系统源安装出来不是 Node.js 22，或者版本过低，再使用 NodeSource 方式：

```bash
curl -fsSL https://rpm.nodesource.com/setup_22.x | sudo bash -
sudo dnf install -y nodejs
node -v
npm -v
```

建议配置 npm 镜像：

```bash
npm config set registry https://registry.npmmirror.com
```

## 4. 准备 Python Conda 环境

如果服务器已经安装 Conda，推荐直接创建独立环境：

```bash
conda create -n aicoding python=3.14 -y
conda activate aicoding
python -V
pip -V
```

如果 Python 3.14 暂时不可用，可以先使用 Python 3.12，但项目当前 `pyproject.toml` 声明的是 `>=3.14`，项目环境推荐保持 3.14。

升级 pip，并使用阿里云 PyPI 镜像：

```bash
python -m pip install --upgrade pip setuptools wheel \
  -i https://mirrors.aliyun.com/pypi/simple/ \
  --trusted-host mirrors.aliyun.com
```

也可以把阿里云镜像设置为默认源：

```bash
pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/
pip config set global.trusted-host mirrors.aliyun.com
```

## 5. 上传项目代码

推荐把本地项目上传到：

```bash
/opt/coding/app
```

上传后确认目录：

```bash
ls -lah /opt/coding/app
```

应该能看到：

```bash
agent
ui
scripts
pyproject.toml
README.md
```

不要上传这些目录：

```bash
ui/node_modules
ui/dist
.venv
__pycache__
data
logs
```

这些内容应该在 Linux 服务器上重新生成。

## 6. 配置 .env

进入项目目录：

```bash
cd /opt/coding/app
```

创建或修改 `.env`：

```bash
vim .env
```

推荐配置：

```env
AI_WORKSPACE_ROOT=/opt/coding/workspace
CODING_DATA_DIR=/opt/coding/data
CODING_LOG_DIR=/opt/coding/logs

CHECKPOINT_DB_PATH=/opt/coding/data/checkpoints.sqlite
STORE_DB_PATH=/opt/coding/data/store.sqlite
LANGGRAPH_STORE_DB_PATH=/opt/coding/data/langgraph_store.sqlite

GITEE_TOKEN=你的GiteeToken
SCM_GITEE_TOKEN=你的GiteeToken
```

如果还有模型相关配置，也放在 `.env` 中，例如 DeepSeek/OpenAI 兼容接口的 Key、Base URL、模型名等。

检查 `.env` 是否残留 Windows 路径：

```bash
grep -n "E:\\|C:\\|my_project" .env
```

如果有输出，必须改掉。Linux 服务器上不能保留：

```text
B:\my_project\CODING
B:\ai_workspace
C:\
```

如果 `.env` 是从 Windows 复制过来的，建议清理 BOM 和 CRLF：

```bash
sed -i '1s/^\xEF\xBB\xBF//' .env
sed -i 's/\r$//' .env
```

## 7. 安装后端依赖

进入项目目录并激活 Conda：

```bash
cd /opt/coding/app
conda activate aicoding
```

必须固定 `deepagents==0.6.11`：

```bash
pip uninstall -y deepagents
pip install "deepagents==0.6.11" \
  -i https://mirrors.aliyun.com/pypi/simple/ \
  --trusted-host mirrors.aliyun.com
```

安装其他依赖：

```bash
pip install \
  "fastapi>=0.138.0" \
  "uvicorn>=0.49.0" \
  "langchain-openai>=1.3.2" \
  "langgraph-checkpoint-sqlite>=3.1.0" \
  "python-dotenv>=1.2.2" \
  "requests>=2.32.0" \
  "zhipuai>=2.1.5" \
  -i https://mirrors.aliyun.com/pypi/simple/ \
  --trusted-host mirrors.aliyun.com
```

也可以执行：

```bash
pip install -e . \
  -i https://mirrors.aliyun.com/pypi/simple/ \
  --trusted-host mirrors.aliyun.com
```

但是当前 `pyproject.toml` 如果仍然写 `deepagents>=0.6.11`，可能会安装到 `0.7+`。因此更稳妥的方式是先手动安装：

```bash
pip install "deepagents==0.6.11" \
  -i https://mirrors.aliyun.com/pypi/simple/ \
  --trusted-host mirrors.aliyun.com
```

再确认版本：

```bash
pip show deepagents
```

必须看到：

```text
Version: 0.6.11
```

验证关键依赖：

```bash
python -c "import fastapi, uvicorn, deepagents, langgraph; print('ok')"
```

## 8. 同步 Skills

项目内 skill 需要同步到工作区：

```bash
cd /opt/coding/app
python scripts/sync_skills.py
```

确认：

```bash
ls -lah /opt/coding/workspace/skills
```

应该能看到：

```bash
ai-coding-implementation
code-review
repo-bootstrap-analysis
```

## 9. 安装前端依赖

进入前端目录：

```bash
cd /opt/coding/app/ui
```

不要复用 Windows 上传过来的 `node_modules`，必须在 Linux 上重新安装：

```bash
rm -rf node_modules package-lock.json
npm config set registry https://registry.npmmirror.com
npm install
```

如果报 Rollup Linux 原生依赖缺失，例如：

```text
Cannot find module @rollup/rollup-linux-x64-gnu
```

说明 `node_modules` 是 Windows 环境残留，执行：

```bash
rm -rf node_modules package-lock.json .vite
npm install
```

开发方式启动：

```bash
cd /opt/coding/app
bash scripts/start_ui.sh
```

生产部署建议构建：

```bash
cd /opt/coding/app/ui
npm run build
```

然后用 Nginx 托管 `ui/dist`。

## 10. 部署自检

执行：

```bash
cd /opt/coding/app
conda activate aicoding
python scripts/verify_linux_deployment.py
```

它会检查：

```text
workspace 目录是否可写
data 目录是否可写
logs 目录是否可写
git 是否可用
python 是否可用
node 是否可用
FastAPI / Uvicorn / DeepAgents / LangGraph 是否可导入
LocalShellBackend 是否健康
虚拟路径 /tmp 是否可读写
backend 是否能执行 git --version
```

如果检查失败，优先看：

```bash
AI_WORKSPACE_ROOT
CODING_DATA_DIR
CODING_LOG_DIR
deepagents 版本
目录权限
```

## 11. 启动后端

方式一：使用脚本：

```bash
cd /opt/coding/app
conda activate aicoding
bash scripts/start_backend.sh
```

方式二：直接启动：

```bash
cd /opt/coding/app
conda activate aicoding
uvicorn agent.app:app --host 0.0.0.0 --port 2024
```

健康检查：

```bash
curl http://127.0.0.1:2024/health
```

如果公网访问，需要阿里云安全组放行 `2024`。

## 12. 启动前端

开发方式：

```bash
cd /opt/coding/app
bash scripts/start_ui.sh
```

Vite 输出类似：

```text
Local:   http://localhost:3000/
Network: http://10.0.0.xxx:3000/
```

公网访问使用服务器公网 IP，例如：

```text
http://47.92.66.118:3000
```

需要阿里云安全组放行：

```text
TCP 3000
TCP 2024
```

如果后续使用 Nginx，推荐只暴露 `80/443`，不要直接暴露 `3000/2024`。

## 13. 常见错误

### 13.1 .env: line 1: #: command not found

原因通常是 `.env` 有 UTF-8 BOM 或 Windows 换行符。

修复：

```bash
cd /opt/coding/app
sed -i '1s/^\xEF\xBB\xBF//' .env
sed -i 's/\r$//' .env
```

### 13.2 日志路径仍指向历史 Windows 目录

错误示例：

```text
No such file or directory: '/opt/coding/logs/agent-runs.log'
```

原因：Linux `.env` 中残留 Windows 路径。

修复：

```bash
grep -n "E:\\|C:\\|my_project" .env
```

把这些路径全部改成：

```env
CODING_LOG_DIR=/opt/coding/logs
CODING_DATA_DIR=/opt/coding/data
AI_WORKSPACE_ROOT=/opt/coding/workspace
```

### 13.3 Cannot find module @rollup/rollup-linux-x64-gnu

原因：上传了 Windows 的 `ui/node_modules`。

修复：

```bash
cd /opt/coding/app/ui
rm -rf node_modules package-lock.json .vite
npm install
```

### 13.4 Backend factories were removed in deepagents 0.7

原因：安装了 `deepagents 0.7+`。

当前项目必须使用：

```bash
pip uninstall -y deepagents
pip install "deepagents==0.6.11" \
  -i https://mirrors.aliyun.com/pypi/simple/ \
  --trusted-host mirrors.aliyun.com
```

验证：

```bash
pip show deepagents
```

必须是：

```text
Version: 0.6.11
```

### 13.5 FilesystemMiddleware does not yet support permissions

原因同样通常是安装了 `deepagents 0.7+`。当前项目代码保留了 `FilesystemPermission` 和 backend factory 方案，适配的是 `deepagents==0.6.11`。

修复方式仍然是降级：

```bash
pip uninstall -y deepagents
pip install "deepagents==0.6.11" \
  -i https://mirrors.aliyun.com/pypi/simple/ \
  --trusted-host mirrors.aliyun.com
```

## 14. 推荐启动顺序

完整顺序：

```bash
# 1. 进入项目
cd /opt/coding/app

# 2. 激活 Python 环境
conda activate aicoding

# 3. 确认 deepagents 版本
pip show deepagents

# 4. 同步 skills
python scripts/sync_skills.py

# 5. 部署自检
python scripts/verify_linux_deployment.py

# 6. 启动后端
bash scripts/start_backend.sh

# 7. 另开一个终端启动前端
bash scripts/start_ui.sh
```

浏览器访问：

```text
http://服务器公网IP:3000
```

后端健康检查：

```text
http://服务器公网IP:2024/health
```

## 15. 最重要的版本提醒

当前项目部署时必须固定：

```text
deepagents==0.6.11
```

不要使用：

```text
deepagents>=0.7
```

否则容易出现：

```text
Backend factories were removed in deepagents 0.7
FilesystemMiddleware does not yet support permissions with backends that provide command execution
```

如果未来要升级到 `deepagents 0.7+`，需要单独改造：

```text
backend factory 改为直接传 backend instance
删除 create_deep_agent 和 SubAgent 里的 FilesystemPermission
重新验证 LocalShellBackend + ToolSanitizeMiddleware 的权限边界
```

当前 Linux 项目部署版本，建议先保持 `deepagents==0.6.11`。
