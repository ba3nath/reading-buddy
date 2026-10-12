# UX consistency

Gate agent for Reading Buddy. It judges one phase and does not change the app.

```bash
python3 check.py --phase 1
```

Phases: `1`, `2`, `fluency`, `3`, `4`. Exit 0 is a pass. Any listed failure fails the gate.
