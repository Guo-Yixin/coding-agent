@echo off
cd /d "%~dp0.."
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
if not defined CODING_BACKEND_HOST set "CODING_BACKEND_HOST=127.0.0.1"
if not defined CODING_BACKEND_PORT set "CODING_BACKEND_PORT=2024"
.venv\Scripts\python.exe -m uvicorn agent.app:app --host %CODING_BACKEND_HOST% --port %CODING_BACKEND_PORT%
