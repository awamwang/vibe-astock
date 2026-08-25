$ErrorActionPreference = "Continue"
$work = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $env:USERPROFILE ".duanxian-agents\cache\xgb_broken_rate"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -and ($_.CommandLine -like "*fetch_xgb_broken_rate*") } |
  ForEach-Object {
    Write-Output "kill $($_.ProcessId) $($_.Name)"
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
  }
Start-Sleep -Seconds 1
$left = @(Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -and ($_.CommandLine -like "*fetch_xgb_broken_rate*") })
if ($left.Count -gt 0) {
  $left | ForEach-Object { Write-Output "still $($_.ProcessId)" }
} else {
  Write-Output "stopped"
}

$outLog = Join-Path $logDir "backfill_fast.out.log"
$errLog = Join-Path $logDir "backfill_fast.err.log"
# 清空本次日志，方便盯进度
"" | Set-Content -Path $outLog -Encoding utf8
"" | Set-Content -Path $errLog -Encoding utf8

$p = Start-Process -FilePath "python" `
  -ArgumentList @(
    "scripts/fetch_xgb_broken_rate.py",
    "backfill",
    "--days", "220",
    "--newest-first",
    "--interval", "0",
    "--jitter", "0"
  ) `
  -WorkingDirectory $work `
  -RedirectStandardOutput $outLog `
  -RedirectStandardError $errLog `
  -PassThru `
  -WindowStyle Hidden

Write-Output "started pid=$($p.Id)"
Write-Output "out=$outLog"
Write-Output "err=$errLog"
