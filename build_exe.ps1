$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

# Build Chinese app name using Unicode code points to avoid file-encoding issues.
$appName = [string]::Concat([char]0x89C6, [char]0x9891, [char]0x5207, [char]0x7247, [char]0x673A)
$legacyName1 = [string]::Concat([char]0x89C6, [char]0x9891, [char]0x8F6C, [char]0x6587, [char]0x5B57)
$exeName = "$appName.exe"
$exePath = Join-Path $root $exeName

foreach ($old in @($exeName, "$legacyName1.exe", "VideoToWord.exe")) {
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

Write-Output "Building exe (with dashscope bundled)..."
& python -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name $appName --distpath "." `
    --hidden-import=dashscope `
    --hidden-import=dashscope.audio.asr `
    --collect-submodules=dashscope `
    gui.py

Write-Output "Build done: $exePath"
