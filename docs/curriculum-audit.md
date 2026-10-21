# Curriculum audit (Phase 0)

Snapshot of what Reading Buddy already had vs the learning roadmap, and gaps closed in Phases 0–3.

## What existed before Phase 0

| Area | Behaviour | Notes |
| --- | --- | --- |
| Queue | `build_adaptive_queue` — due reviews → unmastered → mastered refresh (~every 7 sessions) | 8 stages per difficulty; rhymes/stories use one group per set |
| Day ladder | Miss → +1 / +3 / +7 day `next_review_on` | Close does not move the ladder |
| Mastery | `correct_count >= 3` on ≥2 distinct calendar days | Separate from phonics patterns |
| `sound_tags` | CMU ARPAbet buckets (`th`, `r`, `s`, `sh`, `ch`) | Parent phoneme heatmap only — **not** a grapheme curriculum |
| Attempts | Result + `word_scores` in SQLite | No pattern, no latency |
| Listen audio | Whole-clip WAV under `audio/generated/` | Human override via `audio/human/{slug}.wav`; Phase 3 adds proportional `{slug}.json` timings + listen highlight |
| Export | Parent CSV zip | No restore path |

## Phase 0 additions

| Item | Location |
| --- | --- |
| Pattern catalog + unlock threshold | `content/patterns.json` |
| `pattern` + `sight_word` on every item | `content/items.json` (validated by `scripts/validate_patterns.py`) |
| Event log | `events` table via `app/events.py` |
| Latency | `attempts.latency_ms` + event `latency_ms`; client `client_latency_ms`; `GET /api/warmup` |
| Backup / restore | `scripts/backup_data.py`; `./run --backup` / `./run --restore PATH` |

## Known definition (unlock)

An item is **known** when `mastery.box >= 2` or `mastery.mastered = 1`. Pattern B unlocks when ≥80% of pattern A’s items are known (`unlocked_patterns` in `app/patterns.py`). Sight words are always available once any CVC step is open; they do not gate the ladder.

## Phase 1–3 (implemented on top of this audit)

1. Sets reordered along the phonics ladder (`scripts/reorder_by_pattern.py`).
2. Unlock filters new word/phrase picks when `scheduler_v2` is on.
3. Leitner boxes 1–5 wrap the old ladder; mastered = box ≥4 on separate days.
4. Read-along timings JSON + parent voice upload + effort stars for locking correct/close.
5. Stories rewritten so early-ladder audit is clean (`docs/story-decodability.md`); backup includes `audio/human/`.

## Still later (Phases 4–5)

Mini-rounds, story comprehension checks, fluency charts, weekly printable summary, parent custom word lists.
