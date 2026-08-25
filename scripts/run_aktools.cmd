@echo off
REM 单独启动本机 AKTools（默认 127.0.0.1:8988）
REM 正常情况不必手动跑：server.py 启动时会自动托管。
setlocal
set "REPO=%~dp0.."
for %%I in ("%REPO%") do set "REPO=%%~fI"

set "PY=%REPO%\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

set "AKTOOLS_HOST=127.0.0.1"
if not defined AKTOOLS_PORT set "AKTOOLS_PORT=8988"

cd /d "%REPO%"
title AKTools :%AKTOOLS_PORT%
echo Repo: %REPO%
echo Python: %PY%
echo Starting python -m aktools --host %AKTOOLS_HOST% --port %AKTOOLS_PORT% ...
echo.
"%PY%" -m aktools --host "%AKTOOLS_HOST%" --port "%AKTOOLS_PORT%"
echo.
echo AKTools exited with code %ERRORLEVEL%.
pause
exit /b %ERRORLEVEL%
