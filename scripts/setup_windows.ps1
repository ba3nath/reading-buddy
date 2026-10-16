# Reading Buddy one-time setup for Windows (online), then offline play.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

Write-Host "==> Reading Buddy setup (Windows)"
Write-Host "    Project root: $Root"

# Prefer the Windows py launcher with 3.12 when available (3.14/3.15 break faster-whisper).
$PyExe = $null
$PyArgs = @()
if (Get-Command py -ErrorAction SilentlyContinue) {
  foreach ($ver in @("-3.12", "-3.11", "-3.13")) {
    $v = & py $ver -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')" 2>$null
    if ($LASTEXITCODE -eq 0 -and "$v".Trim() -match '^3\.(11|12|13)$') {
      $PyExe = "py"
      $PyArgs = @($ver)
      break
    }
  }
}
if (-not $PyExe) {
  if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "Python 3.11–3.13 not found. Install 3.12 from python.org (Add to PATH) or: winget install Python.Python.3.12"
  }
  $v = & python -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"
  if ("$v".Trim() -notmatch '^3\.(11|12|13)$') {
    Write-Error "Python $v is unsupported (need 3.11–3.13, recommend 3.12). Install Python.Python.3.12, delete .venv, re-run."
  }
  $PyExe = "python"
  $PyArgs = @()
}
$PyLabel = & $PyExe @PyArgs -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"
Write-Host "    Using: $PyExe $($PyArgs -join ' ') (Python $PyLabel)"

function Refresh-Path {
  $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
    [System.Environment]::GetEnvironmentVariable("Path", "User")
}

function Test-CommandAvailable {
  param([Parameter(Mandatory = $true)][string[]]$Names)
  foreach ($name in $Names) {
    if (Get-Command $name -ErrorAction SilentlyContinue) {
      return $true
    }
  }
  return $false
}

function Test-Ffmpeg {
  try {
    & ffmpeg -version | Out-Null
    return $true
  } catch {
    return $false
  }
}

function Test-Espeak {
  # Kokoro phonemizer accepts either classic espeak or espeak-ng on PATH.
  return (Test-CommandAvailable -Names @("espeak-ng", "espeak"))
}

if (-not (Test-Ffmpeg)) {
  Write-Host "ffmpeg is missing. Trying winget install Gyan.FFmpeg…"
  if (Get-Command winget -ErrorAction SilentlyContinue) {
    winget install --id Gyan.FFmpeg -e --accept-package-agreements --accept-source-agreements
  } else {
    Write-Error "ffmpeg not on PATH. Install with: winget install Gyan.FFmpeg (or Chocolatey), then re-open the terminal."
  }
  Refresh-Path
  if (-not (Test-Ffmpeg)) {
    Write-Error "ffmpeg -version still failing. Install ffmpeg and ensure it is on PATH, then re-run."
  }
}

if (-not (Test-Espeak)) {
  Write-Host "espeak/espeak-ng is missing (required for Kokoro phonemizer). Installing…"
  $installed = $false
  if (Get-Command winget -ErrorAction SilentlyContinue) {
    try {
      winget install --id eSpeak-NG.eSpeak-NG -e --accept-package-agreements --accept-source-agreements
      $installed = $true
    } catch {
      Write-Host "winget eSpeak-NG install failed: $($_.Exception.Message)"
    }
  }
  if (-not (Test-Espeak) -and (Get-Command choco -ErrorAction SilentlyContinue)) {
    Write-Host "Trying Chocolatey: choco install espeak…"
    try {
      choco install espeak -y
      $installed = $true
    } catch {
      Write-Host "Chocolatey espeak install failed: $($_.Exception.Message)"
    }
  }
  Refresh-Path
  if (-not (Test-Espeak)) {
    $hint = @"
ERROR: espeak or espeak-ng is not on PATH (needed before generate_audio.py).
Install one of:
  winget install --id eSpeak-NG.eSpeak-NG -e
  choco install espeak -y
Then close and re-open this terminal so PATH updates, and re-run:
  .\scripts\setup_windows.ps1
"@
    Write-Error $hint
  }
  if ($installed) {
    Write-Host "espeak/espeak-ng is available."
  }
}

Write-Host "==> Creating virtualenv"
if (Test-Path .venv) {
  Write-Host "    Removing existing .venv"
  Remove-Item -Recurse -Force .venv
}
& $PyExe @PyArgs -m venv .venv
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
