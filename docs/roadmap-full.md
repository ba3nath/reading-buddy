# Reading Buddy — full roadmap (coach + reliability + release)

Living plan for the next product arc. Learning **Phases 0–3 are shipped** (patterns, events, Leitner, listen timings, set-scoped scheduler). This document defines **Phases 4–10**.

**North star:** A family can install without a developer; every attempt has an explicit outcome; ASR failure ≠ reading failure; rewards ≠ mastery; the app feels like one coherent reading coach.

**References (study, don’t vendor):**
- [phono-storyforge](https://github.com/tanner-griffith/phono-storyforge) — `alignment.py`, `mastery.py`, `planner.py`, `decodability.py`; closed loop evidence → skill → next activity; adaptive-vs-static eval.
- [adaptive-engine](https://github.com/Magenta91/adaptive-engine) — pure algorithm module, independently testable state updates; **do not** copy GRE IRT into early reading.

**Start-here map (existing tree):**

| Area | Start here |
| --- | --- |
| Speech scoring / matching | `app/matching.py` |
| API, session, persistence | `app/` |
| Adaptive practice / mastery | `app/adaptive.py`, `app/session.py`, `app/patterns.py` |
| Content | `content/items.json`, `content/patterns.json` |
| Speech / audio generation | `audio/`, `app/audio_files.py`, `app/whisper_engine.py` |
| Sound tagging | `scripts/tag_sounds.py` |
| Tests | `tests/` |
| Install / deps | `runner.py` |
| UI / parent | `static/` |
| Backup / restore | `scripts/backup_data.py` |

**Target invariants (must hold after the phase that remediates each debt):**
1. Rewards (stars, garden, effort stars) never determine mastery.
2. Uncertain / silence / assisted / replay / skipped attempts are not independent mastery.
3. Whisper confidence is an **indicator**, not a calibrated probability, unless a benchmark validates it.
4. Localhost is the safe default for network exposure; LAN is opt-in.
5. After each phase: run existing phase gates (`scripts/run_phase_gate.py`) **plus** the phase checklist below.
6. **Numbering:** Roadmap Phases **4–10** are this program. Legacy gate labels (`fluency`, old `4`) in `*/check.py` are separate; extend gates when implementing, do not conflate names.

**Current debt (code today — do not read invariants as already true):**
| Debt | Today | Fixed in |
| --- | --- | --- |
| Bind host | ~~Default `0.0.0.0`~~ → **done in 4a:** default `127.0.0.1`; `--lan` for Wi‑Fi | Phase 4a ✅ |
| Replay mastery | ~~Replay credits mastery~~ → **done in 5b:** stars only; `mastery_eligible=false` | Phase 5b ✅ |
| Model ready gate | ~~Kokoro only~~ → **done in 4b:** Kokoro + Whisper tree under `models/` | Phase 4b ✅ |
| Restore tests | ~~Backup only~~ → **done in 4a:** fresh restore + refuse without force + force overwrite | Phase 4a ✅ |
| Orphan `data/tmp` | ~~No startup sweep~~ → **done in 4b:** `sweep_temp_dir` on lifespan | Phase 4b ✅ |
| Atomic model download | ~~direct urlretrieve~~ → **done in 4b:** `.partial` then rename | Phase 4b ✅ |
| Outcomes | ~~legacy result only~~ → **done in 5b:** API `outcome` + flags; DB still stores legacy `result` | Phase 5b ✅ |
| Matching FP/FN baseline | ~~none~~ → **done in 5a:** `eval/matching/` + budgets (FN includes known strict plural) | Phase 5a ✅ |
| Offline env | `HF_HUB_OFFLINE=1` already set when serving | — (done) |

**Locked schema decisions:**
- **Outcome enum (five):** `correct` | `incorrect` | `uncertain` | `silence` | `skipped`.  
  Do **not** use `assisted` as an outcome value.
- **Flags:** `assisted: bool`, `mastery_eligible: bool`, `reason_code: str`, optional `hint_level: int`.  
  Assisted / prompted success = `outcome: "correct"` + `assisted: true` + `mastery_eligible: false`.  
  **`prompted` ⇔ `assisted: true`** (same concept; prefer `assisted` in API).
- **`attempt_class` (optional event meta, not a sixth outcome):** derive from flags — `independent` (correct ∧ ¬assisted ∧ ¬replay), `prompted` (assisted), `uncertain`, `silence`, `replay`, `skipped`. Do not invent a parallel persisted enum.
- **`mastery_eligible` ↔ existing `events.counts_for_mastery`:** dual-write / rename in Phase 5; one boolean meaning “counts as independent mastery evidence.”
- **Legacy attempt `result` today:** `correct` \| `close` \| `missed` \| `retry` \| `skipped` (plus rare event `shadow` for scheduler compare — not a child outcome).
- **`close` migration (single path):** Phase 5b keeps provisional non-locking second-chance (`reason_code=soft_mismatch`, not mastery-eligible). Phase 7 absorbs second-chance into the hint ladder and stops treating `close` as a separate policy. Do not map `close`→locking `incorrect` in 5b.
- **Benchmark before behavior change:** Phase 5a freezes fixtures against *current* Beginner/Strict; 5b adds outcome fields; 5c may change matching only with FP/FN delta reported.

---

## Requirements coverage (traceability)

| Requirement (from planning) | Phase(s) | Notes |
| --- | --- | --- |
| Speech ≠ reading assessment; FP/FN per mode | 5, eval | Benchmark + README honesty |
| Confidence-aware ASR; unclear → try again, not fail | 5, 7 | `uncertain`/`silence`; hint before fail |
| Adaptive evidence; hard-word retention; no inflated mastery | 5–6, 8 | Replay/assisted blocked; retention metric |
| Local-first / offline after assets; privacy | 4, 10 | Offline smoke; retention docs |
| Bootstrap / recovery / atomic models / ports | 4 | Runner tests |
| Family install without developer; release matrix | 4, 10 | Docs + GitHub release |
| Mistake-aware coach + graduated hints | 7 | Align + hint ladder |
| Personal word/phonics map; skills drive next activity | 6 | Tags + planner |
| Story mode 3–5 sentences, reuse known words | 9 | Curated packs; no LLM v1 |
| Parent: independent / hard sounds / month trend / 5‑min tomorrow | 8 | |
| Spaced repetition playable | 6 | Leitner gaps + planner order |
| Child-controlled adventures | 9 | Optional skins over planner |
| Session recovery no duplicate attempts/rewards | 4 partial, **7** full | Slot locks + refresh tests in 7; API interrupted session in 4 |
| Study phono-storyforge / adaptive-engine | **4.0 spike** | Notes only; no vendor |
| Mini-rounds | **post-10** | Not in Phase 9 scope; do not pretend ownership |
| Weekly printable / fluency charts | **post-10** (optional thin week strip in 8 only) | Phase 8 may show a simple “this week” line; full printable + fluency charts deferred |
| Parent custom word lists | **post-10** | Explicitly deferred |
| Dep pin / lockfile | **4** contracts; lockfile **10** if needed | Range pins + `test_dependencies` in 4; lockfile only if OS drift |
| Recording / kept-clip consent UX | **8** + **10** verify | Parent copy + settings; distinct from research consent for child testing |
| Real-child audio corpus | Optional parallel | Not a gate for 5–8 |
| Gate agents for new phases | Each phase | Update `test-coverage`/`drift-review` markers when shipping |

**Intentionally deferred / non-goals:** research ASR swap; StoryForge cloud/LLM books; GRE IRT θ; reading-age hero score; multi-child cloud sync; mini-rounds; full weekly printable; fluency charts; custom word lists (until post-10).

---

## Per-phase review checklist (required)

Every phase ends with a written pass on:

| Lens | Questions |
| --- | --- |
| **Drift** | Intent in this doc / README / parent copy vs code? Any string-only gate that would miss a regression? Update `docs/scheduler-intent-drift.md` or this file. |
| **Interfaces** | API JSON, settings keys, UI `data-state` / copy contracts stable or versioned? Client and server agree? |
| **Code** | Modules touched; pure vs I/O boundary (prefer `app/coach/*` pure like adaptive-engine `algorithm/`)? Dead paths removed or fenced? |
| **Data models** | SQLite columns/tables, events fields, content JSON schema, settings defaults migrated safely? |
| **Guardrails** | Failure modes: missing models, bad upload, uncertain ASR, restore without force, nonlocal bind, mastery inflation? |
| **Tests** | Unit + integration listed below green; gates green; no silent skip of AC. |

---

## Phase map overview

| Phase | Name | Track | Primary DoD |
| --- | --- | --- | --- |
| **4.0** | Reference spike (optional, ≤1 day) | Study | Adopt/adapt/ignore notes from StoryForge + adaptive-engine |
| **4** | Family install & reliability | R + Release prep | Clean install, recover, trust data location |
| **5** | Speech outcomes & benchmark | S | Explicit outcomes; ASR ≠ reading fail; FP/FN baseline |
| **6** | Phonics map & mastery evidence | C core | Tags + independent/prompted/uncertain stored apart |
| **7** | Coach hints & child UX | C coach | Graduated hints; clear session states; full session recovery |
| **8** | Parent report & tomorrow practice | C parent | Answers real parent questions |
| **9** | Story mode & adventures | C distinctive | Decodable mini-stories; optional theme skins |
| **10** | Family release | Release | Versioned GitHub release, matrix, known limits |

**Dependencies:** **4 ∥ 5**. **6+** need Phase **5** outcome contract (+ replay/`mastery_eligible`). **7** needs **5**; soft-depends on **6** (can ship with item `pattern` if 6 slips). **8** needs **5–6** (hints from **7** improve assisted/prompted reporting). **9** needs **6**. **10** needs **4** + no P0 from **5–8**. **9 is not on the critical path to release.**

```text
4.0 Study (optional)
4 Reliability ──┐
5 Outcomes ─────┼─→ 6 Map/mastery ─┬→ 7 Hints/UI → 8 Parent ──→ 10 Release
                │                  │
                │                  └→ 9 Stories/adventures (optional side branch)
                └─→ (gates + drift review after each)
```

“Stories tier as today” at release (if 9 deferred) = existing difficulty-4 set picker + one story group per set (`docs/story-decodability.md`), **not** Phase 9 mini-packs.

---

## Phase 4.0 — Reference spike (optional)

**Deliverable:** `docs/reference-phono-storyforge.md` + short adaptive-engine note: adopt / adapt / ignore per module. No runtime dependency. Feeds Phase 6–7 design.

### Checklist

| Lens | Pass criteria |
| --- | --- |
| Drift | Notes cite concrete functions, not vibes |
| Interfaces | N/A |
| Code | No code merged except docs |
| Data models | N/A |
| Guardrails | Apache-2.0 / license awareness if copying snippets later |
| Tests | N/A |

---

## Phase 4 — Family install & reliability

**Objective:** A family can install on a supported computer without developer access. Happy path and common failures work without manual DB repair or undocumented commands.

### Scope

| Task | Files | Acceptance |
| --- | --- | --- |
| Establish baseline | `tests/`, `runner.py`, docs | Clean checkout tests run; known failures recorded |
| Harden startup | `runner.py`, `scripts/download_models.py` | Missing deps/models → actionable errors; interrupted setup retryable |
| Network exposure | `runner.py`, `README.md` | **Localhost default**; LAN explicitly opt-in and documented |
| Audio lifecycle | `app/audio_files.py`, `app/main.py` | Temps cleaned on success, failure, restart (orphan sweep) |
| API failures | `app/main.py`, `app/session.py` | Missing input / bad session / unavailable model / audio fail → controlled errors |
| Backup / restore | `scripts/backup_data.py` | Restore into fresh data dir without corruption |
| Privacy docs | `README.md` | Retention/deletion match behavior (tmp, kept, human, DB) |
| User docs | `README.md`, install docs | Prerequisites, setup, first session, troubleshooting, uninstall, data location |
| Dep contracts | `requirements.txt`, `tests/test_dependencies.py` | Keep/strengthen upper-bound contracts; lockfile only if forced |

### Code / data (residual — not already done)

- Change default bind to `127.0.0.1`; add `--lan` (or equivalent); keep `--localhost-only` as alias.
- Atomic model downloads; `models_ready()` includes Whisper **and** Kokoro (today: Kokoro only).
- Lifespan/startup: sweep `data/tmp` orphans.
- No schema change required unless restore stamps need versioning.
- **Already done:** `HF_HUB_OFFLINE=1` on serve paths — do not re-list as remaining work.

### Guardrails

- Restore without `--force` refuses when DB exists (code exists; **add tests**).
- Partial model files never count as ready.

### Tests to add

- `tests/test_runner.py`: missing model, interrupted setup, occupied port, invalid configuration.
- Audio lifecycle: empty audio, transcription exception, cleanup after failure (cancellation = no server file).
- API: invalid payloads, nonexistent session, interrupted session.
- Backup/restore integration on temporary database + fresh dir.
- Offline smoke after assets present (health `offline`, score with double or local model).

### Phase 4 checklist

| Lens | Pass criteria |
| --- | --- |
| Drift | README LAN/localhost and backup-vs-CSV match runner; curriculum-audit export note still true |
| Interfaces | `/api/health` fields stable; error JSON `{error,message}` consistent |
| Code | `runner.py` recovery paths; no silent `pass` on model failure |
| Data models | Backup zip contents documented; restore idempotent with force |
| Guardrails | Localhost default; force-restore; tmp sweep |
| Tests | Suite above green on macOS CI path; Windows noted in matrix if not automated |

---

## Phase 5 — Speech outcomes & benchmark

**Objective:** The app responds appropriately when the child reads correctly, mistakes, stays silent, or produces audio the model cannot confidently interpret. **Speech-recognition failure does not automatically become a reading failure.**

### Suggested result contract (new; migrate from today’s `result`)

```json
{
  "outcome": "uncertain",
  "target": "ship",
  "transcript": "chip",
  "assisted": false,
  "mastery_eligible": false,
  "reason_code": "low_asr_confidence",
  "confidence": { "mean": 0.12, "min": 0.04, "calibrated": false }
}
```

| `outcome` | Meaning | Typical `mastery_eligible` |
| --- | --- | --- |
| `correct` | Read accepted | `true` iff `assisted=false` and not replay |
| `incorrect` | Clear reading miss / soft mismatch locking | `false` |
| `uncertain` | ASR fog / ambiguous audio | `false` |
| `silence` | No speech / empty / RMS gate | `false` |
| `skipped` | Gave up after max retries | `false` |

**Flags (not outcomes):** `assisted`, `mastery_eligible`, `reason_code`, `hint_level` (Phase 7).  
**Legacy dual-write:** keep `result` during transition. Map: `missed`→`incorrect`; `retry`→`silence`|`uncertain`; `close`→provisional non-locking (`soft_mismatch`) until Phase 7; `skipped`→`skipped`; `correct`→`correct`.

### Sub-sequence (required order inside Phase 5)

| Step | Work | Rule |
| --- | --- | --- |
| **5a** | `eval/matching/` fixtures + report on **current** matcher | Baseline before behavior change |
| **5b** | Emit `outcome` / flags; map silence≠uncertain; UI copy | Contract only |
| **5c** | Matching/normalization tweaks | Only with FP/FN delta vs 5a |

### Scope

| Task | Files | Acceptance |
| --- | --- | --- |
| Define outcomes | `app/matching.py`, `app/session.py` | Five outcomes + flags distinct |
| Normalization | `app/matching.py` | Punctuation / harmless formatting ≠ false fail |
| Evaluation fixtures | `tests/`, `eval/matching/` (new) | Labeled pairs → expected outcomes |
| Standardize feedback | API + `static/js/game.js` | Child-friendly copy per outcome |
| Separate rewards from mastery | `app/session.py`, `app/adaptive.py` | Uncertain/assisted/replay/skipped never independent mastery |
| Passage attempts | `app/main.py` `_post_passage` | Same outcome contract on read-through |

### Code / data

- Extend `MatchResult` / attempt payload with `outcome`, `assisted`, `mastery_eligible`, `reason_code`.
- Split today’s catch-all `retry` into `silence` vs `uncertain` where detectable.
- Replay correct: **do not** call `credit_mastery_correct`; `mastery_eligible=false`.
- Close-again / miss-again paths: set `assisted` or non-eligible until Phase 7 renames to hint levels.
- Events: store outcome + mastery_eligible + attempt_class (`independent`\|`prompted`\|`uncertain`\|`replay`\|`silence`).
- Migration: additive columns preferred; dual-write `result`↔`outcome` until Phase 8 export cutover.

### Guardrails

- Low token conf / no_speech → uncertain or silence, not `incorrect`.
- Confidence fields marked `calibrated: false` until benchmark says otherwise.
- Beginner/Strict both emit the same outcome enum.

### Tests to add

- Unit: matching, tokenization, normalization.
- Table-driven: correct, substituted, omitted, extra words.
- Silence ≠ uncertain.
- Repeated attempts + assisted success regression.
- Benchmark report: false reject / false accept by mode (`scripts/eval_matching_benchmark.py`).

### Phase 5 checklist

| Lens | Pass criteria |
| --- | --- |
| Drift | README “Beginner/Strict” updated; no claim that Whisper = reading ability |
| Interfaces | Attempt API documents outcome contract; UI handles all outcomes |
| Code | Single scorer path; silence/uncertain branched before miss |
| Data models | attempts/events columns or JSON fields for outcome + eligibility |
| Guardrails | mastery_eligible false for uncertain/assisted/replay/skipped; rewards may still award stars |
| Tests | 5a baseline checked in before 5c; CI fails on FP/FN regression past thresholds; silence≠uncertain |

---

## Phase 6 — Phonics map & mastery evidence

**Objective:** Personal word/phonics map drives practice; spaced repetition is deterministic and testable; independent vs assisted (`assisted=true`) vs uncertain evidence are stored separately (not as extra outcomes).

### Scope

| Task | Files | Acceptance |
| --- | --- | --- |
| Phonics metadata | `content/items.json`, `scripts/tag_sounds.py`, validators | Every item linked to learning objectives / skills |
| Explicit mastery tracking | `app/events.py`, `app/adaptive.py`, optional `app/coach/map.py` | Independent / prompted / uncertain separate |
| Spaced repetition | Scheduler under `app/` (refine `adaptive.py` or `app/coach/plan.py`) | Difficult words return after configurable gaps |
| Deterministic planner | Pure functions + SQLite apply | Map + Leitner choose next activity, not ladder alone |

### Borrow from references

- StoryForge: grapheme/skill evidence update; `select_objective`-style ZPD + review; decodability decompose for tags.
- adaptive-engine: pure update/select functions, no I/O in algorithm core.

### Code / data

- Content: skill tags (e.g. `sh`, `cvc-a`, blend) validated in CI; keep existing `pattern` / `sight_word`.
- Optional `skill_state` table or derived views from events.
- Leitner gaps remain source of truth for intervals; planner only **orders** due vs new vs weak-skill drills.
- Same-day spam: at most one box advance per item per calendar day.

### Guardrails

- Prompted/uncertain/assisted/replay never increment independent mastery counters (Phase 5 flags; Phase 7 fills `assisted` via hints).
- Set picker still respected (set-scoped opener); map fills within set ∪ earlier ∪ last-resort later only when set exhausted (existing intent in `docs/scheduler-intent-drift.md`).
- Do **not** replace Leitner with BKT in v1; optional later if sims require it (StoryForge reference only).

### Tests to add

- Schema validation for content metadata.
- Deterministic mastery updates and activity selection.
- Retention: missed item returns on schedule; independent success after delay counted.
- Adaptive-vs-static sim under `eval/scheduler/` proving hard-word reviews (required for Phase 6 DoD, not optional).

### Phase 6 checklist

| Lens | Pass criteria |
| --- | --- |
| Drift | Unlock (~80%) vs set-pick vs map planner roles documented |
| Interfaces | Settings/API for unlocked patterns unchanged or migrated |
| Code | `app/coach/map.py` + `plan.py` pure; session only persists |
| Data models | Events carry skill ids; migrations backward compatible |
| Guardrails | No mastery from assisted; replay blocked |
| Tests | Selection golden tests; content validator in CI |

---

## Phase 7 — Graduated hints & child UX

**Objective:** Mistake-aware coach: identify likely difficulty, offer gentle next step; distinguish reading mistake from ASR uncertainty; coherent session states.

**Depends on:** Phase 5 outcomes. **Prefer** Phase 6 skill tags for highlight targets; fallback to item `pattern` / simple grapheme heuristics if 6 incomplete.

### Hint ladder

1. Replay listen (retry)
2. Highlight difficult pattern (`sh` in *ship*)
3. Play sound / first syllable
4. Model word → invite child to read

Hesitation / uncertain → offer hint **before** recording a reading failure (`incorrect`).

### Scope

| Task | Files | Acceptance |
| --- | --- | --- |
| Miscue align | `app/coach/align.py` (new) | cat→cap highlights ending; ship miss → sh practice cue |
| Graduated hints | `app/session.py`, `app/coach/hints.py`, `static/` | Progress retry → targeted → model; hints logged separately from independent success |
| Child UI states | `static/js/game.js`, CSS/HTML | listening, recording, processing, retry, hint, complete |
| Session recovery | `app/session.py` | Refresh/restart does not duplicate attempts or rewards (full AC; Phase 4 only covers API error paths) |
| Retire parallel close/miss again | `app/session.py` | Second-chance flows are hint steps, not a second policy |

### Code / data

- Attempt rows / events: `hint_level`, `miscue_tags`, `assisted=true` on post-hint correct.
- API returns coach line + optional highlight spans; `outcome` stays from Phase 5 enum.
- Close/miss second-take becomes steps inside the ladder, not a parallel system.

### Guardrails

- Success after hint → `assisted` / not independent mastery.
- Uncertain path never shows “wrong word” copy.
- Slot lock: one locking credit per planned slot.

### Tests to add

- Hints do not count as independent success.
- UI/API: load, record failure, retry, hint, complete.
- Session recovery / no duplicate attempts after refresh.
- Align unit tests for onset/coda/digraph miscues.

### Phase 7 checklist

| Lens | Pass criteria |
| --- | --- |
| Drift | Child copy never equates ASR miss with “you can’t read” |
| Interfaces | New fields optional for old clients; states documented |
| Code | Hint state machine single place |
| Data models | hint_level on events/attempts |
| Guardrails | assisted ≠ mastery_eligible; duplicate slot blocked |
| Tests | Recovery + hint eligibility green |

---

## Phase 8 — Parent report

**Objective:** Answer questions parents actually ask—trends and examples, not one opaque score.

### Parent questions → surfaces

| Question | Source |
| --- | --- |
| Which words independently? | Independent corrects / mastered with eligibility |
| Which sounds still hard? | Miscue → skill rollup + pattern heatmap |
| Accuracy improving (~month)? | First-pass independent accuracy by day |
| Five minutes tomorrow? | Planner tip: due reviews + weakest skills |

### Scope

| Task | Files | Acceptance |
| --- | --- | --- |
| Reporting API | `app/parent.py` | Distinguishes independent, prompted, retention |
| Parent UI | `static/parent.html`, `static/js/parent.js` | Trends, difficult patterns, next practice |
| Export | CSV zip | Columns/outcomes aligned with new model; README still points restore to `./run --backup` |
| Thin “this week” strip (optional) | Parent UI | One-line summary only; **full weekly printable = post-10** |
| Kept-clip / recording consent copy | Parent settings + README | Clear what is stored when keep-audio is on |

### Guardrails

- No single “reading age” score as the hero metric.
- Stars/garden/minutes not presented as mastery proof; lead with independent accuracy + retention.
- Fluency charts / WPM dashboards = **post-10** (do not invent from raw `latency_ms` without validation).

### Tests to add

- API fixtures for independent vs assisted aggregates.
- Export includes outcome / eligibility fields where applicable.
- Tomorrow tip deterministic given fixed DB.
- Retention-after-delay aggregate when Phase 6 data exists.

### Phase 8 checklist

| Lens | Pass criteria |
| --- | --- |
| Drift | Parent copy matches definitions in Phase 5–6 |
| Interfaces | `/api/parent/*` documented; backward compatible where possible |
| Code | Aggregations from events, not re-inferred from stars |
| Data models | Export schema version note in README.txt inside zip |
| Guardrails | Privacy: no unexpected upload; kept clips opt-in |
| Tests | Parent API + export tests green |

---

## Phase 9 — Story mode & child-controlled adventures

**Objective:** Tiny meaningful stories (3–5 sentences + illustrations); reuse recently independent words; optional adventure themes that still target phonics.

### Scope

| Task | Files | Acceptance |
| --- | --- | --- |
| Mini-stories | `content/` (+ illustrations), Stories UI in `static/` | Decodable; reuse map-known words; target ≤1–2 new pattern words |
| Decodability check | validator inspired by StoryForge `check_decodability` | CI rejects out-of-scope words for pack level |
| Adventures (optional) | Theme → skill objective mapping | Beach→`sh`, etc., without abandoning deliberate practice |

### Guardrails

- No cloud LLM story generation in v1 (local-first).
- Adventure is a skin over planner objectives, not a separate curriculum fork.

### Tests to add

- Decodability validator on all mini-story packs.
- Session through one mini-story: sentence listen → read → next.
- Adventure selection only queues items for mapped skills.

### Phase 9 checklist

| Lens | Pass criteria |
| --- | --- |
| Drift | Story mode vs existing Stories tier relationship documented |
| Interfaces | Same attempt outcome contract |
| Code | Reuse coach/plan; no second matching stack |
| Data models | story pack schema in content/ |
| Guardrails | Decodability gate in CI |
| Tests | Pack validation + one E2E story path |

---

## Phase 10 — Family release

**Objective:** Repeatable installation, documented support boundary, no known release-blocking defects, reproducible release procedure.

**Entry criteria:** Phase **4** complete; Phases **5–8** have no open P0 (data loss, mastery corruption, ASR→false reading fail, broken restore). Phase **9** optional — if deferred, changelog lists “mini story coach packs: later” and existing Stories tier remains supported.

### Scope

| Task | Files | Acceptance |
| --- | --- | --- |
| Clean-machine testing | `runner.py`, deps, docs | Setup from clean checkout on every **declared** supported platform |
| Full regression | `tests/` | Unit, integration, E2E smoke pass |
| Privacy verification | audio pipeline, persistence, docs | Retention/deletion match docs |
| Verify restore | `scripts/backup_data.py` | Real backup → fresh install |
| User documentation | `README.md`, install docs | Prerequisites, setup, first session, troubleshooting, uninstall, data location (finalize Phase 4 drafts) |
| Publish release | GitHub release, `pyproject.toml` version | Changelog, platform matrix, known limitations |
| Optional lockfile | `uv.lock` / pip-tools | Only if multi-OS install drift justifies |

### Supported platform matrix (declare explicitly in release)

| Platform | Status |
| --- | --- |
| macOS + Python 3.11–3.13 | Primary |
| Windows 10/11 + Python 3.12 | Supported if smoke documented |
| Linux | Best-effort unless tested |

### Tests / evidence

- E2E smoke: install → launch → session → result → restart → progress retained.
- Offline session after assets downloaded.
- Backup/restore round-trip.
- Dependency/startup checks per OS (CI + manual checklist).
- Manual usability with a first-time parent (**research consent** if any child is observed — distinct from in-app recording consent UX in Phase 8).
- Verify privacy/consent copy matches keep-audio / tmp / backup behavior.

### Phase 10 checklist

| Lens | Pass criteria |
| --- | --- |
| Drift | Known limitations match real behavior (Whisper noise, LAN flag, replay fixed, etc.) |
| Interfaces | Version exposed in `/api/health` or about string |
| Code | Tagged commit; no debug flags on by default |
| Data models | Migration from 0.1.0 → release version tested |
| Guardrails | No open P0 on data loss / mastery corruption / ASR→false fail; privacy copy verified |
| Tests | Full suite green; smoke checklist signed off |

---

## Cross-cutting evaluation (runs alongside 5–8)

| Eval | When | Output |
| --- | --- | --- |
| Matching FP/FN benchmark | Phase 5, then every matching change | `eval/matching/` report |
| Adaptive vs static retention sim | Phase 6+ | `eval/scheduler/` (StoryForge pattern) |
| Delayed retention metric | Phase 6–8 | Parent + export |
| Real-child audio corpus | Parallel, optional | Private/LFS; not required to unblock 5 |

---

## Explicit non-goals

- Replacing Whisper with research reading-assessment ASR before Phase 5 contract + benchmark.
- Porting StoryForge ADK / Gemini book factory / cloud Docs.
- Porting GRE IRT ability θ as the child’s model.
- One opaque “reading age” hero score.
- Cloud sync / multi-child accounts in this arc.
- Treating Phase 9 adventures as required for first family release.

---

## Consistency risks (watch during implementation)

| Risk | Mitigation |
| --- | --- |
| Dual `result` vs `outcome` forever | Dual-write in 5; export cutover in 8; delete deprecated field post-10 if unused |
| `counts_for_mastery` vs `mastery_eligible` | One meaning; dual-write then rename |
| Gate phase name collision (`4` vs roadmap 4) | Use roadmap ids in PR titles; extend `check.py` with `4r`/`5s`/… or string markers |
| Hints before map tags | Phase 7 fallback to `pattern` field |
| Stars still feel like mastery | Phase 8 UI copy + Phase 5 eligibility flags |
| Localhost default breaks Wi‑Fi tablet use | README + `--lan`; Phase 10 known limitation |
| Benchmark games matching into “always pass” | Thresholds + separate FP and FN budgets per mode |
| Session recovery split across 4 and 7 | 4 = API errors; 7 = refresh/duplicate slot AC |
| Fake ownership of post-10 features | Mini-rounds / full printable / fluency / custom lists stay post-10 |

---

## PR / issue hygiene

Create **separate reviewable PRs** per phase slice (or sub-slice in the phase tables). Each PR description links:
- Phase number + checklist lenses
- Interface/schema changes
- Test plan
- Drift notes updated (`docs/scheduler-intent-drift.md` and/or this file)

Suggested first PRs:
1. **Phase 4a** — localhost default + API/restore/audio tests  
2. **Phase 4b** — atomic models + `models_ready` + tmp sweep  
3. **Phase 5a** — matching benchmark fixtures/report on **current** behavior (no matcher change)  
4. **Phase 5b** — outcome contract + silence≠uncertain + mastery_eligible on replay  

---

## Definition of done (program)

- **Reliability:** Repeatable install; documented support boundary; backup/restore verified; temps and privacy match docs.
- **Scoring:** Every attempt has an explicit outcome; ASR failure ≠ reading failure; FP/FN known.
- **Coach:** Parent understands what was practiced and what to do next; child recovers from mistakes without confusing or discouraging feedback.
- **Release:** Versioned GitHub release, changelog, platform matrix, known limitations; no release-blocking defects.

---

## Changelog for this document

| Date | Note |
| --- | --- |
| 2026-10-24 | Initial full plan: Phases 4–10, per-phase drift/interfaces/code/data/guardrails/tests |
| 2026-10-24 | Consistency pass: locked outcome enum vs assisted flag; 5a→5c order; coverage matrix; 4.0 spike; Phase 9 optional for release; close/skipped/passage/recovery clarified |
| 2026-10-24 | Independent recheck: target vs current debt table; close single-path; prompted⇔assisted; diagram 9 off critical path; post-10 deferrals honest; HF offline marked done; consent UX vs research consent |
| 2026-10-24 | Phase 4a started: localhost default + `--lan`; restore/API/audio cleanup tests |
| 2026-10-24 | Phase 4b: Whisper in `models_ready`, atomic Kokoro download, tmp sweep on startup |
| 2026-10-24 | Phase 5a: matching benchmark cases + FP/FN budgets (no matcher behavior change) |
| 2026-10-24 | Phase 5b: outcome contract (silence≠uncertain), mastery_eligible, replay no longer credits mastery |
