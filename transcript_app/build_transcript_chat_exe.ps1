$ErrorActionPreference = "Stop"

$appDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $appDir
$chatUi = Join-Path $appDir "chat-ui"
$releaseDir = Join-Path $appDir "electron-release"

$appName = -join [char[]](0x8F6C, 0x5199, 0x67E5, 0x8BC1)
$exeName = "$appName.exe"
$exePath = Join-Path $root $exeName

Set-Location $chatUi

Write-Output "Cleaning old electron-release and root exe..."
foreach ($old in @($exeName, "$appName-*.exe", "转写查证-*.exe")) {
    Get-ChildItem -Path $root -Filter $old -ErrorAction SilentlyContinue | Remove-Item -Force
}
if (Test-Path $releaseDir) {
    Remove-Item -Recurse -Force $releaseDir
}
$localDist = Join-Path $chatUi "dist"
if (Test-Path $localDist) {
    Remove-Item -Recurse -Force $localDist
}

if (-not (Test-Path (Join-Path $chatUi "node_modules"))) {
    Write-Output "npm install..."
    npm install
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Output "Building Electron portable (vite + electron-builder)..."
npm run release
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$built = Get-ChildItem -Path $releaseDir -Filter "*.exe" -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if (-not $built) {
    throw "No exe found under $releaseDir"
}

Copy-Item -Force $built.FullName $exePath
Write-Output "Build done: $exePath"
Write-Output "Place this exe next to transcript_cli.py / runs / .env (repo root), same level as 视频切片机.exe."
