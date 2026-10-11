# Reading Buddy one-time setup for Windows (online), then offline play.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

Write-Host "==> Reading Buddy setup (Windows)"
Write-Host "    Project root: $Root"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  Write-Error "python not found. Install Python 3.11+ from python.org and re-run."
}

function Test-Ffmpeg {
  try {
    & ffmpeg -version | Out-Null
    return $true
  } catch {
    return $false
  }
}

if (-not (Test-Ffmpeg)) {
  Write-Host "ffmpeg is missing. Trying winget install Gyan.FFmpeg…"
  if (Get-Command winget -ErrorAction SilentlyContinue) {
    winget install --id Gyan.FFmpeg -e --accept-package-agreements --accept-source-agreements
  } else {
    Write-Error "ffmpeg not on PATH. Install with: winget install Gyan.FFmpeg (or Chocolatey), then re-open the terminal."
  }
  $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
  if (-not (Test-Ffmpeg)) {
    Write-Error "ffmpeg -version still failing. Install ffmpeg and ensure it is on PATH, then re-run."
  }
}

Write-Host "==> Creating virtualenv"
python -m venv .venv
& "$Root\.venv\Scripts\python.exe" -m pip install --upgrade pip
& "$Root\.venv\Scripts\pip.exe" install -r requirements.txt

Write-Host "==> Downloading models (Whisper + Kokoro) — needs network once"
& "$Root\.venv\Scripts\python.exe" scripts/download_models.py

$gen = Join-Path $Root "audio\generated"
if (-not (Test-Path $gen) -or -not (Get-ChildItem $gen -ErrorAction SilentlyContinue)) {
  Write-Host "==> Generating voice clips"
  & "$Root\.venv\Scripts\python.exe" scripts/generate_audio.py
}

Write-Host ""
Write-Host "Setup complete."
Write-Host ""
Write-Host "Offline second run (network can be off):"
Write-Host "  cd `"$Root`""
Write-Host "  .\.venv\Scripts\Activate.ps1"
Write-Host "  `$env:HF_HUB_OFFLINE = `"1`""
Write-Host "  python -m uvicorn app.main:app --host 127.0.0.1 --port 8765"
Write-Host ""
Write-Host "Open http://127.0.0.1:8765 in Chrome or Edge."
Write-Host "Parent page: http://127.0.0.1:8765/parent"
