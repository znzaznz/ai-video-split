# Project verify: syntax check + unit tests (no API keys required).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path | Split-Path -Parent
Set-Location $root

$modules = @(
    "gui.py",
    "main.py",
    "auto_clip_from_transcript.py",
    "slice_logic.py",
    "slice_strategy.py",
    "video_to_text_paraformer.py",
    "transcript_correct.py"
)

Write-Host "py_compile..."
foreach ($f in $modules) {
    if (-not (Test-Path $f)) {
        Write-Warning "skip missing $f"
        continue
    }
    python -m py_compile $f
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

if (Test-Path "tests") {
    Write-Host "unittest discover..."
    python -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} else {
    Write-Host "no tests/ directory, skip unittest"
}

Write-Host "verify OK"
