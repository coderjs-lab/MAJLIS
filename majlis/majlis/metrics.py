"""Run metrics computed from ledger entries only. Pure function, no LLM."""
from __future__ import annotations

from collections import Counter
from typing import Any

from majlis.citation_check import STATUSES


def _payload(e: dict) -> dict:
    return e.get("payload") or {}


def citation_index(entries: list[dict]) -> dict[tuple, str]:
    """(agent_id, round, claim_id) -> citation status, from citation_check entries."""
    idx: dict[tuple, str] = {}
    for e in entries:
        if e.get("event_type") == "citation_check":
            p = _payload(e)
            for r in p.get("results") or []:
                idx[(p.get("agent_id"), p.get("round"), r.get("claim_id"))] = r.get("status")
    return idx


def executed_actions(entries: list[dict]) -> list[dict]:
    """Actions that went ahead: gate ALLOW, gate not enforced (ungoverned), or
    a human approved them. Each item: agent_id, round, action (dict), seq.
    The action is joined to the most recent agent_turn of that agent that
    proposed the same action_id."""
    proposed: dict[tuple, tuple[Any, dict]] = {}   # (agent, action_id) -> (round, action)
    out: dict[tuple, dict] = {}

    def mark(agent: str, action_id: str, seq: int) -> None:
        rnd, action = proposed.get((agent, action_id), (None, {"action_id": action_id}))
        key = (agent, rnd, action_id)
        if key not in out:
            out[key] = {"agent_id": agent, "round": rnd, "action": action, "seq": seq}

    for e in entries:
        et, p = e.get("event_type"), _payload(e)
        if et == "agent_turn":
            for a in (p.get("turn") or {}).get("proposed_actions") or []:
                proposed[(p.get("agent_id"), a.get("action_id"))] = (p.get("round"), a)
        elif et == "gate_decision":
            if p.get("decision") == "ALLOW" or p.get("enforced") is False:
                mark(p.get("agent_id"), p.get("action_id"), e["seq"])
        elif et == "human_decision":
            if p.get("decision") == "approve":
                mark(p.get("agent_id"), p.get("action_id"), e["seq"])
    return list(out.values())


def unsupported_bases(entries: list[dict]) -> list[dict]:
    """Legal claims used as the basis of an executed action whose citation status
    is not VERIFIED (including claims with no citation result at all)."""
    status = citation_index(entries)
    seen, out = set(), []
    for x in executed_actions(entries):
        for cid in x["action"].get("legal_basis_claim_ids") or []:
            key = (x["agent_id"], x["round"], cid)
            st = status.get(key)
            # NO_CITATION = a non-legal claim (fact from inject / recommendation) that needs no clause.
            if st not in ("VERIFIED", "NO_CITATION") and key not in seen:
                seen.add(key)
                out.append({"agent_id": x["agent_id"], "round": x["round"], "claim_id": cid,
                            "action_id": x["action"].get("action_id"), "status": st or "NOT_CHECKED"})
    return out


def compute(entries: list[dict]) -> dict:
    cit = {s: 0 for s in STATUSES}
    gate = {"allow": 0, "deny": 0, "escalate": 0, "would_deny_let_through": 0,
            "would_escalate_let_through": 0, "out_of_vocabulary": 0}
    human = {"approved": 0, "rejected": 0}
    llm = {"calls": 0, "errors": 0, "prompt_tokens": 0, "completion_tokens": 0, "latency_ms_total": 0}
    gaps_by_pattern: Counter = Counter()
    gaps_total = gaps_global = gaps_insufficient = 0
    duties_first: dict[str, str | None] = {}

    for e in entries:
        et, p = e.get("event_type"), _payload(e)
        if et == "citation_check":
            for r in p.get("results") or []:
                cit[r["status"]] = cit.get(r["status"], 0) + 1
        elif et == "gate_decision":
            d = p.get("decision")
            if d in ("ALLOW", "DENY", "ESCALATE"):
                gate[d.lower()] += 1
            if p.get("enforced") is False and d == "DENY":
                gate["would_deny_let_through"] += 1
            if p.get("enforced") is False and d == "ESCALATE":
                gate["would_escalate_let_through"] += 1
            if "out_of_vocabulary" in (p.get("events") or []):
                gate["out_of_vocabulary"] += 1
        elif et == "human_decision":
            if p.get("decision") == "approve":
                human["approved"] += 1
            elif p.get("decision") == "reject":
                human["rejected"] += 1
        elif et == "llm_call":
            llm["calls"] += 1
            if p.get("error"):
                llm["errors"] += 1
            usage = p.get("usage") or {}
            llm["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
            llm["completion_tokens"] += int(usage.get("completion_tokens") or 0)
            llm["latency_ms_total"] += int(p.get("latency_ms") or 0)
        elif et == "gap_candidate":
            gaps_total += 1
            gaps_by_pattern[p.get("pattern")] += 1
            if p.get("global_examples"):
                gaps_global += 1
            if p.get("insufficient_evidence"):
                gaps_insufficient += 1
        elif et == "agent_turn":
            for duty in (p.get("turn") or {}).get("responsibilities_claimed") or []:
                duties_first.setdefault(duty, e.get("stage"))

    # Share of cited claims that verified (claims that cite nothing are excluded).
    checked = sum(cit.values()) - cit["NO_CITATION"]
    cit["verification_rate"] = round(cit["VERIFIED"] / checked, 3) if checked else 0.0

    return {
        "citations": cit,
        "gate": gate,
        "human": human,
        "unsupported_passed_as_fact": len(unsupported_bases(entries)),
        "gaps": {"by_pattern": dict(gaps_by_pattern), "total": gaps_total,
                 "with_global_example": gaps_global, "insufficient_evidence": gaps_insufficient},
        "llm": llm,
        "duties_first_identified": duties_first,
    }
