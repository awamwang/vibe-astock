# 生产模式：确保 frontend/dist 就绪后，单进程启动 server.py（:8910，无 reload）
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/run_prod.ps1
#   或双击 / 运行 scripts/run_prod.cmd
#
# 打开 http://127.0.0.1:8910 即可（API + 静态前端同端口）。
# Ctrl+C 停止服务。
#
# 参数：
#   -Port N          后端端口（默认 8910 / $env:VIBE_PORT）
#   -ForceBuild      强制重新 npm run build
#   -SkipBuild       已有 dist 时跳过构建（缺 dist 仍会构建）

param(
    [int]$Port = 0,
    [switch]$ForceBuild,
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$Repo = Split-Path $PSScriptRoot -Parent
if ($Port -le 0) {
    if ($env:VIBE_PORT) { $Port = [int]$env:VIBE_PORT } else { $Port = 8910 }
}

if ($ForceBuild -and $SkipBuild) {
    Write-Host "不能同时指定 -ForceBuild 与 -SkipBuild"
    exit 1
}

$Py = Join-Path $Repo ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { $Py = "python" }

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Write-Host "未找到 npm，请先安装 Node.js"
    exit 1
}

# pwsh 的 Get-Command npm 指向 npm.ps1，直接 & npm 在部分环境下不稳定；统一走 npm.cmd
$npmDir = Split-Path (Get-Command npm).Source -Parent
$npmCmd = Join-Path $npmDir "npm.cmd"
if (-not (Test-Path $npmCmd)) {
    Write-Host "找不到 npm.cmd: $npmCmd"
    exit 1
}

$frontendDir = Join-Path $Repo "frontend"
$distIndex = Join-Path $frontendDir "dist\index.html"
if (-not (Test-Path (Join-Path $frontendDir "package.json"))) {
    Write-Host "找不到 frontend/package.json: $frontendDir"
    exit 1
}

if (-not (Test-Path (Join-Path $frontendDir "node_modules"))) {
    Write-Host "正在安装前端依赖..."
    Push-Location $frontendDir
    try {
        & $npmCmd install
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    } finally {
        Pop-Location
    }
}

function Test-FrontendNeedsBuild {
    if (-not (Test-Path $distIndex)) { return $true }
    $distTime = (Get-Item $distIndex).LastWriteTimeUtc
    $watchRoots = @(
        (Join-Path $frontendDir "src"),
        (Join-Path $frontendDir "index.html"),
        (Join-Path $frontendDir "package.json"),
        (Join-Path $frontendDir "vite.config.ts"),
        (Join-Path $frontendDir "tsconfig.json"),
        (Join-Path $frontendDir "tsconfig.app.json"),
        (Join-Path $frontendDir "tailwind.config.js"),
        (Join-Path $frontendDir "postcss.config.js")
    )
    foreach ($root in $watchRoots) {
        if (-not (Test-Path $root)) { continue }
        $item = Get-Item $root
        if (-not $item.PSIsContainer) {
            if ($item.LastWriteTimeUtc -gt $distTime) { return $true }
            continue
        }
        $newer = Get-ChildItem -Path $root -Recurse -File -ErrorAction SilentlyContinue |
            Where-Object { $_.LastWriteTimeUtc -gt $distTime } |
            Select-Object -First 1
        if ($null -ne $newer) { return $true }
    }
    return $false
}

$needBuild = $false
if ($ForceBuild) {
    $needBuild = $true
} elseif ($SkipBuild) {
    if (-not (Test-Path $distIndex)) {
        Write-Host "未找到 frontend/dist，忽略 -SkipBuild，开始构建..."
        $needBuild = $true
    }
} else {
    $needBuild = Test-FrontendNeedsBuild
}

if ($needBuild) {
    Write-Host "正在构建前端（npm run build）..."
    Push-Location $frontendDir
    try {
        & $npmCmd run build
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    } finally {
        Pop-Location
    }
    if (-not (Test-Path $distIndex)) {
        Write-Host "构建完成但找不到 $distIndex"
        exit 1
    }
    Write-Host "前端构建完成"
} else {
    Write-Host "前端 dist 已是最新，跳过构建"
}

& $Py -c "import aktools" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "正在安装 aktools（后端会托管本机 :8988）..."
    & $Py -m pip install "aktools>=0.0.90"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

# 生产模式关闭热重载（避免继承开发会话里残留的 VIBE_RELOAD=1）
Remove-Item Env:VIBE_RELOAD -ErrorAction SilentlyContinue
$env:VIBE_PORT = "$Port"

Write-Host ""
Write-Host "生产模式"
Write-Host "  打开      http://127.0.0.1:$Port"
Write-Host "  AKTools  http://127.0.0.1:8988   随后端自动托管"
Write-Host "  Ctrl+C 停止服务"
Write-Host ""

Set-Location $Repo
& $Py (Join-Path $Repo "server.py")
exit $LASTEXITCODE
