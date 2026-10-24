# Reading Buddy

A local reading game for a child: listen, then say it back. Kokoro speaks the prompt; the mic and `faster-whisper` (`small.en` on CPU) score the reading. Stars, an adaptive queue, day-ladder mastery, end-of-session replay, buddies, a growth-only garden, and a parent trends page (CSV export, no PIN).

## Quick start (after `git pull`)

From the repo root:

```bash
./run
# Windows / fallback: python3 runner.py
```

The runner will:

1. Find Python 3.11+, create `.venv` if needed, and re-run inside it  
2. Install `requirements.txt` when it changed (or imports are missing)  
3. Download Whisper + Kokoro models once if they are missing  
4. Regenerate listen clips only when content/TTS inputs changed or clips are missing  
5. Restart the server and print URLs, for example:

```text
This computer:  http://127.0.0.1:8765
Parent page:    http://127.0.0.1:8765/parent
```

With `./run --lan`, a Wi‑Fi device line is also printed (e.g. `http://192.168.x.x:8765`).

Use Chrome or Edge (needed for the microphone).

| Command | What it does |
| --- | --- |
| `./run` | Bootstrap + audio if needed + restart (binds localhost) |
| `./run --stop` | Stop the server |
| `./run --force-audio` | Rebuild all listen clips |
| `./run --force-deps` | Re-run `pip install -r requirements.txt` |
| `./run --lan` | Bind `0.0.0.0` so a phone/tablet on Wi‑Fi can connect |
| `./run --localhost-only` | Same as default bind (kept for older scripts) |
| `./run --foreground` | Keep uvicorn in this terminal |

On macOS, the default start path installs a LaunchAgent via `launchctl` (`com.readingbuddy.server`) so the app can come back after reboot. Elsewhere, uvicorn runs in the foreground unless you pass `--background`.

## Requirements

- Python **3.11–3.13** (**3.12 recommended**). Declared in `pyproject.toml` as `requires-python = ">=3.11,<3.14"`.
  - **Why:** `kokoro-onnx` requires `<3.14`; `ctranslate2` / `onnxruntime` have no good **3.15** wheels yet (Windows pip fails with `ResolutionImpossible`).
  - Windows: [python.org 3.12](https://www.python.org/downloads/) (tick “Add to PATH”), or `winget install Python.Python.3.12`, then delete `.venv` and run `py -3.12 runner.py`
  - Also on Windows: `winget install --id eSpeak-NG.eSpeak-NG -e` and `winget install Gyan.FFmpeg`
- **ffmpeg** on `PATH` (`ffmpeg -version`)
  - macOS: `brew install ffmpeg` (or `scripts/setup_mac.sh`)
  - Windows: `winget install Gyan.FFmpeg` (or `scripts/setup_windows.ps1`)
  - Linux: `sudo apt install ffmpeg`
- **espeak** or **espeak-ng** on `PATH` (Kokoro phonemizer)
  - macOS: `brew install espeak`
  - Windows: `winget install --id eSpeak-NG.eSpeak-NG -e`
  - Linux: `sudo apt install espeak-ng`

First-time machine setup (Homebrew tools + venv + models) can still use:

```bash
./scripts/setup_mac.sh          # macOS
.\scripts\setup_windows.ps1     # Windows PowerShell
```

After that, day-to-day is just `./run`.

## What the child and parent see

**Child** — pick a buddy, then Words / Phrases / Rhymes / Stories. Each difficulty has eight sets; finished sets are marked done, started ones look partial. One Start button; refresh resumes an open session. Rhymes play a real nursery poem line by line, then a required read-through. Stories are short decodable narratives in order, then a read-through. Missed words get a kind second try; silence is a retry, not a fail.

**Parent** (`/parent`) — accuracy, mastered words, tricky words, pattern + sound heatmaps, record-your-voice overrides, settings (mode, length, buddy, keep-audio, effort stars), tomorrow note, kept-clip playback, CSV zip (analytics only — use `./run --backup` to restore progress).

**Backup / restore progress** (DB + settings + kept clips + parent voice in `audio/human/`):

```bash
./run --backup
./run --restore data/backup-YYYYMMDD-HHMMSS.zip --force-restore
# or: python scripts/backup_data.py backup|restore …
```

`GET /api/health` → `{ "whisper", "ffmpeg", "offline", "audio" }`.

## Matching (Beginner vs Strict)

- **Beginner** — forgiving on short slips; drops of tiny words (`the`, `a`, `to`, …) on longer lines do not fail a clear reading.  
- **Strict** — needs the full word sequence. Exact multi-word lines use mean Whisper confidence (nursery words like *hickory* are often soft), so a correct reading is not failed by one low token score.

Whisper estimates what was spoken; it is not a definitive reading assessment. Labeled FP/FN for both modes live under `eval/matching/` (`python scripts/eval_matching_benchmark.py`).

## Offline play

After models and clips exist, the network can be off. `./run` sets `HF_HUB_OFFLINE=1` for the server. Manual equivalent:

```bash
source .venv/bin/activate
export HF_HUB_OFFLINE=1
python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
# Wi‑Fi devices: use --host 0.0.0.0 (same as ./run --lan)
```

## Optional / advanced

```bash
python scripts/tag_sounds.py --download   # CMU dict → sound_tags
python scripts/generate_illustrations.py  # pictograms → static/illustrations/
# Override a clip with a parent recording:
#   audio/human/{slug}.wav
```

Listen-clip review agent (Whisper audit / A/B retune): see `audio-clip-review/README.md`.

## Tests

```bash
source .venv/bin/activate
pytest -q
# Runner / dependency contract + matching:
pytest -q tests/test_dependencies.py tests/test_runner.py tests/test_matching.py
# Line coverage for the install path:
pytest -q --cov=runner --cov=app.matching --cov-report=term-missing \
  tests/test_dependencies.py tests/test_runner.py tests/test_matching.py
# Gate (includes a "runner" phase marker check):
python test-coverage/check.py --phase runner
```

## Privacy & kindness

- Temp mic audio is deleted after scoring.  
- `keep_audio` defaults to off; when on, wavs go to `data/kept/{attempt_id}.wav` for the parent page.  
- SQLite stores transcripts and results, never audio bytes.  
- Default bind is `127.0.0.1` (this computer only). Use `./run --lan` for a tablet on Wi‑Fi.  
- No visible timers, no lost stars or garden growth, no red fail screens, no buzzers.

## Layout

| Path | Role |
| --- | --- |
| `run` / `runner.py` | Day-to-day bootstrap + restart |
| `app/` | FastAPI, matcher, session, adaptive queue, Whisper, audio |
| `static/` | Child + parent UI, mascots, pictograms |
| `content/items.json` | Words, phrases, nursery rhymes, short stories |
| `scripts/` | Setup, models, audio, illustrations |
| `audio/generated/`, `models/`, `data/` | Runtime assets (gitignored) |
| `tests/` | pytest |
