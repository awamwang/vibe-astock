@echo off
REM 生产模式：确保 frontend/dist 就绪后启动 server.py（:8910，无 reload）
setlocal
title vibe-astock Prod
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_prod.ps1" %*
set "RC=%ERRORLEVEL%"
echo.
echo Prod exited with code %RC%.
pause
exit /b %RC%
