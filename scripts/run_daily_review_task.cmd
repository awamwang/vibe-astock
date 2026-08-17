@echo off
REM 计划任务入口：幂等复盘，日志追加到 %%USERPROFILE%%\.duanxian-agents\logs\
setlocal
set "REPO=%~dp0.."
for %%I in ("%REPO%") do set "REPO=%%~fI"
set "LOGDIR=%USERPROFILE%\.duanxian-agents\logs"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
set "LOG=%LOGDIR%\daily_review_task.log"

set "PY=%REPO%\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

echo ===== %DATE% %TIME% =====>> "%LOG%"
cd /d "%REPO%"
"%PY%" "%REPO%\scripts\daily_review_if_missing.py" --repo "%REPO%" >> "%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
echo exit=%RC%>> "%LOG%"
exit /b %RC%
