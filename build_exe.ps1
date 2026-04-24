$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

# Build Chinese app name using Unicode code points to avoid file-encoding issues.
$appName = [string]::Concat([char]0x89C6, [char]0x9891, [char]0x8F6C, [char]0x6587, [char]0x5B57)
$exeName = "$appName.exe"
$exePath = Join-Path $root $exeName

if (Test-Path $exePath) {
    Remove-Item -Force $exePath
}
if (Test-Path "VideoToWord.exe") {
    Remove-Item -Force "VideoToWord.exe"
}
if (Test-Path "dist") {
    Remove-Item -Recurse -Force "dist"
}
if (Test-Path "build") {
    Remove-Item -Recurse -Force "build"
}

& pyinstaller --noconfirm --clean --onefile --windowed --name $appName --distpath "." gui.py

Write-Output "Build done: $exePath"
