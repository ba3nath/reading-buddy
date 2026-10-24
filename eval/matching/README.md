# Matching benchmark (Phase 5a)

Frozen evaluation of Beginner / Strict **against labeled reading intent**.

- **Do not change matcher behavior to game this suite.** Phase 5a freezes a baseline; 5c may change matching only with an explicit FP/FN delta vs this baseline.
- Whisper confidence is an **indicator**, not a calibrated probability (`calibrated: false` in reports).

## Labels

| `reading_label` | Meaning |
| --- | --- |
| `reading_ok` | Child decoded the target (allow harmless formatting) |
| `reading_mistake` | Clear substitution / content error |
| `silence` | No speech / empty / forced silence path |
| `asr_uncertain` | Audio too weak for a reading verdict |

## Metrics

- **False accept (FP):** `reading_mistake` scored as `correct`
- **False reject (FN):** `reading_ok` scored as `missed`
- `close` and `retry` are tracked separately (soft / uncertain paths)

## Run

```bash
python scripts/eval_matching_benchmark.py
python scripts/eval_matching_benchmark.py --json eval/matching/reports/latest.json
pytest -q tests/test_matching_benchmark.py
```
