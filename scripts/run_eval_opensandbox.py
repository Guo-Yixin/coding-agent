from __future__ import annotations

import argparse
import json
import os
import sys
import tomllib
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.evals import EvalCase, EvalRunner
from agent.evals.reporting import write_report_data


def main() -> int:
    parser = argparse.ArgumentParser(description="Run real coding-agent tasks in OpenSandbox")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--agent-ref", required=True)
    parser.add_argument("--server-config", type=Path, required=True, help="OpenSandbox server TOML; API key is read without being written to reports")
    args = parser.parse_args()

    output = args.output.expanduser().resolve()
    if output == PROJECT_ROOT or PROJECT_ROOT in output.parents:
        raise SystemExit("OpenSandbox Eval output must stay outside the coding-agent source repository")
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"Refusing to overwrite non-empty output directory: {output}")

    server_config = tomllib.loads(args.server_config.expanduser().resolve().read_text(encoding="utf-8"))
    server = server_config.get("server", {})
    host = str(server.get("host", "127.0.0.1")).strip().lower()
    port = int(server.get("port", 8080))
    api_key = str(server.get("api_key", "")).strip()
    if host not in {"127.0.0.1", "localhost", "::1"} or not 1 <= port <= 65535:
        raise SystemExit("OpenSandbox Eval requires a local-only server endpoint")
    domain = f"http://{host}:{port}"
    health = requests.get(domain.rstrip("/") + "/health", timeout=5)
    health.raise_for_status()

    dataset = args.dataset.expanduser().resolve()
    cases = [
        EvalCase.from_dict(json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(dataset.glob("*.json"))
    ]
    if not cases:
        raise SystemExit(f"No cases found in {dataset}")
    if any(case.metadata.get("agent_backend") != "opensandbox" for case in cases):
        raise SystemExit("Every case in this dataset must declare agent_backend=opensandbox")

    env_keys = (
        "OPEN_SANDBOX_DOMAIN", "OPEN_SANDBOX_API_KEY", "OPEN_SANDBOX_IMAGE",
        "OPEN_SANDBOX_CPU", "OPEN_SANDBOX_MEMORY", "OPEN_SANDBOX_TIMEOUT_SECONDS",
        "OPEN_SANDBOX_COMMAND_TIMEOUT_SECONDS", "OPEN_SANDBOX_MAX_UPLOAD_BYTES",
    )
    previous = {key: os.environ.get(key) for key in env_keys}
    os.environ["OPEN_SANDBOX_DOMAIN"] = domain
    os.environ["OPEN_SANDBOX_API_KEY"] = api_key
    if not os.environ.get("OPEN_SANDBOX_IMAGE"):
        os.environ["OPEN_SANDBOX_IMAGE"] = "coding-agent-eval/python:3.11-slim"
    try:
        runner = EvalRunner(
            output_dir=output,
            mode="real",
            env_file=args.env_file,
            agent_source_root=PROJECT_ROOT,
            agent_revision=args.agent_ref,
        )
        report = runner.run(cases, repository=args.repo.expanduser().resolve())
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    data_path = output / "report.json"
    if data_path.is_file():
        data = json.loads(data_path.read_text(encoding="utf-8"))
        data.setdefault("config", {})["opensandbox_service"] = {
            "host": host,
            "port": port,
            "localhost_only": True,
            "health_status": health.status_code,
        }
        data_path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (output / "run.json").write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        write_report_data(data, output)
    summary = report.to_dict()["summary"]
    print(json.dumps({"report_id": report.report_id, "summary": summary}, ensure_ascii=False))
    return 0 if summary.get("passed_count") == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
