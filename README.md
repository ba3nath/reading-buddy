# Reading Buddy

Local reading game for a child: listen-then-say with Kokoro clips, microphone capture, `faster-whisper` `small.en` on CPU, Beginner/Strict matching, stars, adaptive queue, day ladder / mastery, end-of-session replay, animated buddies, a growth-only garden, and a parent trend page with CSV export.

Bind: [http://127.0.0.1:8765](http://127.0.0.1:8765) (localhost only). Parent: [http://127.0.0.1:8765/parent](http://127.0.0.1:8765/parent) (no PIN).

## Requirements

- Python 3.11+ (3.12 recommended)
- **ffmpeg** on `PATH` (`ffmpeg -version` must succeed)
  - macOS: `brew install ffmpeg` (or `scripts/setup_mac.sh`)
  - Windows: `winget install Gyan.FFmpeg` (or `scripts/setup_windows.ps1`)
  - Linux: `sudo apt install ffmpeg`
- **espeak / espeak-ng** on `PATH` (Kokoro phonemizer; required before `generate_audio.py`)
  - macOS: `brew install espeak` (or `scripts/setup_mac.sh`)
  - Windows: `winget install --id eSpeak-NG.eSpeak-NG -e` (or Chocolatey `choco install espeak`; `scripts/setup_windows.ps1` tries both)
  - Linux: `sudo apt install espeak-ng`
- Chrome or Edge for the microphone (localhost is a secure context)

## Setup (once, while online)

**macOS**

```bash
chmod +x scripts/setup_mac.sh
./scripts/setup_mac.sh
```

**Windows (PowerShell)**

```powershell
.\scripts\setup_windows.ps1
```

**Manual**

```bash
cd /workspace   # or your clone root
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python scripts/download_models.py    # Whisper small.en + Kokoro ONNX
python scripts/tag_sounds.py --download   # optional: CMU dict → sound_tags
python scripts/generate_audio.py     # wavs into audio/generated/
# After TTS/postprocess changes (or if clips sound clipped): 
#   python scripts/generate_audio.py --force
python scripts/generate_illustrations.py   # word/line pictograms → static/illustrations/
```

Drop a parent recording at `audio/human/{slug}.wav` to override a generated clip.

## Run (offline second run)

After models and clips exist, play with the network off:

```bash
source .venv/bin/activate
export HF_HUB_OFFLINE=1
python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
$env:HF_HUB_OFFLINE = "1"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765). Child game: buddies (cat / Krishna / unicorn), garden growth on each completed session, rhyme-time listen-and-sing-along on levels 6–7 (one clip per line on screen). Parent page: accuracy, mastered, tricky words, sound heatmap (v1 reading-accuracy note), settings, keep-audio playback, CSV zip export.

`GET /api/health` reports `{ "whisper", "ffmpeg", "offline", "audio" }`.

## Tests (no mic)

```bash
source .venv/bin/activate
pytest -q
```

Matcher, session, adaptive, and API tests (M1–M4) use fixture transcripts and a Whisper double.

## Privacy

- Temp audio is deleted in a `finally` block after scoring.
- `keep_audio` defaults to false. When true, wavs are copied to `data/kept/{attempt_id}.wav` for the parent page; turning the setting off deletes those files.
- SQLite stores transcripts and results, never audio bytes.
- Server binds `127.0.0.1` only.

## Kindness

No visible timers, no lost stars or garden growth, no red fail screens, no buzzers. Silence is a retry. Buddies are original characters (cat, Krishna, unicorn).

## Layout

- `app/` — FastAPI, matcher, session, adaptive queue, parent aggregations, Whisper, audio helpers
- `static/` — child game + parent page (plain HTML/JS), mascot SVGs, word pictograms
- `content/items.json` — levels 1–7
- `scripts/setup_mac.sh`, `scripts/setup_windows.ps1` — one-time online setup
- `audio/generated/`, `audio/human/`, `models/`, `data/` — gitignored runtime assets
- `tests/` — pytest suites
