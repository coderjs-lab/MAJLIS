# MAJLIS: implementation plan (build of 9–10 Nov 2026)

Source of truth: the MAJLIS playbook (Abhra) + the organisers' meeting summary + the official event page.
This file records how we build it, and every place we deliberately depart from the playbook to raise our odds.

## What we are building (5 lines)
1. **A clause-level UAE + global legal knowledge base** (official texts only, Arabic + English where available), hybrid-searchable, packaged in the ITU reference repo's `InputDocs` format, with a measured recall@5.
2. **A staged, multi-institution AI-incident exercise**: a fictional AI triage service (system under test) fails across five stages; simulated DoH, TDRA and Data Office agents and a Legal & Policy Adviser each see only their own injects and coordinate over a typed blackboard.
3. **A deterministic trust layer**: verbatim citation checker, policy-as-code gate (ALLOW / 403 DENY / ESCALATE to a human), gap miner (G1–G5), SHA-256 hash-chained audit ledger with replay. The LLM proposes, code decides.
4. **An exercise console** (web app) that tells the story stage by stage: who knew what, what each agent claimed and whether the law actually says it, what the gate did, governed vs ungoverned, the gap register, the audit trail mapped onto the ITU-T Y.3172 pipeline.
5. **Reproducibility**: committed demo ledgers replay with no API key; one command runs a live exercise.

**Layer 1 done when:** one command produces a governed and an ungoverned S1 ledger; a DENY 403 card shows a real clause; `verify_ledger` prints OK; the console replays a run from a clean venv.

## Changes vs the playbook (DECISION, to maximise judging score)
| # | Change | Why it helps us win |
|---|---|---|
| C1 | **LLM = GLM (z.ai, OpenAI-compatible)** instead of the Anthropic SDK; `glm-5.3` for demo runs, `glm-5.3-flash` for cheap runs, plus an offline `mock` backend. Schema-validated JSON + one repair retry. | Uses the key we have; mock backend makes the whole pipeline testable and reproducible without any key. |
| C2 | **Custom web console (FastAPI + hand-built UI)** instead of Streamlit. Live run streaming, approve/reject queue, judge inject box, split governed/ungoverned view, proper Arabic RTL rendering. | Round 2 is a table-side live demo; Streamlit looks generic. A purpose-built console reads as a product, not a notebook. |
| C3 | **Y.3172 lens on every log line**: each ledger event is tagged with its Y.3172 node (SRC, C, PP, M, P, D, SINK, MLFO) and the console draws the pipeline lighting up as the run proceeds. | Turns the "Alignment with ITU standards" criterion from a table in the report into something judges see working. |
| C4 | **Information-asymmetry matrix**: a stage × agent grid showing who received which inject and when. | Makes the brief's "information released in chunks, unevenly" requirement visible in one glance. |
| C5 | **Auto-generated After-Action Report (AAR)** per run (Markdown, from the ledger only, no LLM). | Real exercise practice (tabletop exercises end in an AAR); gives Abhra report-ready tables. |
| C6 | **Agent cards (JSON)** exported from the agent YAMLs. | Plugs straight into ITU/TDRA's *Global Open Repository of AI Agents and metadata*; cheap proof of reuse. |
| C7 | **Source-access log as evidence**: every document we tried to fetch is recorded with its result; official portals that block automated retrieval become evidence for technical gap TG1 (no machine-readable official UAE legal corpus). | Turns a blocker into an evidence-backed gap. |
| C8 | **The build sources the KB itself** (official sources only: EU Cellar API, ITU, NIST, IMDA, DoH, MOHAP, WHO, reference repo), and lists the documents that need a manual browser download. Retrieval test set is drafted from real clause text and flagged `needs_team_review`. | Removes the biggest schedule risk (waiting on documents) without bending the "official sources only" rule. |
| C9 | **numpy dense index + BM25 + RRF** instead of ChromaDB at runtime; Chroma/InputDocs export for ITU compatibility. | Fewer moving parts for judges reproducing it; GPU here, CPU fine elsewhere. |
| C10 | Rules carry `status` (draft/verified) **and** `review` (who checked the clause). The build verifies each rule's clause against the stored text; Abhra signs off. | Keeps the 403 demo honest and auditable. |

Unchanged from the playbook: the five override rules, the S1 scenario and cast, the gate algorithm, G1–G5, the two-tier gap register, the experiments E1–E6, the report blueprint, the README checklist.

## Repository layout
```
ITUAIReadiness/            # clone of CrashingGuru/ITUAIReadiness (MIT), branch `majlis`
  simulation/              # upstream, untouched (dimensions.json, causal_graph.py, InputDocs)
  majlis/
    PLAN.md CONTRACTS.md DECISIONS.md README.md requirements*.txt .env.example
    configs/  agents/ policies/ scenarios/ countries/ duties.yaml standards_coverage.yaml
    kb/       sources/manifest.csv sources/access_log.csv raw/ clauses/clauses.jsonl index/ Inputs.md retrieval_eval.jsonl
    majlis/   schemas.py ledger.py retrieval.py citation_check.py policy_gate.py gap_miner.py
              metrics.py aar.py llm.py agents.py engine.py readiness.py
    scripts/  build_kb.py build_index.py eval_retrieval.py run_scenario.py verify_ledger.py export_agent_cards.py
    app/      server.py static/ (console)
    runs/     committed demo ledgers (replayable)
    tests/
```

## Build waves
Built by parallel Claude subagents against `CONTRACTS.md`; integration, review and live runs by the lead.

| Wave | Workstream | Output |
|---|---|---|
| 1 | KB sourcing + clause extraction | `kb/raw`, `manifest.csv`, `access_log.csv`, `clauses.jsonl`, `Inputs.md`, InputDocs copy, manual-download list |
| 1 | Retrieval | `retrieval.py`, `build_index.py` (bge-m3), `eval_retrieval.py`, tests |
| 1 | Deterministic core | `ledger.py`, `verify_ledger.py`, `citation_check.py`, `policy_gate.py`, `gap_miner.py`, `metrics.py`, `aar.py`, tests |
| 1 | Agents + engine | `llm.py` (glm + mock), `agents.py`, `engine.py`, `run_scenario.py`, agent/scenario/duty configs |
| 1 | Console | `app/server.py`, `app/static/*` |
| 2 | Lead | Real policy rules from verified clauses; retrieval test set; end-to-end mock run; console wired to real runs |
| 3 | Lead (needs your OK to spend GLM) | Demo runs: S1 governed, ungoverned, Arabic; judge inject; gap narratives; metrics; AAR |
| 4 | Lead + subagent | Saudi pack / live-inject reuse demo, readiness causal propagation, agent cards, README, report numbers |

## Needed from the team
- **Manual downloads** of UAE texts whose official portals block automated retrieval (list: `kb/sources/MANUAL_DOWNLOADS.md`), dropped into `kb/raw/manual/`.
- **OK to spend the GLM key** on the demo runs (≈30–45 calls per run, 3–5 runs).
- **Team names** for the README/report; exact submission hour.
- **Abhra**: review flagged items (`needs_team_review` in the eval set, `review: pending_team_review` in rules, Tier-2 gaps).
