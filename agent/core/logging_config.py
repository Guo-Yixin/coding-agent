from __future__ import annotations

import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from agent.core import settings


class PrefixLoggerFilter(logging.Filter):
    """只允许指定 logger 前缀进入某个 handler。

    当前项目保留两类文件日志：
    - backend.log：完整后端日志；
    - agent-runs.log：只记录 Agent 执行链路，也就是 agent.run.*。

    用 filter 分离日志，比在业务代码里手动写多个 logger 更稳定，也更符合
    企业项目常见的“全量日志 + 关键业务域日志”设计。
    """

    def __init__(self, *prefixes: str) -> None:
        super().__init__()
        self.prefixes = prefixes

    def filter(self, record: logging.LogRecord) -> bool:
        return any(record.name.startswith(prefix) for prefix in self.prefixes)


def _configure_console_encoding() -> None:
    """尽量把控制台输出切换为 UTF-8。"""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            # 控制台编码修正只是展示优化，不能因为它失败而影响服务启动。
            continue


def _log_level() -> int:
    """解析日志级别，非法配置回退到 INFO。"""

    return getattr(logging, settings.LOG_LEVEL, logging.INFO)


def _close_and_remove_handlers(logger: logging.Logger) -> None:
    """移除并关闭旧 handler，避免 reload/test 重复写日志。

    Windows 下文件句柄被占用会影响日志轮转和测试清理，因此不能只 remove，
    还要显式 close。
    """

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            continue


def _make_timed_file_handler(path: Path) -> TimedRotatingFileHandler:
    """创建企业化的按时间轮转文件 handler。

    当前写入固定文件名，例如 backend.log；到轮转点后，标准库会生成
    backend.log.2026-07-10 这样的历史文件，并按 backupCount 自动清理。
    delay=True 可以避免进程启动时立即打开文件，只有第一条日志到来时才创建。
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    handler = TimedRotatingFileHandler(
        filename=str(path),
        when=settings.LOG_ROTATION_WHEN,
        interval=settings.LOG_ROTATION_INTERVAL,
        backupCount=settings.LOG_RETENTION_DAYS,
        encoding="utf-8",
        utc=False,
        delay=True,
    )
    handler.suffix = "%Y-%m-%d"
    return handler


def configure_logging() -> None:
    """配置后端日志系统。

    企业化改造点：
    1. 使用标准库 TimedRotatingFileHandler，而不是自定义日期 handler。
    2. 当前日志固定写入 backend.log / agent-runs.log，历史文件自动加日期后缀。
    3. 使用 backupCount 做保留天数控制，避免日志无限增长。
    4. 日志格式包含 pid 和 threadName，方便排查后台任务、SSE、工具调用并发问题。
    5. 保留 agent.run.* 专用日志，便于只看 Agent 执行链路。
    """

    _configure_console_encoding()
    settings.LOG_DIR.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(_log_level())
    _close_and_remove_handlers(root_logger)

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s [%(name)s] [pid=%(process)d thread=%(threadName)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler()
    console_handler.setLevel(_log_level())
    console_handler.setFormatter(formatter)

    backend_handler = _make_timed_file_handler(settings.backend_log_path())
    backend_handler.setLevel(_log_level())
    backend_handler.setFormatter(formatter)

    agent_handler = _make_timed_file_handler(settings.agent_log_path())
    agent_handler.setLevel(_log_level())
    agent_handler.setFormatter(formatter)
    agent_handler.addFilter(PrefixLoggerFilter("agent.run"))

    root_logger.addHandler(console_handler)
    root_logger.addHandler(backend_handler)
    root_logger.addHandler(agent_handler)

    logging.getLogger("agent").info(
        "日志系统已启动：dir=%s level=%s rotation=%s interval=%s retention=%s",
        settings.LOG_DIR,
        settings.LOG_LEVEL,
        settings.LOG_ROTATION_WHEN,
        settings.LOG_ROTATION_INTERVAL,
        settings.LOG_RETENTION_DAYS,
    )


def read_recent_log(path: Path, max_lines: int = 200) -> list[str]:
    """读取日志文件末尾若干行，供 API 页面或前端展示。"""

    if max_lines < 1:
        max_lines = 1
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return lines[-max_lines:]
