"""Shared helpers for the trust-layer tests (fictional TEST-DOC fixtures only)."""
from __future__ import annotations

import json
from pathlib import Path

from majlis.ledger import Ledger
from majlis.schemas import Clause

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CLAUSES_FILE = FIXTURES / "kb" / "clauses" / "clauses.jsonl"
RULES_FILE = FIXTURES / "rules_test.yaml"


class FakeKB:
    """Dict-backed stand-in for retrieval.KB: only `get` is needed."""

    def __init__(self, clauses: dict[str, Clause]):
        self.clauses = clauses

    def get(self, clause_id: str) -> Clause | None:
        return self.clauses.get(clause_id)


def load_fake_kb() -> FakeKB:
    clauses = {}
    for line in CLAUSES_FILE.read_text(encoding="utf-8").splitlines():
        if line.strip():
            c = Clause(**json.loads(line))
            clauses[c.clause_id] = c
    return FakeKB(clauses)


def write_ledger(run_dir: Path, events: list[tuple]) -> list[dict]:
    """Write (stage, actor, event_type, payload) tuples through the real
    Ledger (real hashes); return entries as dicts."""
    led = Ledger(run_dir, "test-run")
    return [led.append(*ev).model_dump() for ev in events]


def turn(agent: str, rnd: int = 1, *, claims=(), actions=(), claimed=(), disclaimed=(),
         requests=(), insufficient=(), evidence=()) -> dict:
    """An agent_turn payload."""
    return {
        "agent_id": agent, "round": rnd, "evidence_clause_ids": list(evidence),
        "turn": {
            "situation_summary": "test", "claims": list(claims), "proposed_actions": list(actions),
            "requests": list(requests), "responsibilities_claimed": list(claimed),
            "responsibilities_disclaimed": list(disclaimed), "insufficient_evidence": list(insufficient),
            "uncertainties": [], "confidence": "medium",
        },
    }


def citation(agent: str, rnd: int, results: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {"agent_id": agent, "round": rnd, "results": results, "counts": counts}


def gate(agent: str, action_id: str, action_type: str, decision: str, *, enforced=True,
         events=(), rule_ids=(), state=None, mode=None) -> dict:
    code = {"ALLOW": 200, "DENY": 403, "ESCALATE": 202}[decision]
    return {"action_id": action_id, "agent_id": agent, "action_type": action_type, "decision": decision,
            "status_code": code, "mode": mode or ("governed" if enforced else "ungoverned"),
            "enforced": enforced, "rule_ids": list(rule_ids), "clause_id": None, "quote": None,
            "issuer": None, "url": None, "message": "", "state_facts": state or {},
            "events": list(events), "reason": ""}
