"""Shared data contracts for MAJLIS.

Every module imports its types from here. Changing a field here is a contract
change: update CONTRACTS.md and every producer/consumer in the same commit.
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Knowledge base
# ---------------------------------------------------------------------------

Jurisdiction = str  # AE | AE-AZ | AE-DU | EU | US | SG | SA | INTL
InstrumentType = Literal[
    "law", "decree", "regulation", "standard", "policy", "strategy",
    "guidance", "itu_recommendation", "framework", "charter", "test_fixture",
]
Binding = Literal["binding", "non_binding", "unknown"]
Language = Literal["en", "ar"]


class Clause(BaseModel):
    """One citable unit of law/standard/guidance. `text` is stored exactly as
    extracted and is never paraphrased or cleaned."""
    clause_id: str                      # e.g. "EU-REG-2016-679/art-33/para-1/en"
    doc_id: str
    doc_title: str
    issuer: str
    jurisdiction: Jurisdiction
    instrument_type: InstrumentType
    binding: Binding
    sectors: List[str] = Field(default_factory=list)   # health, data, telecom, cyber, ai, general
    language: Language = "en"
    translation_status: str = "original"  # original | official_translation | unofficial_translation
    parallel_clause_id: Optional[str] = None
    article: Optional[str] = None
    paragraph: Optional[str] = None
    heading: Optional[str] = None
    text: str
    url: str
    page: Optional[int] = None
    effective_date: Optional[str] = None
    retrieved_at: str
    source_sha256: str
    tier: str                           # A..F per playbook section 7.1, or "TEST"
    extraction: str = "ok"              # ok | extraction_failed | manual


class RetrievalFilters(BaseModel):
    jurisdiction: Optional[List[str]] = None
    sectors: Optional[List[str]] = None
    binding: Optional[List[str]] = None
    language: Optional[List[str]] = None


class EvidenceItem(BaseModel):
    """A clause as shown to an agent (and to the UI)."""
    clause_id: str
    doc_id: str
    doc_title: str
    issuer: str
    jurisdiction: str
    instrument_type: str
    binding: str
    article: Optional[str] = None
    paragraph: Optional[str] = None
    heading: Optional[str] = None
    language: str = "en"
    url: str
    text: str
    score: float = 0.0
    rank_dense: Optional[int] = None
    rank_bm25: Optional[int] = None


# ---------------------------------------------------------------------------
# Agent configuration (configs/agents/<id>.yaml)
# ---------------------------------------------------------------------------

AgentKind = Literal["application", "institution", "adviser"]


class AgentConfig(BaseModel):
    id: str
    display_name: str
    display_name_ar: Optional[str] = None
    short_name: Optional[str] = None            # e.g. "DoH" for compact UI
    kind: AgentKind
    jurisdiction: str
    mandate: str
    mandate_sources: List[str] = Field(default_factory=list)  # clause_ids; empty => "unverified summary"
    retrieval_filters: RetrievalFilters = Field(default_factory=RetrievalFilters)
    retrieval_k: int = 8
    retrieval_focus: Optional[str] = None       # standing interests, fused into every turn's retrieval
    can_message: List[str] = Field(default_factory=list)
    action_vocabulary: List[str] = Field(default_factory=list)
    output_language: Language = "en"
    effort: str = "low"


# ---------------------------------------------------------------------------
# LLM outputs (validated JSON)
# ---------------------------------------------------------------------------

ClaimType = Literal["obligation", "permission", "prohibition", "definition",
                    "fact_from_inject", "recommendation"]
LEGAL_CLAIM_TYPES = {"obligation", "permission", "prohibition", "definition"}


class Claim(BaseModel):
    claim_id: str
    statement: str
    claim_type: ClaimType
    clause_id: Optional[str] = None
    quote: Optional[str] = None


class ProposedAction(BaseModel):
    action_id: str
    action_type: str
    target: Optional[str] = None
    description: str
    legal_basis_claim_ids: List[str] = Field(default_factory=list)
    urgency: Literal["immediate", "hours", "days", "unspecified"] = "unspecified"


class AgentRequest(BaseModel):
    to_agent: str
    question: str


class AgentTurn(BaseModel):
    situation_summary: str
    claims: List[Claim] = Field(default_factory=list)
    proposed_actions: List[ProposedAction] = Field(default_factory=list)
    requests: List[AgentRequest] = Field(default_factory=list)
    responsibilities_claimed: List[str] = Field(default_factory=list)     # from configs/duties.yaml
    responsibilities_disclaimed: List[str] = Field(default_factory=list)  # from configs/duties.yaml
    insufficient_evidence: List[str] = Field(default_factory=list)
    uncertainties: List[str] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"] = "medium"


class GlobalExample(BaseModel):
    jurisdiction: str
    instrument: str
    clause_id: Optional[str] = None
    quote: Optional[str] = None
    how_it_handles: str


class AdviceAnswer(BaseModel):
    question: str
    answer_summary: str
    claims: List[Claim] = Field(default_factory=list)
    global_examples: List[GlobalExample] = Field(default_factory=list)
    suspected_gaps: List[str] = Field(default_factory=list)
    insufficient_evidence: bool = False


class GapNarrative(BaseModel):
    """LLM-written wording for a code-detected gap. Strictly from evidence."""
    title: str
    description: str
    implication: str
    next_step: str


# ---------------------------------------------------------------------------
# Deterministic layer
# ---------------------------------------------------------------------------

CitationStatus = Literal["VERIFIED", "NEAR_MATCH", "FAILED", "NOT_RETRIEVED",
                         "UNKNOWN_CLAUSE", "UNSUPPORTED", "NO_CITATION"]


class CitationResult(BaseModel):
    claim_id: str
    clause_id: Optional[str] = None
    status: CitationStatus
    score: float = 0.0                  # fuzzy partial ratio 0..100 where computed
    claim_type: Optional[str] = None
    note: Optional[str] = None


class RuleCondition(BaseModel):
    action_type: List[str] = Field(default_factory=list)
    state: Dict[str, Any] = Field(default_factory=dict)


class Rule(BaseModel):
    rule_id: str
    status: Literal["draft", "verified"] = "draft"
    review: str = "pending_team_review"        # who checked the clause text, or pending
    description: str
    applies_when: RuleCondition
    unless_state: Dict[str, Any] = Field(default_factory=dict)
    decision: Literal["ALLOW", "DENY", "ESCALATE", "REQUIRE"]
    clause_ids: List[str] = Field(default_factory=list)
    quote: Optional[str] = None                # verbatim excerpt of clause_ids[0]; checked by the gate
    message_en: str = ""
    message_ar: str = ""


GateOutcome = Literal["ALLOW", "DENY", "ESCALATE"]


class GateDecision(BaseModel):
    action_id: str
    agent_id: str
    action_type: str
    decision: GateOutcome                      # what the gate decided
    status_code: int                           # 200 ALLOW, 403 DENY, 202 ESCALATE (pending human)
    mode: Literal["governed", "ungoverned"]
    enforced: bool                             # False in ungoverned mode (logged as would_have_decided)
    rule_ids: List[str] = Field(default_factory=list)
    clause_id: Optional[str] = None
    quote: Optional[str] = None
    issuer: Optional[str] = None
    url: Optional[str] = None
    message: str = ""
    state_facts: Dict[str, Any] = Field(default_factory=dict)
    events: List[str] = Field(default_factory=list)   # policy_void | conflict | no_rule | out_of_vocabulary
    reason: str = ""                                  # which step of the decision algorithm fired


class GapEvidence(BaseModel):
    ledger_seqs: List[int] = Field(default_factory=list)
    clause_ids: List[str] = Field(default_factory=list)


class GapCandidate(BaseModel):
    gap_id: str                                 # e.g. "G2-001"
    type: Literal["policy", "standards", "technical"]
    pattern: Literal["G1_POLICY_VOID", "G2_CONFLICT", "G3_RESPONSIBILITY", "G4_CLOCK", "G5_STANDARDS"]
    title: str
    description: str
    evidence: GapEvidence = Field(default_factory=GapEvidence)
    readiness_dimensions: List[int] = Field(default_factory=list)   # 1..13
    global_examples: List[GlobalExample] = Field(default_factory=list)
    insufficient_evidence: bool = False        # True => no verified global example found
    implication: str = ""
    next_step: str = ""
    confidence: Literal["low", "medium", "high"] = "medium"
    status: Literal["candidate"] = "candidate"
    detail: Dict[str, Any] = Field(default_factory=dict)  # detector-specific facts (e.g. duty, deadlines)


# ---------------------------------------------------------------------------
# Audit ledger
# ---------------------------------------------------------------------------

EVENT_TYPES = (
    "run_start", "inject", "retrieval", "llm_call", "agent_turn", "citation_check",
    "gate_decision", "human_decision", "message", "stage_end", "gap_candidate",
    "agent_error", "metrics", "run_end",
)


class LedgerEntry(BaseModel):
    seq: int
    ts: str
    run_id: str
    stage: Optional[str] = None
    actor: str
    event_type: str
    payload: Dict[str, Any]
    prev_hash: str
    hash: str


# ---------------------------------------------------------------------------
# Scenario (configs/scenarios/<id>.yaml)
# ---------------------------------------------------------------------------

class Stage(BaseModel):
    id: str
    sim_time: str
    title: Optional[str] = None
    recipients: List[str]
    inject_en: str
    inject_ar: Optional[str] = None
    state_changes: Dict[str, Any] = Field(default_factory=dict)
    expected: str = ""
    expected_ar: Optional[str] = None
    synthetic_data: bool = False


class Scenario(BaseModel):
    id: str
    title: str
    title_ar: Optional[str] = None
    country_pack: str = "uae"
    disclaimer: str
    initial_state: Dict[str, Any] = Field(default_factory=dict)
    stages: List[Stage]
