#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
UI_ROOT="${PROJECT_ROOT}/ui"

cd "${UI_ROOT}"

if [[ ! -d "node_modules" ]]; then
  npm install
fi

export VITE_DASHBOARD_API_BASE_URL="${VITE_DASHBOARD_API_BASE_URL:-http://127.0.0.1:2024}"
exec node "${UI_ROOT}/node_modules/vite/bin/vite.js" dev --host "${CODING_UI_HOST:-0.0.0.0}" --port "${CODING_UI_PORT:-3000}"
