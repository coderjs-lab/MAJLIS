# MAJLIS — Multi-Agent Joint Legal & Institutional Simulation

**ITU AI for Good Lab Hackathon: United Arab Emirates (2026).**
**Team:** Harmanjot Singh · Abhra Dubey · Aya Elsayed

> **Fictional exercise.** The incident, the provider "OasisCare" and all telemetry are invented. The institutional agents simulate roles for training; nothing here is an official position of any UAE body or legal advice. Legal text comes only from official sources, quoted verbatim with a link.

When an AI system fails inside a public service, three questions decide the damage: **which rule applies, who must act, and by when**. Today nobody can answer them until the crisis is underway. MAJLIS rehearses the crisis first. A fictional AI triage service in a UAE telehealth platform fails in stages. Simulated regulators each see only part of the picture, consult the actual legal texts and coordinate. **Every claim is checked against the verbatim law. Every action passes a policy gate. Wherever the rules are silent, contradictory or leave nobody responsible, MAJLIS records a gap** — with a global example of how others handle it, or a plain "insufficient evidence".

A *majlis* is the traditional Gulf council where parties consult before a decision. That is what the agents do.

---

## 1. Quick look (no API key, ~3 minutes)

```bash
git clone <this repo> && cd ITUAIReadiness/majlis
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m uvicorn app.server:app --port 8765
# open http://127.0.0.1:8765 and pick a run from the run picker (replay mode)
```

The committed runs under `runs/` replay entirely from their ledgers: no model calls, no key. Verify any run's hash chain:

```bash
.venv/bin/python scripts/verify_ledger.py runs/<run_id>
```

## 2. What you are looking at

| Console view | What it shows | Judging criterion |
|---|---|---|
| Exercise | Stages T0–T5; who received what (information-asymmetry matrix); each agent's claims with citation status; proposed actions with gate stamps; expected vs actual | Agent capability, error scenarios |
| Policy gate | Every ALLOW / **DENY 403** / ESCALATE decision with the verbatim clause, issuer and link; human approvals | Auditability, governance |
| Gaps | Tier 1 machine-detected candidates (G1–G5) and Tier 2 team-verified gaps, each with evidence, readiness dimensions and a global example or INSUFFICIENT EVIDENCE | Gap identification |
| Audit trail | The hash-chained ledger; every prompt, retrieval, raw model output and decision; each row tagged with its ITU-T Y.3172 node | Auditability |
| Knowledge base | Hybrid search (BM25 + bge-m3) over clause-level official texts, Arabic beside English, retrieval evaluation | KB quality |
| Compare | Governed vs ungoverned run of the same scenario | Governance effect |
| Architecture | The Y.3172 pipeline with our proposed governance extension (LA, HA, AE, GM), live event counts per node | Alignment with ITU standards |
| Agents | Each agent's mandate, knowledge slice, tools and messaging rights; downloadable agent card | Reusability |

## 3. Results from the committed runs

All runs: scenario S1, model `glm-5.3` (z.ai), reasoning effort low, simulated approver `reject_all` unless noted, KB of 2,282 clauses. Every number below is printed by `scripts/report_tables.py` from the ledgers in `runs/`; nothing is hand-edited.

| Metric | governed · EN | ungoverned · EN | governed · AR | governed · EN · +C5,C3 |
|---|---|---|---|---|
| Ledger entries (hash chain) | 485 (OK) | 493 (OK) | 482 (OK) | 613 (OK) |
| LLM calls / errors | 62 / 0 | 62 / 0 | 62 / 0 | 80 / 0 |
| Citation verification rate | 92.4% | 89.0% | 93.9% | 90.1% |
| Gate: ALLOW / DENY 403 / ESCALATE | 19 / 0 / 2 | 17 / 1 / 7 | 20 / 0 / 2 | 20 / 0 / 2 |
| **Violations let through** (would DENY, executed) | **0** | **1** | 0 | 0 |
| **Escalations bypassed** (would ESCALATE, executed) | **0** | **7** | 0 | 0 |
| Human decisions: approved / rejected | 0 / 2 | 0 / 0 | 0 / 2 | 0 / 2 |
| Gap candidates G1/G2/G3/G4/G5 | 6/0/5/0/8 | 8/0/7/0/8 | 5/0/6/0/8 | 8/0/6/0/8 |

