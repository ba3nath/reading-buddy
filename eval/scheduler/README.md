# Scheduler retention sim (Phase 6)

In-memory adaptive vs static review comparison. No Whisper / SQLite.

- **Static:** round-robin across items
- **Adaptive:** due-first Leitner gaps + weak-pattern prefer (mirrors `app/coach` + box gaps)

## Run

```bash
python3 scripts/eval_scheduler_sim.py
pytest -q tests/test_scheduler_sim.py
```

## Pass criteria

Adaptive must schedule **more hard-word reviews** than static on the fixed seed (hard `sh` items start weaker than easy `cvc-a`).
