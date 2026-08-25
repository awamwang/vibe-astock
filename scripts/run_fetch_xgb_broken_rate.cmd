@echo off
REM 选股宝炸板率离线拉取（供分位序列并入炸板率）
REM 用法示例：
REM   scripts\run_fetch_xgb_broken_rate.cmd status
REM   scripts\run_fetch_xgb_broken_rate.cmd backfill --days 220
REM   scripts\run_fetch_xgb_broken_rate.cmd incr
REM   scripts\run_fetch_xgb_broken_rate.cmd today
REM   scripts\run_fetch_xgb_broken_rate.cmd watch

setlocal
cd /d "%~dp0\.."
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" "scripts\fetch_xgb_broken_rate.py" %*
) else (
  python "scripts\fetch_xgb_broken_rate.py" %*
)
exit /b %ERRORLEVEL%
