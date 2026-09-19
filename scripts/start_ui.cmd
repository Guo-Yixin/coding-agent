@echo off
set VITE_DASHBOARD_API_BASE_URL=http://127.0.0.1:2024
cd /d "%~dp0..\ui"
if not defined CODING_UI_HOST set "CODING_UI_HOST=127.0.0.1"
if not defined CODING_UI_PORT set "CODING_UI_PORT=3000"
node node_modules\vite\bin\vite.js dev --port %CODING_UI_PORT% --host %CODING_UI_HOST%
