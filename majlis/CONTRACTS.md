# MAJLIS build contracts

The interface every module and builder follows. Types live in `majlis/schemas.py`.
If you must change a contract, change this file and every caller in the same step.

Root: `ITUAIReadiness/majlis/` (all paths below are relative to it).
Python: `.venv/bin/python` (3.12). Run tests with `.venv/bin/python -m pytest -q`.
Imports: `from majlis.schemas import ...` (run from the `majlis/` root; `scripts/*` add the root to `sys.path`).

## Non-negotiable rules (from the playbook)
1. **No invented law.** No law names, article numbers, quotes, deadlines or mandates written from memory into code, configs, prompts, tests or docs. Legal text enters the system only through `kb/clauses/clauses.jsonl`, which is extracted from downloaded official files. Test fixtures use obviously fake clauses (`TEST-DOC/art-1`).
2. **The LLM proposes, code decides.** The citation checker, policy gate, gap detectors, ledger and metrics never call an LLM.
3. **Facts come from state.** The gate reads scenario state owned by the engine, never facts asserted by a model.
4. **Fiction, labelled.** The scenario, the provider "OasisCare" and all telemetry are fictional; the institutional agents are simulations. Every UI view, README and scenario file carries this disclaimer. Never use a real company name.
5. **Secrets.** `GLM_API_KEY` comes from `.env` (project root `../../.env` or `majlis/.env`). Never print it or write it into the ledger, logs or commits.
6. **Building does not spend the GLM key.** Builders and tests use the offline `mock` backend. Only the final demo runs use `glm`.

## Module interfaces

### `majlis/ledger.py`
```python
GENESIS = "0" * 64
def canonical_json(obj) -> str            # sort_keys=True, separators=(",", ":"), ensure_ascii=False
class Ledger:
    def __init__(self, run_dir: Path, run_id: str)       # writes run_dir/ledger.jsonl (append, flush each line)
    def append(self, stage: str | None, actor: str, event_type: str, payload: dict) -> LedgerEntry
    # hash = sha256((prev_hash + canonical_json(entry_without_hash)).encode("utf-8")).hexdigest()
    # entry_without_hash = {seq, ts, run_id, stage, actor, event_type, payload, prev_hash}
    # seq starts at 0; ts is UTC ISO-8601 with "Z"
def load_entries(path: Path) -> list[dict]
def verify_chain(path_or_entries) -> tuple[bool, int, int | None]   # (ok, n_entries, first_broken_seq)
Y3172_NODE: dict[str, str]   # event_type -> Y.3172 node label (see table below)
```
Also write `run_dir/manifest.json` at run start (via `write_manifest(run_dir, dict)`): git commit, config file sha256s, KB version hash, model, backend, mode, approver, lang, started_at.

### `majlis/retrieval.py`
```python
class KB:
    @classmethod
    def load(cls, kb_dir: Path = Path("kb")) -> "KB"     # reads kb/clauses/clauses.jsonl (+ kb/index/* if present)
    clauses: dict[str, Clause]
    dense_available: bool
    version: str                                          # sha256 of clauses.jsonl
    def get(self, clause_id: str) -> Clause | None
    def search(self, query: str, filters: RetrievalFilters | None = None, k: int = 8,
               mode: str = "hybrid") -> list[EvidenceItem]  # mode: hybrid | dense | bm25
def normalise_for_search(text: str) -> str               # NFKC, lowercase, Arabic: strip diacritics/tatweel, unify alef
```
Hybrid = Reciprocal Rank Fusion, `score = sum(1/(60+rank))` over dense and BM25 lists (top 50 each), return top k.
If dense is unavailable (no `kb/index/dense.npy` or no sentence-transformers), hybrid silently degrades to BM25 and `dense_available=False`.
`KB.load` must also accept `kb_dir=Path("tests/fixtures/kb")` (the stub KB).

### `majlis/citation_check.py`
```python
def normalise_quote(text: str) -> str   # NFKC, collapse whitespace, unify quotes/dashes, Arabic: strip diacritics+tatweel, casefold
def check_claims(claims: list[Claim], evidence_ids: set[str], kb: KB) -> list[CitationResult]
```
Order per claim: legal type (obligation/permission/prohibition/definition) with no clause_id or no quote -> UNSUPPORTED;
non-legal type with no clause_id -> NO_CITATION; clause not in KB -> UNKNOWN_CLAUSE; clause not in evidence_ids -> NOT_RETRIEVED;
normalised quote is substring of normalised clause text -> VERIFIED; rapidfuzz `partial_ratio >= 90` -> NEAR_MATCH; else FAILED.
Only VERIFIED claims may be used as a legal basis anywhere downstream.

