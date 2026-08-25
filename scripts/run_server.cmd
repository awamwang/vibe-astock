@echo off
REM 启动 vibe-astock Web Server（默认端口 8910）
REM 启动时会自动托管本机 AKTools（默认 :8988；AKTOOLS_MANAGED=0 可关闭）
setlocal
set "REPO=%~dp0.."
for %%I in ("%REPO%") do set "REPO=%%~fI"

set "PY=%REPO%\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

cd /d "%REPO%"
title vibe-astock Server
echo Repo: %REPO%
echo Python: %PY%
echo Starting server.py (http://127.0.0.1:8910) ...
echo AKTools will be ensured on startup (http://127.0.0.1:8988) ...
echo.
"%PY%" "%REPO%\server.py"
echo.
echo Server exited with code %ERRORLEVEL%.
pause
exit /b %ERRORLEVEL%
