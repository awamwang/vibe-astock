$ErrorActionPreference = "Stop"
$work = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $env:USERPROFILE ".duanxian-agents\cache\xgb_broken_rate"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$outLog = Join-Path $logDir "backfill.out.log"
$errLog = Join-Path $logDir "backfill.err.log"
$p = Start-Process -FilePath "python" `
  -ArgumentList @("scripts/fetch_xgb_broken_rate.py", "backfill", "--days", "220", "--newest-first") `
  -WorkingDirectory $work `
  -RedirectStandardOutput $outLog `
  -RedirectStandardError $errLog `
  -PassThru `
  -WindowStyle Hidden
"started pid=$($p.Id)"
"out=$outLog"
"err=$errLog"