### `majlis/policy_gate.py`
```python
def load_rules(path: Path) -> list[Rule]
class PolicyGate:
    def __init__(self, rules: list[Rule], kb: KB, high_impact: set[str], vocabulary: dict[str, list[str]])
    def decide(self, action: ProposedAction, agent_id: str, state: dict, mode: str) -> GateDecision
```
Algorithm (in order): action_type not in the agent's vocabulary -> DENY event `out_of_vocabulary`;
collect rules whose `applies_when.action_type` contains the action and whose `applies_when.state` all match `state` and whose `unless_state` does not all hold;
matched DENY + matched REQUIRE -> ESCALATE + event `conflict`; any **verified** DENY -> DENY 403 (clause_id/quote/issuer/url from the KB clause of the rule's first clause_id);
any ESCALATE or **draft** DENY -> ESCALATE (202); only ALLOW -> ALLOW (200); no match and action in `high_impact` -> ESCALATE + event `policy_void`;
no match, low impact -> ALLOW + event `no_rule`. In `ungoverned` mode compute the same decision, set `enforced=False` (the engine lets it through).
High-impact list lives in `configs/policies/<pack>_rules.yaml` under a top-level `high_impact_actions:` key; rules under `rules:`.

### `majlis/gap_miner.py`
```python
def mine(entries: list[dict], duties: list[str], standards_coverage: dict) -> list[GapCandidate]
```
Pure function over ledger entries. Detectors G1–G5 as in playbook 9.4:
G1 POLICY_VOID: gate `policy_void` events, or the same question (normalised, fuzzy >= 85) in `insufficient_evidence` of 2+ agents.
G2 CONFLICT: gate `conflict` events.
G3 RESPONSIBILITY: duty in `responsibilities_claimed` of 2+ agents (overlap) or requested/disclaimed by some agent but claimed by none (vacuum).
G4 CLOCK: VERIFIED claims from 2+ different doc_ids whose quotes contain different deadlines (regex: numbers + hour(s)/day(s)/business days, "without undue delay", "immediately", "promptly", Arabic ساعة/ساعات/يوم/أيام/فوراً/دون تأخير).
G5 STANDARDS: for each scenario need in `configs/standards_coverage.yaml` with `covered: false`, emit one gap.
Each candidate carries evidence ledger seqs + clause_ids and readiness_dimensions (static map per pattern, overridable in standards_coverage.yaml). Description is templated deterministically; the engine may later fill `GapNarrative` + global examples via the Legal Adviser.

### `majlis/metrics.py`
```python
def compute(entries: list[dict]) -> dict
```
Keys: `citations` {VERIFIED, NEAR_MATCH, FAILED, NOT_RETRIEVED, UNKNOWN_CLAUSE, UNSUPPORTED, NO_CITATION, verification_rate},
`gate` {allow, deny, escalate, would_deny_let_through, would_escalate_let_through, out_of_vocabulary},
`human` {approved, rejected}, `unsupported_passed_as_fact` (legal claims not VERIFIED that were used as legal_basis of an executed action),
`gaps` {by_pattern, total, with_global_example, insufficient_evidence}, `llm` {calls, errors, prompt_tokens, completion_tokens, latency_ms_total},
`duties_first_identified` {duty: stage_id}.

### `majlis/aar.py`
```python
def render_aar(entries: list[dict]) -> str   # Markdown After-Action Report, deterministic, from the ledger only
```

### `majlis/llm.py`
```python
@dataclass
class LLMResult: parsed: BaseModel | None; raw_text: str; usage: dict; prompt_sha256: str; latency_ms: int;
                 model: str; backend: str; attempts: int; error: str | None
def structured_call(system: str, user: str, schema: type[BaseModel], *, purpose: str, agent_id: str,
                    effort: str | None = None, context: dict | None = None) -> LLMResult
```
Backends via env `MAJLIS_BACKEND` = `glm` | `mock` (default `mock` when no key). GLM: OpenAI-compatible
`POST {MAJLIS_GLM_BASE_URL or https://api.z.ai/api/paas/v4}/chat/completions`, `Authorization: Bearer $GLM_API_KEY`,
`model=$MAJLIS_MODEL` (default `glm-5.3`), `response_format={"type":"json_object"}`, `thinking={"type":"enabled"}`,
top-level `reasoning_effort` in {low, high, max} (map medium->high). The JSON schema is embedded in the system prompt.
Validate with Pydantic; on failure retry once with the validation error appended; on second failure return `parsed=None, error=...`.
`mock` backend: deterministic, schema-valid outputs built from `context` (evidence clauses, vocabulary, inject) — it quotes the
first sentence of an evidence clause verbatim so the citation checker can be exercised. Label it clearly as mock output.

### `majlis/agents.py`, `majlis/engine.py`
```python
def load_agent_configs(dir: Path) -> dict[str, AgentConfig]
def load_scenario(path: Path) -> Scenario
def run_scenario(scenario_path: Path, *, mode: str, approver: str, lang: str, pack: str = "uae",
                 extra_stages: list[Stage] | None = None, runs_dir: Path = Path("runs"),
                 run_id: str | None = None) -> Path          # returns the run directory
```
approver: `reject_all` | `approve_all` | `interactive` (wait for `run_dir/approvals/<action_id>.json` = {"decision": "approve"|"reject", "by": "..."}; timeout -> reject, recorded).

## Ledger event payloads (what the UI reads)

| event_type | actor | payload |
|---|---|---|
| run_start | engine | scenario_id, title, title_ar, disclaimer, mode, approver, lang, model, backend, kb_version, agents:[{id, display_name, display_name_ar, short_name, kind, mandate, mandate_verified}], stages:[{id, sim_time, title, recipients, expected, expected_ar}] |
| inject | engine | stage_id, sim_time, title, recipients, text, text_ar, state_changes, state_after, expected, synthetic_data |
| retrieval | agent id | agent_id, query, filters, results:[{clause_id, doc_title, article, score}] |
| llm_call | agent id | agent_id, purpose, model, backend, effort, prompt_sha256, system, user, raw_output, usage, latency_ms, attempts, error |
| agent_turn | agent id | agent_id, round, turn (AgentTurn dict), evidence_clause_ids |
| citation_check | engine | agent_id, round, results:[CitationResult], counts:{status: n} |
| gate_decision | gate | GateDecision dict |
| human_decision | approver | action_id, agent_id, decision (approve/reject), approver ("simulated:reject_all", "human:<name>", "timeout"), rule_ids |
| message | agent id / engine | msg_type (request/advice/assessment/gate_decision/human_decision), from, to, content |
| stage_end | engine | stage_id, allowed, blocked, escalated, open_requests, state |
| gap_candidate | gap_miner | GapCandidate dict |
| agent_error | agent id | agent_id, error, attempts |
| metrics | engine | metrics.compute() output |
| run_end | engine | status (completed/failed), counts, duration_s |

`Y3172_NODE`: run_start→MLFO, inject→SRC→C, retrieval→PP, llm_call→M, agent_turn→M, citation_check→P, gate_decision→P,
human_decision→SINK (HA), message→D, stage_end→MLFO, gap_candidate→SINK (GM), agent_error→M, metrics→MLFO, run_end→MLFO.

## Config files
- `configs/agents/{triage,doh,tdra,data_office,legal_adviser}.yaml` -> AgentConfig
- `configs/duties.yaml` -> `duties: [notify_data_protection_authority, notify_health_regulator, report_network_outage, suspend_ai_service, inform_affected_patients, revalidate_model, approve_data_transfer, report_cyber_incident, approve_model_update, coordinate_public_communication]`
- `configs/policies/uae_rules.yaml` -> `high_impact_actions: [...]`, `rules: [Rule...]`
- `configs/scenarios/s1_failover.yaml` -> Scenario; `configs/scenarios/challenge_cards.yaml` -> list of Stage-like injects
- `configs/standards_coverage.yaml` -> `needs: [{id, need, standard, covered, note, readiness_dimensions}]`
- `configs/countries/uae.yaml` -> pack: agents dir, rules file, KB jurisdictions, display names
