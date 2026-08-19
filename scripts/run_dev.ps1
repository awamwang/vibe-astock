# 开发模式：前端 Vite Watch（:5910）+ 后端 uvicorn reload（:8910）
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/run_dev.ps1
#   或双击 / 运行 scripts/run_dev.cmd
#
# 请打开前端地址做开发（HMR）；后端只给 /api，改 .py 会自动重启。
# Ctrl+C 会同时停止前后端。

param(
    [int]$Port = 0,
    [int]$FrontendPort = 5910
)

$ErrorActionPreference = "Stop"
$Repo = Split-Path $PSScriptRoot -Parent
if ($Port -le 0) {
    if ($env:VIBE_PORT) { $Port = [int]$env:VIBE_PORT } else { $Port = 8910 }
}

$Py = Join-Path $Repo ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { $Py = "python" }

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Write-Host "未找到 npm，请先安装 Node.js"
    exit 1
}

# pwsh 的 Get-Command npm 指向 npm.ps1，Start-Process 无法执行脚本文件。
# 必须改用同目录的 npm.cmd，否则前端进程会立刻失败，5910 端口永远起不来。
$npmDir = Split-Path (Get-Command npm).Source -Parent
$npmCmd = Join-Path $npmDir "npm.cmd"
if (-not (Test-Path $npmCmd)) {
    Write-Host "找不到 npm.cmd: $npmCmd"
    exit 1
}

$frontendDir = Join-Path $Repo "frontend"
if (-not (Test-Path (Join-Path $frontendDir "package.json"))) {
    Write-Host "找不到 frontend/package.json: $frontendDir"
    exit 1
}
if (-not (Test-Path (Join-Path $frontendDir "node_modules"))) {
    Write-Host "正在安装前端依赖..."
    Push-Location $frontendDir
    try {
        npm install
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    } finally {
        Pop-Location
    }
}

& $Py -c "import watchfiles" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "正在安装 watchfiles（后端热重载需要）..."
    & $Py -m pip install "watchfiles>=0.21"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

function Test-TcpOpen([string]$TargetHost, [int]$TargetPort) {
    try {
        $client = [System.Net.Sockets.TcpClient]::new()
        $iar = $client.BeginConnect($TargetHost, $TargetPort, $null, $null)
        $ok = $iar.AsyncWaitHandle.WaitOne(200, $false)
        if (-not $ok -or -not $client.Connected) {
            $client.Close()
            return $false
        }
        $client.EndConnect($iar)
        $client.Close()
        return $true
    } catch {
        return $false
    }
}

Write-Host ""
Write-Host "开发模式"
Write-Host "  前端 Watch  http://127.0.0.1:$FrontendPort   请打开这个地址"
Write-Host "  后端 Reload http://127.0.0.1:$Port          /api 热重启"
Write-Host "  Ctrl+C 同时停止前后端"
Write-Host ""

$viteOut = Join-Path $env:TEMP "vibe-astock-vite.out.log"
$viteErr = Join-Path $env:TEMP "vibe-astock-vite.err.log"
Remove-Item $viteOut, $viteErr -ErrorAction SilentlyContinue

$frontend = Start-Process -FilePath $npmCmd -ArgumentList @(
    "run", "dev", "--", "--host", "127.0.0.1", "--port", "$FrontendPort", "--strictPort"
) -WorkingDirectory $frontendDir -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput $viteOut -RedirectStandardError $viteErr

$ready = $false
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 250
    if ($frontend.HasExited) { break }
    if (Test-TcpOpen "127.0.0.1" $FrontendPort) {
        $ready = $true
        break
    }
}

if (-not $ready) {
    Write-Host "前端 Vite 未能在 http://127.0.0.1:$FrontendPort 启动"
    if ($frontend.HasExited) {
        Write-Host "进程已退出，退出码: $($frontend.ExitCode)"
    }
    foreach ($log in @($viteErr, $viteOut)) {
        if (Test-Path $log) {
            $text = Get-Content $log -Raw -ErrorAction SilentlyContinue
            if ($text) { Write-Host $text }
        }
    }
    if (-not $frontend.HasExited) {
        & taskkill.exe /PID $frontend.Id /T /F 2>$null | Out-Null
    }
    exit 1
}

Write-Host "前端已就绪  http://127.0.0.1:$FrontendPort"

$env:VIBE_RELOAD = "1"
$env:VIBE_PORT = "$Port"

try {
    Set-Location $Repo
    & $Py (Join-Path $Repo "server.py")
} finally {
    if ($null -ne $frontend -and -not $frontend.HasExited) {
        Write-Host "正在关闭前端..."
        & taskkill.exe /PID $frontend.Id /T /F 2>$null | Out-Null
    }
}
