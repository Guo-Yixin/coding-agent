from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.tools import fetch_url


def main() -> None:
    """验证 fetch_url 直接导出，并且会拒绝本机/内网地址。"""

    result = fetch_url.invoke({"url": "http://127.0.0.1:8000/health"})
    if result.get("ok") is not False:
        raise AssertionError(f"fetch_url 应拒绝本机地址，实际：{result}")
    if "拦截" not in str(result.get("error", "")):
        raise AssertionError(f"fetch_url 拒绝原因应是中文安全拦截，实际：{result}")

    print("fetch_url tool verification passed")


if __name__ == "__main__":
    main()
