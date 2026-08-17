# Register daily review scheduled task (22:00 every day).
# Script itself skips non-trading days / existing usable reviews.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\register_daily_review_task.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\register_daily_review_task.ps1 -Repo "G:\Projects\Stock\vibe-astock"
#
# If Access Denied: run PowerShell as Administrator, or create the task in Task Scheduler GUI.

param(
    [string]$Repo = "",
    [string]$TaskName = "VibeAstockDailyReview",
    [string]$Time = "22:00"
)

if (-not $Repo) {
    $Repo = Split-Path $PSScriptRoot -Parent
}
$Repo = (Resolve-Path $Repo).Path
$MainPy = Join-Path $Repo "main.py"
$Cmd = Join-Path $Repo "scripts\run_daily_review_task.cmd"

if (-not (Test-Path $MainPy)) {
    Write-Error "Invalid repo (missing main.py): $Repo"
    exit 1
}
if (-not (Test-Path $Cmd)) {
    Write-Error "Missing: $Cmd"
    exit 1
}

$LogDir = Join-Path $env:USERPROFILE ".duanxian-agents\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogFile = Join-Path $LogDir "daily_review_task.log"

Write-Host "Repo: $Repo"
Write-Host "Task: $TaskName"
Write-Host "When: daily at $Time"
Write-Host "Entry: $Cmd"
Write-Host "Log: $LogFile"
Write-Host ""

$createOut = & schtasks.exe /Create /TN $TaskName /TR $Cmd /SC DAILY /ST $Time /F /RL LIMITED 2>&1
$rc = $LASTEXITCODE

if ($rc -eq 0) {
    Write-Host "Scheduled task registered."
    schtasks.exe /Query /TN $TaskName /FO LIST
    Write-Host ""
    Write-Host "Run now:  schtasks /Run /TN $TaskName"
    Write-Host "Delete:   schtasks /Delete /TN $TaskName /F"
    exit 0
}

Write-Host "Auto-register failed (exit $rc):"
Write-Host ($createOut | Out-String)
Write-Host ""
Write-Host "Do one of the following:"
Write-Host "1) Open PowerShell as Administrator and re-run this script."
Write-Host "2) Win+R -> taskschd.msc -> Create Basic Task:"
Write-Host "   Name: $TaskName"
Write-Host "   Trigger: Daily at $Time"
Write-Host "   Action: Start a program"
Write-Host "   Program: $Cmd"
Write-Host "   Start in: $Repo"
Write-Host "3) Manual dry-run of the entry script:"
Write-Host "   $Cmd"
exit $rc
