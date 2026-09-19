#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${PROJECT_ROOT}"

if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="$(command -v python3 || command -v python)"
fi

exec "${PYTHON_BIN}" -m uvicorn agent.app:app --host "${CODING_BACKEND_HOST:-0.0.0.0}" --port "${CODING_BACKEND_PORT:-2024}"
