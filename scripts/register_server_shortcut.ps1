# 在「开始」菜单创建 vibe-astock Server 快捷方式
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\register_server_shortcut.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\register_server_shortcut.ps1 -Repo "G:\Projects\Stock\vibe-astock"

param(
    [string]$Repo = "",
    [string]$ShortcutName = "vibe-astock Server"
)

if (-not $Repo) {
    $Repo = Split-Path $PSScriptRoot -Parent
}
$Repo = (Resolve-Path $Repo).Path
$Cmd = Join-Path $Repo "scripts\run_server.cmd"
$ServerPy = Join-Path $Repo "server.py"

if (-not (Test-Path $ServerPy)) {
    Write-Error "Invalid repo (missing server.py): $Repo"
    exit 1
}
if (-not (Test-Path $Cmd)) {
    Write-Error "Missing: $Cmd"
    exit 1
}

$Programs = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
if (-not (Test-Path $Programs)) {
    New-Item -ItemType Directory -Force -Path $Programs | Out-Null
}

$LnkPath = Join-Path $Programs "$ShortcutName.lnk"
$Wsh = New-Object -ComObject WScript.Shell
$Shortcut = $Wsh.CreateShortcut($LnkPath)
$Shortcut.TargetPath = $Cmd
$Shortcut.WorkingDirectory = $Repo
$Shortcut.WindowStyle = 1
$Shortcut.Description = "启动 vibe-astock Web Server (:8910)"
$Shortcut.Save()

Write-Host "Shortcut created:"
Write-Host "  $LnkPath"
Write-Host "Target:"
Write-Host "  $Cmd"
Write-Host "Start in:"
Write-Host "  $Repo"
Write-Host ""
Write-Host "Open Start Menu and search: $ShortcutName"
