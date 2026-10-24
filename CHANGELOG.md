# Changelog

## 0.2.0 — family coach prep

Phases 4–8 of the coach/reliability roadmap (feature work; publish/tag separately):

- **Local-first defaults** — bind `127.0.0.1`; use `./run --lan` for Wi‑Fi tablets; model download/bootstrap hardening.
- **Attempt outcomes** — `outcome` / `assisted` / `mastery_eligible`; replay never inflates independent mastery.
- **Phonics map & spacing** — weak-skill review bias; one Leitner box advance per calendar day; scheduler retention sim.
- **Graduated hints** — miscue highlights + coach lines; post-hint success stays assisted; uncertain ≠ “wrong word”. (Sound/model audio steps still thin.)
- **Parent report** — independent vs assisted accuracy, retention-after-miss, five-minute tomorrow tip, export schema v2.

### Deferred (Phase 9)

Mini story coach packs / adventure themes: **later**. The existing Stories difficulty tier remains supported.

### Platforms

| Platform | Status |
| --- | --- |
| macOS + Python 3.11–3.13 | Primary |
| Windows 10/11 + Python 3.12 | Setup scripts documented; full smoke not signed off |
| Linux | Best-effort |

### Known limitations / open debt

- Whisper can mis-hear quiet or noisy rooms; uncertain retries are not reading failures.
- Default localhost bind: tablets need `./run --lan`.
- CSV zip is analytics only; restore progress with `./run --backup` / restore script.
- No cloud sync, multi-child accounts, or “reading age” score.
- Hint ladder levels 3–4 are mostly coach copy (`play_model` not wired to audio UI yet).
- Attempt rows still store legacy `result`; outcome flags live on the API + `events.meta_json`.
