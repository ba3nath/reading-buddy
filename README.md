# Reading Buddy (Milestones 1–2)

Local reading game for a child: words on screen, listen-then-say with Kokoro clips, microphone capture, `faster-whisper` `small.en` on CPU, kind feedback, stars, and end-of-session replay of missed words. Levels 1–3 words. No garden or parent page yet.

Bind: `http://127.0.0.1:8765` (localhost only).

## Requirements

- Python 3.11+ (3.12 recommended)
- **ffmpeg** on `PATH` (`ffmpeg -version` must succeed)
  - macOS: `brew install ffmpeg`
  - Windows: `winget install Gyan.FFmpeg`
  - Linux: `sudo apt install ffmpeg`
- **espeak-ng** (for Kokoro phonemizer): `sudo apt install espeak-ng` / `brew install espeak`
- Chrome or Edge for the microphone (localhost is a secure context)

## Setup (once, while online)

```bash
cd /workspace   # or your clone root
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python scripts/download_models.py    # Whisper small.en + Kokoro ONNX
python scripts/generate_audio.py     # wavs into audio/generated/
```

Voice id is `bf_isabella` (British female, chosen from the install’s British voice list). Override with `python scripts/generate_audio.py --voice bf_emma` if you prefer.

Drop a parent recording at `audio/human/{slug}.wav` to override a generated clip (same basename).

## Run (offline OK)

After models and clips exist, play with the network off:

```bash
source .venv/bin/activate
export HF_HUB_OFFLINE=1
python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765).

`GET /api/health` reports `{ "whisper", "ffmpeg", "offline", "audio" }`. The child UI enables Start when Whisper, ffmpeg, and generated clips are ready.

## Tests (no mic)

```bash
source .venv/bin/activate
pytest tests/test_matching.py tests/test_session.py tests/test_api_m1.py tests/test_api_m2.py -q
```

Matcher and session tests use fixture transcripts. API tests use a Whisper double and tiny fixture audio.

## Layout

- `app/` — FastAPI, matcher, session, Whisper, audio helpers
- `static/` — child game (plain HTML/JS)
- `content/items.json` — level 1–3 word slice
- `audio/generated/` — Kokoro wavs (gitignored; rebuild with `generate_audio.py`)
- `audio/human/` — optional parent overrides (gitignored)
- `models/` — Whisper + Kokoro weights (gitignored)
- `data/` — SQLite + settings (gitignored)
- `tests/` — pytest suites and fixtures

## Privacy

Temp audio is always deleted in a `finally` block after scoring.
`keep_audio` defaults to false in `data/settings.json`; moving clips to `data/kept/` is Milestone 4.
