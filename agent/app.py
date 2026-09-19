"""FastAPI 应用入口模块。

本模块是 CODING 项目后端的服务入口，负责：
- 加载环境变量和日志配置
- 创建 FastAPI 应用实例
- 配置跨域资源共享（CORS）
- 注册所有 API 路由
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agent.core.logging_config import configure_logging
from agent.env_utils import load_environment

# ---------------------------------------------------------------
# 启动前置初始化
# ---------------------------------------------------------------
# 注意：FastAPI/Uvicorn 是本地部署版中唯一的服务化入口。
# 这里显式调用 load_environment() 加载 .env 文件中的配置，
# 并调用 configure_logging() 初始化日志系统。
# 这样做的好处是不依赖 langgraph dev 等开发服务器自带的环境加载机制。
# ---------------------------------------------------------------
load_environment()
configure_logging()

# 延迟导入 API 路由模块
# 使用 # noqa: E402 忽略 flake8 关于导入顺序的警告，
# 因为此处必须等环境变量和日志配置初始化完成后才能导入路由模块。
from agent.api import dashboard_router, router  # noqa: E402

# ---------------------------------------------------------------
# 创建 FastAPI 应用实例
# ---------------------------------------------------------------
app = FastAPI(
    title="CODING Backend",  # 应用名称
    version="0.1.0",                     # 应用版本号
)

# ---------------------------------------------------------------
# 配置 CORS 中间件
# ---------------------------------------------------------------
# 允许来自以下前端的跨域请求：
#   - 127.0.0.1:3000 / localhost:3000  （常见 React/Next.js 开发端口）
#   - 127.0.0.1:5173 / localhost:5173  （常见 Vite 开发端口）
# 生产环境中应替换为实际的前端域名。
# ---------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:3000",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=True,   # 允许携带凭证（如 Cookie）
    allow_methods=["*"],       # 允许所有 HTTP 方法
    allow_headers=["*"],       # 允许所有请求头
)

# ---------------------------------------------------------------
# 注册路由
# ---------------------------------------------------------------
# router          - 主要 API 路由（核心业务逻辑）
# dashboard_router - 仪表盘相关 API 路由（管理/监控用途）
# ---------------------------------------------------------------
app.include_router(router)
app.include_router(dashboard_router)
