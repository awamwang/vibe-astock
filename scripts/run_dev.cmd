@echo off
REM 开发模式：前端 Vite Watch（:5910）+ 后端 uvicorn reload（:8910）
setlocal
title vibe-astock Dev
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_dev.ps1" %*
set "RC=%ERRORLEVEL%"
echo.
echo Dev exited with code %RC%.
pause
exit /b %RC%
