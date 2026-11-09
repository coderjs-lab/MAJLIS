"""Gap miner: deterministic detectors over ledger entries.

    G1 POLICY_VOID       gate `policy_void` events; or the same question
                         (normalised, fuzzy >= 85) in `insufficient_evidence`
                         of 2+ agents
    G2 CONFLICT          gate `conflict` events
    G3 RESPONSIBILITY    a duty claimed by 2+ agents (overlap), or requested /
                         disclaimed by some agent but claimed by none (vacuum)
    G4 CLOCK             VERIFIED claims from 2+ documents whose quotes state
                         different deadlines
    G5 STANDARDS         each scenario need marked `covered: false` (medium) or
                         `covered: partial` (low); `true` is a positive mapping

Each detector is a small pure function. Descriptions are templates that state
only what the ledger shows. Gap candidates are *candidates*: a human reviews
them. No LLM is called.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Iterable

from rapidfuzz import fuzz

from majlis.citation_check import normalise_quote
from majlis.schemas import GapCandidate, GapEvidence

PATTERN_CODE = {
    "G1_POLICY_VOID": "G1", "G2_CONFLICT": "G2", "G3_RESPONSIBILITY": "G3",
    "G4_CLOCK": "G4", "G5_STANDARDS": "G5",
}
# Default ITU AI-readiness dimensions per pattern (overridable in standards_coverage.yaml
# under `pattern_dimensions: {G1: [...], ...}`).
READINESS_DIMENSIONS: dict[str, list[int]] = {
    "G1": [10, 7], "G2": [10, 4], "G3": [7, 10], "G4": [7, 3], "G5": [10, 13],
}
QUESTION_FUZZ_THRESHOLD = 85


# ---------------------------------------------------------------------------
# Ledger helpers
# ---------------------------------------------------------------------------

def _of_type(entries: Iterable[dict], event_type: str) -> list[dict]:
    return [e for e in entries if e.get("event_type") == event_type]


def _turns(entries: list[dict]) -> list[tuple[dict, str, dict]]:
    """(entry, agent_id, turn dict) for every agent_turn entry."""
    out = []
    for e in _of_type(entries, "agent_turn"):
        p = e.get("payload") or {}
        out.append((e, p.get("agent_id") or e.get("actor"), p.get("turn") or {}))
    return out


def doc_id_of(clause_id: str) -> str:
    """Document id = first path segment of a clause id (e.g. 'TEST-DOC-A/art-2/en')."""
    return clause_id.split("/", 1)[0]


def verified_claims(entries: list[dict]) -> list[dict]:
    """Join agent_turn claims with citation_check results (by agent, round,
    claim_id) and keep only VERIFIED ones. Returns dicts with agent_id, round,
    claim_id, clause_id, quote, statement, seqs."""
    claims: dict[tuple, tuple[dict, int]] = {}
    for e, agent, turn in _turns(entries):
        rnd = (e.get("payload") or {}).get("round")
        for c in turn.get("claims") or []:
            claims[(agent, rnd, c.get("claim_id"))] = (c, e["seq"])
    out = []
    for e in _of_type(entries, "citation_check"):
        p = e.get("payload") or {}
        for r in p.get("results") or []:
            if r.get("status") != "VERIFIED":
                continue
            key = (p.get("agent_id"), p.get("round"), r.get("claim_id"))
            if key not in claims:
                continue
            c, turn_seq = claims[key]
            out.append({
                "agent_id": key[0], "round": key[1], "claim_id": key[2],
                "clause_id": r.get("clause_id") or c.get("clause_id"),
                "quote": c.get("quote") or "", "statement": c.get("statement") or "",
                "seqs": [turn_seq, e["seq"]],
            })
    return out


def _fmt_state(state: dict) -> str:
    if not state:
        return "{}"
    return "{" + ", ".join(f"{k}={v}" for k, v in state.items()) + "}"


class _Ids:
    """Stable ids: G1-001, G1-002, ... per pattern, in detection order."""
    def __init__(self) -> None:
        self.counts: dict[str, int] = defaultdict(int)

    def next(self, code: str) -> str:
        self.counts[code] += 1
        return f"{code}-{self.counts[code]:03d}"


def _gap(ids: _Ids, pattern: str, gap_type: str, title: str, description: str,
         seqs: Iterable[int], clause_ids: Iterable[str], dims: dict[str, list[int]],
         detail: dict, confidence: str = "medium") -> GapCandidate:
    code = PATTERN_CODE[pattern]
    return GapCandidate(
        gap_id=ids.next(code), type=gap_type, pattern=pattern, title=title,
        description=description,
        evidence=GapEvidence(ledger_seqs=sorted(set(seqs)), clause_ids=sorted(set(clause_ids))),
        readiness_dimensions=list(dims.get(code, READINESS_DIMENSIONS[code])),
        insufficient_evidence=True,  # no verified global example yet; the engine may add one
        confidence=confidence, detail=detail,
    )


# ---------------------------------------------------------------------------
# G1 POLICY_VOID
# ---------------------------------------------------------------------------

def detect_g1_gate(entries: list[dict], ids: _Ids, dims: dict) -> list[GapCandidate]:
    groups: dict[tuple, dict] = {}
    for e in _of_type(entries, "gate_decision"):
        p = e.get("payload") or {}
        if "policy_void" not in (p.get("events") or []):
            continue
        key = (p.get("action_type"), p.get("agent_id"), e.get("stage"))
        g = groups.setdefault(key, {"seqs": [], "state": p.get("state_facts") or {},
                                    "decision": p.get("decision")})
        g["seqs"].append(e["seq"])
    out = []
    for (action, agent, stage), g in groups.items():
        outcome = "escalated (fail-closed)" if g["decision"] == "ESCALATE" else f"decided {g['decision']}"
        out.append(_gap(
            ids, "G1_POLICY_VOID", "policy",
            title=f"No rule covers high-impact action `{action}`",
            description=(f"No rule in the policy pack applied to high-impact action `{action}` "
                         f"proposed by `{agent}` at stage {stage} in state {_fmt_state(g['state'])}; "
                         f"the gate {outcome}."),
            seqs=g["seqs"], clause_ids=[], dims=dims,
            detail={"trigger": "policy_void", "action_type": action, "agent_id": agent,
                    "stage": stage, "state": g["state"], "occurrences": len(g["seqs"])},
            confidence="high",
        ))
    return out


def detect_g1_questions(entries: list[dict], ids: _Ids, dims: dict) -> list[GapCandidate]:
    """Cluster `insufficient_evidence` questions (greedy, fuzzy >= 85) and
    report clusters raised by 2+ distinct agents."""
    clusters: list[dict] = []
    for e, agent, turn in _turns(entries):
        for q in turn.get("insufficient_evidence") or []:
            nq = normalise_quote(q)
            if not nq:
                continue
            for c in clusters:
                if fuzz.token_sort_ratio(nq, c["norm"]) >= QUESTION_FUZZ_THRESHOLD:
                    break
            else:
                c = {"norm": nq, "text": q, "agents": [], "seqs": [], "stages": []}
                clusters.append(c)
            if agent not in c["agents"]:
                c["agents"].append(agent)
            c["seqs"].append(e["seq"])
            if e.get("stage") not in c["stages"]:
                c["stages"].append(e.get("stage"))
    out = []
    for c in clusters:
        if len(c["agents"]) < 2:
            continue
        agents = ", ".join(f"`{a}`" for a in c["agents"])
        out.append(_gap(
            ids, "G1_POLICY_VOID", "policy",
            title="Question left without evidence by several agents",
            description=(f"Agents {agents} each reported insufficient evidence in the knowledge base "
                         f"for the question \"{c['text']}\" (stages: {', '.join(map(str, c['stages']))})."),
            seqs=c["seqs"], clause_ids=[], dims=dims,
            detail={"trigger": "insufficient_evidence", "question": c["text"], "agents": c["agents"],
                    "stages": c["stages"]},
        ))
    return out


# ---------------------------------------------------------------------------
# G2 CONFLICT
# ---------------------------------------------------------------------------

def detect_g2(entries: list[dict], ids: _Ids, dims: dict) -> list[GapCandidate]:
    groups: dict[tuple, dict] = {}
    for e in _of_type(entries, "gate_decision"):
        p = e.get("payload") or {}
        if "conflict" not in (p.get("events") or []):
            continue
        key = (p.get("action_type"), e.get("stage"), tuple(p.get("rule_ids") or []))
        g = groups.setdefault(key, {"seqs": [], "agents": [], "state": p.get("state_facts") or {},
                                    "clause_id": p.get("clause_id")})
        g["seqs"].append(e["seq"])
        if p.get("agent_id") not in g["agents"]:
            g["agents"].append(p.get("agent_id"))
    out = []
    for (action, stage, rule_ids), g in groups.items():
        rules = ", ".join(f"`{r}`" for r in rule_ids)
        agents = ", ".join(f"`{a}`" for a in g["agents"])
        out.append(_gap(
            ids, "G2_CONFLICT", "policy",
            title=f"Conflicting rules for action `{action}`",
            description=(f"Rules {rules} both applied to action `{action}` proposed by {agents} at stage "
                         f"{stage} in state {_fmt_state(g['state'])}: one denies it and one requires it; "
                         f"the gate escalated to a human."),
            seqs=g["seqs"], clause_ids=[g["clause_id"]] if g["clause_id"] else [], dims=dims,
            detail={"action_type": action, "stage": stage, "rule_ids": list(rule_ids),
                    "agents": g["agents"], "state": g["state"]},
            confidence="high",
        ))
    return out


# ---------------------------------------------------------------------------
# G3 RESPONSIBILITY
# ---------------------------------------------------------------------------

def _duty_mentioned(duty: str, text: str) -> bool:
    t = normalise_quote(text)
    return duty.casefold() in t or duty.replace("_", " ").casefold() in t


def detect_g3(entries: list[dict], duties: list[str], ids: _Ids, dims: dict) -> list[GapCandidate]:
    known = set(duties)
    claimed: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    disclaimed: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    requested: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for e, agent, turn in _turns(entries):
        for d in turn.get("responsibilities_claimed") or []:
            if not known or d in known:
                claimed[d][agent].append(e["seq"])
        for d in turn.get("responsibilities_disclaimed") or []:
            if not known or d in known:
                disclaimed[d][agent].append(e["seq"])
        for req in turn.get("requests") or []:
            for d in duties:
                if _duty_mentioned(d, req.get("question") or ""):
                    requested[d][agent].append(e["seq"])

    order = list(duties) + sorted((set(claimed) | set(disclaimed) | set(requested)) - set(duties))
    out = []
    for d in order:
        if len(claimed.get(d, {})) >= 2:
            agents = list(claimed[d])
            out.append(_gap(
                ids, "G3_RESPONSIBILITY", "policy",
                title=f"Overlapping responsibility for `{d}`",
                description=(f"Duty `{d}` was claimed by {len(agents)} agents: "
                             f"{', '.join(f'`{a}`' for a in agents)}."),
                seqs=[s for a in agents for s in claimed[d][a]], clause_ids=[], dims=dims,
                detail={"kind": "overlap", "duty": d, "agents": agents},
            ))
        elif not claimed.get(d) and (disclaimed.get(d) or requested.get(d)):
            dis, req = list(disclaimed.get(d, {})), list(requested.get(d, {}))
            parts = []
            if req:
                parts.append(f"requested by {', '.join(f'`{a}`' for a in req)}")
            if dis:
                parts.append(f"disclaimed by {', '.join(f'`{a}`' for a in dis)}")
            seqs = [s for src in (disclaimed.get(d, {}), requested.get(d, {})) for v in src.values() for s in v]
            out.append(_gap(
                ids, "G3_RESPONSIBILITY", "policy",
                title=f"No agent took responsibility for `{d}`",
                description=f"Duty `{d}` was {' and '.join(parts)}, and no agent claimed it.",
                seqs=seqs, clause_ids=[], dims=dims,
                detail={"kind": "vacuum", "duty": d, "requested_by": req, "disclaimed_by": dis},
            ))
    return out


# ---------------------------------------------------------------------------
# G4 CLOCK
# ---------------------------------------------------------------------------

_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
# Patterns run on normalise_quote() output (casefolded; Arabic alef unified, diacritics stripped).
_NUM_UNIT = re.compile(
    r"(\d+)\s*-?\s*(business\s+days?|working\s+days?|hours?|days?|ساعات|ساعة|ايام|يوما|يوم)")
_PHRASES = {
    "without undue delay": "without undue delay",
    "دون تاخير": "without undue delay",
    "immediately": "immediately",
    "فورا": "immediately",
    "promptly": "promptly",
}
_UNIT = {"hour": "hours", "hours": "hours", "ساعة": "hours", "ساعات": "hours",
         "day": "days", "days": "days", "يوم": "days", "يوما": "days", "ايام": "days"}


def extract_deadlines(text: str) -> list[str]:
    """Deadline expressions in a quote, normalised ('72 hours', 'without undue delay')."""
    t = normalise_quote(text).translate(_ARABIC_DIGITS)
    found: list[str] = []
    for m in _NUM_UNIT.finditer(t):
        unit = re.sub(r"\s+", " ", m.group(2))
        if unit.startswith(("business", "working")):
            unit = "business days"
        else:
            unit = _UNIT.get(unit, unit)
        found.append(f"{int(m.group(1))} {unit}")
    for phrase, label in _PHRASES.items():
        if phrase in t:
            found.append(label)
    return sorted(set(found))


def detect_g4(entries: list[dict], ids: _Ids, dims: dict) -> list[GapCandidate]:
    by_doc: dict[str, dict] = {}
    for c in verified_claims(entries):
        deadlines = extract_deadlines(c["quote"])
        if not deadlines or not c["clause_id"]:
            continue
        g = by_doc.setdefault(doc_id_of(c["clause_id"]),
                              {"deadlines": set(), "clause_ids": set(), "seqs": set()})
        g["deadlines"].update(deadlines)
        g["clause_ids"].add(c["clause_id"])
        g["seqs"].update(c["seqs"])
    if len(by_doc) < 2:
        return []
    distinct = {frozenset(g["deadlines"]) for g in by_doc.values()}
    if len(distinct) < 2:
        return []
    clocks = {doc: sorted(g["deadlines"]) for doc, g in sorted(by_doc.items())}
    summary = "; ".join(f"{doc}: {', '.join(d)}" for doc, d in clocks.items())
    return [_gap(
        ids, "G4_CLOCK", "policy",
        title="Different reporting clocks across instruments",
        description=(f"Verified quotes from {len(clocks)} documents state different deadlines ({summary}). "
                     f"The ledger does not show which clock governs this incident."),
        seqs=[s for g in by_doc.values() for s in g["seqs"]],
        clause_ids=[c for g in by_doc.values() for c in g["clause_ids"]], dims=dims,
        detail={"deadlines_by_doc": clocks},
    )]


# ---------------------------------------------------------------------------
# G5 STANDARDS
# ---------------------------------------------------------------------------

def _coverage(value) -> str:
    """Normalise `covered` (YAML bool or string) to 'true' | 'partial' | 'false'."""
    if isinstance(value, bool):
        return "true" if value else "false"
    v = str(value).strip().lower()
    return v if v in ("true", "partial", "false") else "false"


def standard_label(standard_id: str | None) -> str:
    """'ITU-T-Y3172' -> 'ITU-T Y.3172' (other ids are returned unchanged)."""
    if not standard_id:
        return "The mapped standard"
    m = re.fullmatch(r"ITU-T-([A-Z])\.?(\d+(?:\.\d+)?)", standard_id)
    return f"ITU-T {m.group(1)}.{m.group(2)}" if m else standard_id


def detect_g5(standards_coverage: dict, ids: _Ids, dims: dict) -> list[GapCandidate]:
    """One gap per need with `covered: false` (confidence medium) or
    `covered: partial` (confidence low). `covered: true` is a positive mapping."""
    out = []
    for need in (standards_coverage or {}).get("needs") or []:
        cov = _coverage(need.get("covered", True))
        if cov == "true":
            continue
        std = standard_label(need.get("standard"))
        what = need.get("need") or need.get("id")
        verb = "does not specify" if cov == "false" else "only partly specifies"
        desc = (f"Scenario need `{need.get('id')}` ({what}) is marked `covered: {cov}` against {std}"
                + (f", section {need['section']}" if need.get("section") else "") + ".")
        if need.get("note"):
            desc += f" Team reading: {need['note']}"
        g = _gap(
            ids, "G5_STANDARDS", "standards",
            title=f"{std} {verb}: {what}",
            description=desc, seqs=[], clause_ids=[], dims=dims,
            detail={"need_id": need.get("id"), "need": need.get("need"), "standard": need.get("standard"),
                    "section": need.get("section"), "quote": need.get("quote"),
                    "covered": cov, "note": need.get("note"), "proposal": need.get("proposal")},
            confidence="medium" if cov == "false" else "low",
        )
        if need.get("readiness_dimensions"):
            g.readiness_dimensions = list(need["readiness_dimensions"])
        out.append(g)
    return out


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _dimension_overrides(standards_coverage: dict) -> dict[str, list[int]]:
    dims = dict(READINESS_DIMENSIONS)
    for key, val in ((standards_coverage or {}).get("pattern_dimensions") or {}).items():
        code = PATTERN_CODE.get(key, key)
        dims[code] = list(val)
    return dims


def mine(entries: list[dict], duties: list[str], standards_coverage: dict | None) -> list[GapCandidate]:
    """Run G1..G5 over a run's ledger entries. Pure and deterministic."""
    dims = _dimension_overrides(standards_coverage or {})
    ids = _Ids()
    gaps: list[GapCandidate] = []
    gaps += detect_g1_gate(entries, ids, dims)
    gaps += detect_g1_questions(entries, ids, dims)
    gaps += detect_g2(entries, ids, dims)
    gaps += detect_g3(entries, list(duties or []), ids, dims)
    gaps += detect_g4(entries, ids, dims)
    gaps += detect_g5(standards_coverage or {}, ids, dims)
    return gaps
