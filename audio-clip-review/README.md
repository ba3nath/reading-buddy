# Audio clip review agent

BDK agent that audits and retunes **Reading Buddy** listen clips using the
Whisper single-token A/B workflow learned in production.

## Defaults

| Setting | Value |
| --- | --- |
| Purpose | Domain assistant over the Reading Buddy audio pipeline |
| Model | `grok-4.5` (effort=high, fast) |
| Channels | Playground + HTTP |
| MCP | none |
| Root | Parent Reading Buddy repo (`READING_BUDDY_ROOT` override) |

## Tools

| Tool | Role |
| --- | --- |
| `get_overrides` | Read current word/voice TTS pins |
| `audit_clips` | Whisper classify OK / weak / fail |
| `ab_tune_words` | Single-token A/B for weak/fail |
| `apply_winners` | Merge winners (dry-run by default) |
| `regen_clips` | Force-regenerate wavs |

## CLI (same engine)

```bash
# from Reading Buddy root
python scripts/review_audio_clips.py audit --out /tmp/audio_audit.json
python scripts/review_audio_clips.py ab-tune --audit /tmp/audio_audit.json --out /tmp/audio_winners.json
python scripts/review_audio_clips.py apply-winners --winners /tmp/audio_winners.json          # dry-run
python scripts/review_audio_clips.py apply-winners --winners /tmp/audio_winners.json --write
python scripts/review_audio_clips.py regen --winners /tmp/audio_winners.json
```

## Run the agent

```bash
cd audio-clip-review
npx bdk validate --dir .
npx bdk info --dir . --json
npx bdk call get_overrides --dir . --input '{"words":["cat","pen"]}'
npx bdk serve --dir . --mode single --dev
# http://127.0.0.1:3000/playground
```

Model turns need a Cursor API credential (`CURSOR_API_KEY` / `bdk login`).
