# Reading Buddy (Milestones 1–3)

Local reading game for a child: listen-then-say with Kokoro clips, microphone capture, `faster-whisper` `small.en` on CPU, Beginner/Strict matching, stars, adaptive queue, day ladder / mastery, and end-of-session replay of missed words only. Levels 1–7 (words, phrases, sentences, PD nursery-rhyme lines). No garden or full parent UI yet (M4).

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
python scripts/tag_sounds.py --download   # optional: CMU dict → sound_tags
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

Parent settings (M3 partial, no PIN UI): `GET` / `PUT /api/parent/settings` for `mode`, `level`, `auto_strict`, `session_length`.

## Tests (no mic)

```bash
source .venv/bin/activate
pytest -q
```

Matcher, session, adaptive, and API tests (M1–M3) use fixture transcripts and a Whisper double.

## Layout

- `app/` — FastAPI, matcher, session, adaptive queue, Whisper, audio helpers
- `static/` — child game (plain HTML/JS)
- `content/items.json` — levels 1–7
- `content/rhymes-for-approval.md` — PD rhyme candidates / approved set
- `audio/generated/` — Kokoro wavs (gitignored; rebuild with `generate_audio.py`)
- `audio/human/` — optional parent overrides (gitignored)
- `models/` — Whisper + Kokoro + optional CMU dict (gitignored)
- `data/` — SQLite + settings (gitignored)
- `tests/` — pytest suites and fixtures

## Privacy

Temp audio is always deleted in a `finally` block after scoring.
`keep_audio` defaults to false in `data/settings.json`; moving clips to `data/kept/` is Milestone 4.
