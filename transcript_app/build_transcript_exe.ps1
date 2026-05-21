$ErrorActionPreference = "Stop"

$appDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $appDir
Set-Location $root

$appName = [string]::Concat(
    [char]0x89C6, [char]0x9891, [char]0x8F6C, [char]0x5199,
    [char]0x7EA0, [char]0x9519
)
$exeName = "$appName.exe"
$exePath = Join-Path $root $exeName

foreach ($old in @($exeName)) {
    $oldPath = Join-Path $root $old
    if (Test-Path $oldPath) {
        Remove-Item -Force $oldPath
    }
}
if (Test-Path "dist") {
    Remove-Item -Recurse -Force "dist"
}
if (Test-Path "build") {
    Remove-Item -Recurse -Force "build"
}

Write-Output "Installing build deps (pyinstaller, dashscope)..."
& python -m pip install pyinstaller dashscope -q

Write-Output "Building transcript exe (with dashscope bundled)..."
& python -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name $appName --distpath "." `
    --paths $root `
    --hidden-import=dashscope `
    --hidden-import=dashscope.audio.asr `
    --collect-submodules=dashscope `
    "transcript_app\transcript_gui.py"

Write-Output "Build done: $exePath"