**What happened.** In the governed run the gate escalated `continue_triage` at T1 (DoH Responsible AI Standard §3.1.1.2.2, escalation protocols) and the human rejected it; the AI stayed on human fallback, so the T2 data-localisation breach never occurred. In the ungoverned run the same agent kept triaging and at T2 processed patient data outside the UAE: the gate's would-be **DENY 403** under Federal Law 2/2019 Art. 13 was logged and let through, together with 7 bypassed escalations. Governance here *prevented* the violation rather than blocking it after the fact.

**Citation integrity.** Of all citations the agents made, 89–94% were verbatim. Most failures are `UNKNOWN_CLAUSE`: the model dropped the `/en` suffix of a clause id or cited a sub-section number inside a larger chunk. The checker is deliberately strict and never repairs an id; such claims are never used as a legal basis (technical gap TG3).

**Retrieval (E1, 30 questions, 7 in Arabic, `kb/retrieval_eval.jsonl`):** recall@5 dense 0.53, hybrid 0.50, BM25 0.20 (article-level: 0.63 / 0.57 / 0.23). BM25 hurts on paraphrased questions; we report it rather than tune it. Questions are drafted from clause text and flagged for team review.

**Pilot.** Run `20261109-153019` used a neutral triage objective: glm-5.3 suspended itself at T1 and never tested the gate. Real services run under availability pressure, so the system under test now has a disclosed availability-first objective (`configs/agents/triage.yaml`). The pilot ledger is kept, unedited.

## 4. Architecture

```
            MLFO  (scenario engine: ML intent = scenario file + governance mode)
              |
 SRC --> C --> PP --> M ----------> P --------> D --> SINK
 injects  per-agent  clause      LLM agents   policy gate   blackboard   actions, human
 telemetry delivery  retrieval   (propose     + citation    routing      approver, gap
 legal texts         (hybrid)    JSON)        checker                    register
                                              |  proposed extension (not part of the standard):
                                              |  LA legal applicability · HA human approval
                                              |  AE audit evidence (hash chain) · GM gap miner
 all inside an ML sandbox (ITU-T Y.3181): simulated underlay, fictional scenario
```

**The LLM proposes, code decides.** Agents return schema-validated JSON (situation, claims with clause id + verbatim quote, proposed actions, requests to other agents, duties claimed/disclaimed, unanswerable questions). Plain Python then:

1. **Citation checker** — every quote must be a substring of the stored clause that was actually shown to the agent (VERIFIED), else NEAR_MATCH / FAILED / NOT_RETRIEVED / UNKNOWN_CLAUSE / UNSUPPORTED.
2. **Policy gate** — rules in `configs/policies/uae_rules.yaml`, each tied to a clause id; facts come from scenario state, never from the model. ALLOW (200), DENY (403 + clause), ESCALATE (202, human approval). No rule for a high-impact action → fail closed + `policy_void`.
3. **Gap miner** — G1 policy void, G2 conflict, G3 responsibility overlap/vacuum, G4 clock conflict, G5 standards gap (from our reading of Y.3172/Y.3173 in `configs/standards_coverage.yaml`).
4. **Audit ledger** — JSONL, `hash = sha256(prev_hash + canonical_json(entry))`; replayable; tamper-evident.

See `PLAN.md` for design decisions and `CONTRACTS.md` for module interfaces.

## 5. Full run (live agents)

