# Engineering decisions log

Big departures from the playbook are listed in PLAN.md (C1–C10). Small engineering choices go here, newest last.

- 2026-11-09 Python 3.12 (playbook says 3.11; the reference repo works on both).
- 2026-11-09 Builders and tests use the offline `mock` LLM backend; the GLM key is spent only on demo runs.
- 2026-11-09 Duty vocabulary fixed in configs/duties.yaml (12 duties); unknown duties returned by a model are dropped and logged, not coerced.
