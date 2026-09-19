from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.core.logging_config import configure_logging
from agent.core.runtime import run_agent_task
from agent.env_utils import load_environment


DEFAULT_PROMPT = """请在这个 Gitee 仓库中创建一个最小 FastAPI 项目：
1. 提供 /health 接口，返回 {"status": "ok"}。
2. 添加 pytest 测试。
3. 添加 README，说明安装、启动和测试方式。
4. 运行测试。
5. 提交到 coding/e2e-verify 分支。
6. 创建 Gitee Pull Request。
"""


def main() -> None:
    """真实 Gitee 端到端验收入口。

    这个脚本会真实调用 DeepSeek、clone Gitee 仓库、提交代码、push 分支并创建 PR。
    因此必须传入专门的测试仓库，不要对生产仓库直接运行。
    """

    parser = argparse.ArgumentParser(description="运行 CODING Gitee 端到端验收")
    parser.add_argument("repo_url", help="Gitee 测试仓库地址，例如 https://gitee.com/owner/repo.git")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="发送给 Agent 的任务说明")
    parser.add_argument("--thread-id", default=None, help="可选，指定 LangGraph thread_id")
    args = parser.parse_args()

    load_environment()
    configure_logging()

    result = run_agent_task(repo_url=args.repo_url, prompt=args.prompt, thread_id=args.thread_id)
    # Windows 控制台可能是 GBK 编码，直接打印模型返回的 Unicode 内容会失败。
    # ensure_ascii=True 可以把中文和特殊符号转义成 ASCII，保证验收脚本稳定退出。
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