```bash
cp .env.example .env            # add GLM_API_KEY (z.ai); MAJLIS_MODEL=glm-5.3
.venv/bin/pip install -r requirements-embed.txt      # optional: dense retrieval (bge-m3, ~2.3 GB)
.venv/bin/python scripts/build_kb.py --no-download   # rebuild clauses from kb/raw
.venv/bin/python scripts/build_index.py              # dense index (optional)
.venv/bin/python scripts/eval_retrieval.py           # recall@5 / MRR
.venv/bin/python scripts/run_scenario.py --scenario s1_failover --mode governed   --approver reject_all --backend glm
.venv/bin/python scripts/run_scenario.py --scenario s1_failover --mode ungoverned --approver reject_all --backend glm
.venv/bin/python scripts/run_scenario.py --scenario s1_failover --mode governed   --approver reject_all --backend glm --lang ar
```

A judge's own event, injected live (no code change):

```bash
.venv/bin/python scripts/run_scenario.py --scenario s1_failover --mode governed --backend glm \
  --inject "The overseas vendor requests raw logs for debugging." --recipients triage,data_office --after T3
```

Or use **New exercise** in the console (interactive approvals, challenge cards).

Offline smoke test of the whole pipeline (no key, deterministic mock agents): `MAJLIS_BACKEND=mock .venv/bin/python scripts/run_scenario.py --scenario s1_failover --mode governed`.
Tests: `.venv/bin/python -m pytest -q`.

## 6. Knowledge base

**2,282 clauses from 20 official documents** (UAE: Federal Law 2/2019 on ICT in health, Cabinet Resolution 40/2019 executive regulation, DoH Abu Dhabi Responsible AI and Data Governance standards, UAE AI Charter, National AI Strategy 2031; global: EU AI Act, GDPR, NIS2, NIST AI RMF 1.0, FDA PCCP guidance, IMDA agentic-AI and GenAI frameworks, WHO 2021 and 2024; ITU-T Y.3172, Y.3173, Y.3181, ITU AI Readiness Framework 2.0; Saudi NSDAI). `kb/sources/manifest.csv` (one row per document, official URL, sha256), `kb/clauses/clauses.jsonl` (one row per clause, text verbatim), `kb/Inputs.md` (reference-repo format; the originals are also copied into `simulation/server/knowledge/InputDocs/MAJLIS_UAE_Health_Telecom/` so the reference ingester can use them unchanged). `kb/sources/access_log.csv` records every download attempt — official portals that refuse automated retrieval are evidence for technical gap TG1.

## 7. Reuse: another country, another scenario

Agents, rules and scenarios are YAML. A new country pack = `configs/countries/<pack>.yaml` + `configs/agents/*` + `configs/policies/<pack>_rules.yaml` + documents in the manifest. A new scenario = one file in `configs/scenarios/`. No code changes.

## 8. Hardware and cost

Built and run on Ubuntu, 32 cores, 62 GB RAM, RTX 4090 (only used for embeddings: 2,282 clauses in 20 s; CPU works). Replay needs nothing but Python. A live S1 run makes 62 GLM calls (about 0.6 M prompt tokens, 80 k completion tokens) and takes about 8 minutes with agents of one round running in parallel.

## 9. Limitations (read this)

- Simulated and fictional; LLM output varies between runs (we report the committed ledgers).
- Policy rules are encoded by us from cited clauses; `review:` in each rule shows whether the team has signed it off. The gate is a *policy application component*, not a legal authority.
- Gap candidates are hypotheses until verified against the primary text (Tier 2). "Mapped to" Y.3172/Y.3173 — never "compliant with".
- Some official UAE texts could not be retrieved automatically; see `kb/sources/MANUAL_DOWNLOADS.md`.

## 10. Licence and attribution

Built on the ITU reference repository [CrashingGuru/ITUAIReadiness](https://github.com/CrashingGuru/ITUAIReadiness) (MIT; upstream `LICENSE` kept). Readiness dimensions and the causal graph are reused from it with attribution. Legal texts remain the property of their issuers and are linked to the originals.
