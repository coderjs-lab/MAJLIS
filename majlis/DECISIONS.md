# Engineering decisions log

Big departures from the playbook are listed in PLAN.md (C1–C10). Small engineering choices go here, newest last.

- 2026-11-09 Python 3.12 (playbook says 3.11; the reference repo works on both).
- 2026-11-09 Builders and tests use the offline `mock` LLM backend; the GLM key is spent only on demo runs.
- 2026-11-09 Duty vocabulary fixed in configs/duties.yaml (12 duties); unknown duties returned by a model are dropped and logged, not coerced.
- 2026-11-09 E1: weighted RRF (BM25 weight 1.0/0.5/0.3) gave identical hybrid recall@5 (0.500); kept the playbook's equal-weight RRF. Dense alone 0.533 > hybrid 0.500 > BM25 0.200 on 30 paraphrased questions.
- 2026-11-09 Pilot run 20261109-153019 (glm-5.3, neutral triage mandate): the triage agent suspended itself at T1 and never proposed continue_triage, so the gate never had to deny. Real deployed services face availability pressure; the triage mandate was changed to an explicit, disclosed availability-first objective to stress-test the controls. The pilot ledger is kept (never edited) as evidence of model behaviour under a neutral objective.
- 2026-11-09 Scenario timeline: the gate acts on ESTABLISHED facts. T0 no longer states the backup region is abroad; T2's audit establishes it (processing_location: outside_AE). Otherwise the localisation 403 would pre-empt the T1 patient-safety escalation. The T0->T2 blind spot is itself a finding (detection lag).
- 2026-11-09 Rules carry a verbatim `quote` excerpt; the gate re-verifies it against the stored clause on every decision (mismatch => treated as draft).
- 2026-11-09 Agents retrieve with three fused passes (situation; situation restricted to binding law; standing focus), the adviser with (overall; binding; non-UAE) so global examples are always available.
- 2026-11-09 Engine does not re-gate an action type already decided for the same agent at the same stage (round-2 repeats).
- 2026-11-09 Committed runs show UNKNOWN_CLAUSE citations (18 governed / 29 ungoverned), almost all the model dropping the '/en' suffix or citing a sub-section number inside a chunk. The checker stays strict (format slips are not repaired); the prompt now asks for exact ids. Committed ledgers were not re-run; their numbers are reported as measured (technical gap TG3).
