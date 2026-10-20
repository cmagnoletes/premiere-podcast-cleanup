# Installs the podcast-cleanup skill into Claude Code on Windows.
# Run from the repo folder in PowerShell:   powershell -ExecutionPolicy Bypass -File .\install.ps1
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

# Python: the "py" launcher first (python.org installs), then "python" (winget / Store)
$py = $null
foreach ($cand in @("py", "python")) {
    $cmd = Get-Command $cand -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notlike "*WindowsApps*") { $py = $cand; break }
}
if (-not $py) {
    Write-Host "Python 3 is missing (the 'python' that opens the Microsoft Store does not count)."
    Write-Host "Install it:  winget install Python.Python.3.12   then open a NEW PowerShell window and rerun."
    exit 1
}
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Host "ffmpeg is missing. Install it:  winget install Gyan.FFmpeg   then open a NEW PowerShell window and rerun."
    exit 1
}

$skills = Join-Path $HOME ".claude\skills"
$target = Join-Path $skills "podcast-cleanup"
$source = Join-Path $here "skills\podcast-cleanup"
New-Item -ItemType Directory -Force -Path $skills | Out-Null
if (Test-Path $target) {
    $item = Get-Item $target -Force
    if ($item.LinkType -eq "Junction") { $item.Delete() }
    else { Write-Host "$target already exists and is not a link. Move it away first, then rerun."; exit 1 }
}
# A junction needs no admin rights, and 'git pull' in this folder updates the skill in place
New-Item -ItemType Junction -Path $target -Target $source | Out-Null
Write-Host "Linked $target -> $source"

Write-Host "Running the tests..."
& $py -m unittest discover -s (Join-Path $here "tests") *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Tests FAILED. Run:  $py -m unittest discover -s tests   to see why."
    exit 1
}
Write-Host "Tests passed."
Write-Host ""
Write-Host "Done. Restart Claude Code, open Premiere with the MCP Bridge started, and say:"
Write-Host "  Clean up the active sequence in Premiere."
