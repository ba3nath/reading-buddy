---
name: single-token-tts
description: >-
  Rules for retuning Reading Buddy listen clips without carrier words.
  Use when auditing, A/B tuning, or applying TTS overrides.
---

# Single-token TTS

Kids hear the generated clip while reading one word on screen.

## Allowed spoken forms

- `cat`, `cat.`, `cat!`, `cat?`
- Never `the cat`, `fat cat`, `a cat`, `say cat`

## A/B grid

Voices: `bf_emma`, `bf_alice`, `bf_isabella`, `bm_lewis`  
Speeds / punct: `.` @ 0.78–0.94, `!` @ 0.95–1.0, bare @ 0.88–1.0, `?` @ 0.92

Score = `hits*10 - filler*2 + (1 if emma else 0)`. Early-stop on clean full hits.

## After apply

Regenerate wavs (`regen_clips` or `python runner.py --force-audio`).
Update `tests/test_audio_postprocess.py` if override expectations change.
