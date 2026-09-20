"""对已启动的 OpenSandbox server 做最小真实验证。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agent.sandbox import OpenSandboxConfig, OpenSandboxExecutor, SandboxFile, sandbox_health


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", default=None, help="OpenSandbox server，例如 http://192.168.11.128:8080")
    parser.add_argument("--image", default=None, help="沙箱镜像，默认读取环境变量")
    parser.add_argument("--keep", action="store_true", help="保留沙箱以便手工排查")
    args = parser.parse_args()

    config = OpenSandboxConfig.from_env()
    if args.domain:
        config = OpenSandboxConfig(**{**config.__dict__, "domain": args.domain.rstrip("/")})
    if args.image:
        config = OpenSandboxConfig(**{**config.__dict__, "image": args.image})
    if args.keep:
        config = OpenSandboxConfig(**{**config.__dict__, "keep_sandbox": True})

    health = sandbox_health(config.domain, api_key=config.api_key)
    print(json.dumps({"health": health}, ensure_ascii=False, indent=2))
    if not health["ok"]:
        return 2

    executor = OpenSandboxExecutor(config)
    try:
        sandbox_id = executor.start()
        uploaded = executor.upload_files(
            [SandboxFile(path="workspace/coding_agent_probe.py", data=b"print('opensandbox-ok')\n")]
        )
        result = executor.execute("python workspace/coding_agent_probe.py")
        payload = {
            "sandbox_id": sandbox_id,
            "uploaded_files": uploaded,
            "execution": result.__dict__,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        if result.exit_code not in (0, None) or "opensandbox-ok" not in result.stdout:
            return 3
        return 0
    finally:
        executor.close()


if __name__ == "__main__":
    sys.exit(main())
