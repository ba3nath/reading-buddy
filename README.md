# Reading Buddy (Milestone 1)

Local reading game for a child: words on screen, microphone capture, `faster-whisper` `small.en` on CPU, kind feedback and stars. Levels 1–3 only. No Kokoro, garden, or parent page yet.

Bind: `http://127.0.0.1:8765` (localhost only).

## Requirements

- Python 3.11+ (3.12 recommended)
- **ffmpeg** on `PATH` (`ffmpeg -version` must succeed)
  - macOS: `brew install ffmpeg`
  - Windows: `winget install Gyan.FFmpeg`
  - Linux: `sudo apt install ffmpeg`
- Chrome or Edge for the microphone (localhost is a secure context)

## Setup (once, while online)

```bash
cd /workspace   # or your clone root
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python scripts/download_models.py
```

## Run (offline OK)

After models are downloaded, play with the network off:

```bash
source .venv/bin/activate
export HF_HUB_OFFLINE=1
python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765).

`GET /api/health` reports `{ "whisper", "ffmpeg", "offline" }`. The child UI enables Start only when Whisper and ffmpeg are both ready.

## Tests (no mic)

```bash
source .venv/bin/activate
pytest tests/test_matching.py tests/test_session.py tests/test_api_m1.py -q
```

Matcher and session tests use fixture transcripts. API tests use a Whisper double and tiny fixture audio.

## Layout

- `app/` — FastAPI, matcher, session, Whisper, audio helpers
- `static/` — child game (plain HTML/JS)
- `content/items.json` — level 1–3 word slice
- `models/` — Whisper weights (gitignored)
- `data/` — SQLite + settings (gitignored)
- `tests/` — pytest suites and fixtures

## Privacy

Temp audio is always deleted in a `finally` block after scoring in Milestone 1.
`keep_audio` defaults to false in `data/settings.json`; moving clips to `data/kept/` is Milestone 4.
