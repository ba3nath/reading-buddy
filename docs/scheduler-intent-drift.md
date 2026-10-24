# Scheduler intent vs code (drift notes)

Written after the “every set starts with cat” bug. Intent is the product contract; tests in `tests/test_scheduler_set_intent.py` enforce it.

## Intent

| Rule | Why |
| --- | --- |
| Choosing **Set N** practises **Set N** | Child/parent set picker is the curriculum control |
| Mix: easy opener → due → this set → earlier review → closer | Spaced practice without abandoning the set |
| Pattern unlock (~80% known) gates **new ladder steps** | Progression safety |
| Rhymes/stories = one group per set | Do not mix poems or stories |

## Drift that shipped (and how tests catch it)

1. **Global easy opener** — `ORDER BY mastered, box, correct_count, id` with `pool_ids` including Set 1 always picked `cat`.  
   **Guard:** `test_each_words_set_opens_with_an_item_from_that_set`, `test_mastered_cat_does_not_hijack_later_set_opener`.

2. **Earlier due crowded the queue** — Set 1 `next_review_on <= today` filled length before Set N words.  
   **Guard:** `test_earlier_due_reviews_cannot_crowd_out_chosen_set`.

3. **Pattern unlock blocked the chosen set** — mastery unlock stuck on `cvc-a`+`sight`, so Set 6 digraphs were skipped and Set 1 CVC padded the session.  
   **Fix:** set pick opens that set’s patterns; mastery unlock only gates *earlier* review.  
   **Guard:** majority-from-set tests on a fresh profile.

4. **Weak stage test** — `test_queue_stays_inside_current_and_earlier_sets` only required `>= 1` overlap; would pass the cat bug. Tightened to opener-in-set + ≥4 from set + no later sets.

## Roles (unlock vs set-pick vs map)

| Layer | Owns | Does not |
| --- | --- | --- |
| **Pattern unlock (~80%)** | Which *new* ladder patterns may appear in earlier-review padding | Which set the child practises today |
| **Set picker** | Current-set membership for opener + primary fill | Long-term spacing intervals |
| **Leitner box / gaps** | When an item is due (`next_review_on`) | Order among due items |
| **Phonics map + plan** (`app/coach/`) | Order among due / earlier rows (weak skills first) | Leaving the chosen set; replacing Leitner |

Map bias stays inside `stage ∪ earlier` (same set-scoped rules as above).

## Remaining intentional tensions

- **Dual unlock models:** stage pick vs mastery ladder. Stage pick wins for the current set; ladder still matters for review padding and future auto-advance.
- **Closer slot:** last item may still be earlier review if the set is short; tests allow ≤1 Set‑1 item when Set 1 is all due.
- **Set 1 opener may still be `cat`** — that is correct when `cat` is in Set 1 and easiest there.
- **Same-day box guard:** at most one Leitner box advance per item per calendar day (correct_count still increments).

## Drift pass follow-ups (fixed)

- End-session mastered words use Leitner (`mastered` + `box` + `mastered_on`), not `correct_count = 3`.
- Scheduler padding prefers `stage ∪ earlier`; later sets only after the whole current set is queued (keeps 5|10 when sets are thin, e.g. phrases).
- Live queue always uses set-scoped scheduler (legacy path shadow-only).
- Garden end copy says “new {stage}” only when `stage_changed`.
- CSV export includes pattern/box/latency/events; README points to `./run --backup` for restore.
- Timings JSON rebuilds when the active wav mtime is newer than the cache.
