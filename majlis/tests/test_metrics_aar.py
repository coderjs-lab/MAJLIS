import subprocess
import sys
from pathlib import Path

from majlis.aar import render_aar
from majlis.gap_miner import mine
from majlis.ledger import Ledger, load_entries
from majlis.metrics import compute, unsupported_bases
from majlis import readiness
from tests.trust_helpers import citation, gate, turn

ROOT = Path(__file__).resolve().parents[1]


def _claim(cid, ctype="obligation", clause_id="TEST-DOC-A/art-2/en", quote="within 72 hours"):
    return {"claim_id": cid, "statement": "s", "claim_type": ctype, "clause_id": clause_id, "quote": quote}


def _action(aid, atype, basis):
    return {"action_id": aid, "action_type": atype, "description": "d", "legal_basis_claim_ids": basis,
            "urgency": "hours", "target": None}


def build_run(run_dir: Path, mode="governed") -> list[dict]:
    """A small synthetic run written through the real Ledger."""
    led = Ledger(run_dir, "run-test")
    ungov = mode == "ungoverned"
    led.append(None, "engine", "run_start", {
        "scenario_id": "S-TEST", "title": "Test scenario (fictional)", "disclaimer": "Fictional test run.",
        "mode": mode, "approver": "reject_all", "lang": "en", "model": "mock-model", "backend": "mock",
        "kb_version": "abc123", "agents": [],
        "stages": [{"id": "T1", "sim_time": "T+0", "title": "Outage", "recipients": ["triage", "doh"],
                    "expected": "Notify the regulator."}]})
    led.append("T1", "engine", "inject", {"stage_id": "T1", "sim_time": "T+0", "title": "Outage",
                                          "recipients": ["triage", "doh"], "text": "The test service is down.",
                                          "expected": "Notify the regulator.", "state_after": {}})
    led.append("T1", "mock", "llm_call", {"agent_id": "triage", "usage": {"prompt_tokens": 100, "completion_tokens": 20},
                                          "latency_ms": 5, "error": None})
    led.append("T1", "mock", "llm_call", {"agent_id": "doh", "usage": {}, "latency_ms": 7, "error": "bad json"})
    led.append("T1", "triage", "agent_turn", turn("triage", claims=[
        _claim("c1"),                                  # verified
        _claim("c2", quote="within 24 hours"),         # failed
        _claim("c3", ctype="fact_from_inject", clause_id=None, quote=None),
    ], actions=[
        _action("a1", "notify_regulator", ["c1"]),       # allowed, verified basis
        _action("a2", "share_logs", ["c2"]),             # escalated; executed only if not enforced
        _action("a3", "transfer_data", ["c2", "c9"]),    # denied; executed only if not enforced
        _action("a4", "send_status_update", ["c3"]),     # allowed, non-verified basis
    ], claimed=["notify_health_regulator"]))
    led.append("T1", "engine", "citation_check", citation("triage", 1, [
        {"claim_id": "c1", "clause_id": "TEST-DOC-A/art-2/en", "status": "VERIFIED", "score": 100.0},
        {"claim_id": "c2", "clause_id": "TEST-DOC-A/art-2/en", "status": "FAILED", "score": 40.0},
        {"claim_id": "c3", "clause_id": None, "status": "NO_CITATION", "score": 0.0},
    ]))
    led.append("T1", "gate", "gate_decision", gate("triage", "a1", "notify_regulator", "ALLOW", enforced=not ungov))
    led.append("T1", "gate", "gate_decision", gate("triage", "a2", "share_logs", "ESCALATE", enforced=not ungov,
                                                   events=["policy_void"], state={"service_down": True}))
    d = gate("triage", "a3", "transfer_data", "DENY", enforced=not ungov, rule_ids=["R1"])
    d.update(clause_id="TEST-DOC-A/art-1/en", quote="Health data of patients shall be stored", issuer="Test Issuer")
    led.append("T1", "gate", "gate_decision", d)
    led.append("T1", "gate", "gate_decision", gate("triage", "a4", "send_status_update", "ALLOW", enforced=not ungov))
    if not ungov:
        led.append("T1", "approver", "human_decision", {"action_id": "a2", "agent_id": "triage", "decision": "reject",
                                                        "approver": "simulated:reject_all", "rule_ids": []})
    led.append("T1", "engine", "stage_end", {"stage_id": "T1", "allowed": 2, "blocked": 1, "escalated": 1,
                                             "open_requests": [], "state": {}})
    for g in mine(load_entries(run_dir), [], {"needs": [{"id": "N1", "need": "n", "covered": False}]}):
        led.append(None, "gap_miner", "gap_candidate", g.model_dump())
    led.append(None, "engine", "run_end", {"status": "completed"})
    return load_entries(run_dir)


def test_metrics_governed(tmp_path):
    m = compute(build_run(tmp_path))
    assert m["citations"]["VERIFIED"] == 1 and m["citations"]["FAILED"] == 1
    assert m["citations"]["NO_CITATION"] == 1 and m["citations"]["verification_rate"] == 0.5
    assert m["gate"] == {"allow": 2, "deny": 1, "escalate": 1, "would_deny_let_through": 0,
                         "would_escalate_let_through": 0, "out_of_vocabulary": 0}
    assert m["human"] == {"approved": 0, "rejected": 1}
    assert m["unsupported_passed_as_fact"] == 1           # c3 behind allowed a4
    assert m["llm"] == {"calls": 2, "errors": 1, "prompt_tokens": 100, "completion_tokens": 20,
                        "latency_ms_total": 12}
    assert m["gaps"] == {"by_pattern": {"G1_POLICY_VOID": 1, "G5_STANDARDS": 1}, "total": 2,
                         "with_global_example": 0, "insufficient_evidence": 2}
    assert m["duties_first_identified"] == {"notify_health_regulator": "T1"}


def test_metrics_ungoverned_counts_let_through(tmp_path):
    entries = build_run(tmp_path, mode="ungoverned")
    m = compute(entries)
    assert m["gate"]["would_deny_let_through"] == 1 and m["gate"]["would_escalate_let_through"] == 1
    # c2 (FAILED) behind a2 and a3, c9 (never checked) behind a3, c3 behind a4.
    assert m["unsupported_passed_as_fact"] == 3
    assert {(u["claim_id"], u["status"]) for u in unsupported_bases(entries)} == {
        ("c2", "FAILED"), ("c9", "NOT_CHECKED"), ("c3", "NO_CITATION")}


def test_human_approval_executes_action(tmp_path):
    led = Ledger(tmp_path, "r")
    led.append("T1", "triage", "agent_turn", turn("triage", claims=[_claim("c1")],
                                                  actions=[_action("a1", "share_logs", ["c1"])]))
    led.append("T1", "engine", "citation_check", citation("triage", 1, [
        {"claim_id": "c1", "clause_id": "TEST-DOC-A/art-2/en", "status": "NEAR_MATCH", "score": 95.0}]))
    led.append("T1", "gate", "gate_decision", gate("triage", "a1", "share_logs", "ESCALATE"))
    assert compute(load_entries(tmp_path))["unsupported_passed_as_fact"] == 0
    led.append("T1", "approver", "human_decision", {"action_id": "a1", "agent_id": "triage", "decision": "approve",
                                                    "approver": "human:test", "rule_ids": []})
    assert compute(load_entries(tmp_path))["unsupported_passed_as_fact"] == 1


def test_aar_renders_from_ledger(tmp_path):
    entries = build_run(tmp_path)
    md = render_aar(entries)
    assert md.startswith("# After-Action Report: Test scenario (fictional)")
    assert "Fictional test run." in md
    assert "verified, " in md and "BROKEN" not in md
    for section in ("## Stages", "## Gate decisions", "## Citation integrity", "## Gap candidates",
                    "## Metrics", "## Limitations"):
        assert section in md
    assert "triage: TEST-DOC-A/art-2/en" in md            # key verified claim in the stage table
    assert "DENY 403" in md and "TEST-DOC-A/art-1/en (Test Issuer)" in md
    assert "reject by simulated:reject_all" in md
    assert "G1-001" in md and "INSUFFICIENT EVIDENCE" in md
    assert "mock-model / mock" in md
    assert render_aar(entries) == md                        # deterministic


def test_aar_reports_broken_chain(tmp_path):
    entries = build_run(tmp_path)
    entries[3]["payload"]["latency_ms"] = 999
    assert "BROKEN at seq 3" in render_aar(entries)


def test_ledger_from_run_verifies_with_script(tmp_path):
    build_run(tmp_path)
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "verify_ledger.py"), str(tmp_path)],
                         capture_output=True, text=True)
    assert out.returncode == 0 and out.stdout.startswith("OK: chain verified")


def test_readiness_reference_model():
    names = readiness.dimension_names()
    assert len(names) == 13 and names[10] == "AI & Policies" and names[13] == "Digital Infrastructure"
    assert (10, 7, 0.5) in readiness.edges()
    effect = readiness.propagate(10, 1.0, depth=2)
    assert effect[10] == 1.0 and effect[7] == 0.5
    assert effect[12] == 0.125                              # 10 -> 7 -> 12: 1.0 * 0.5 * 0.5 * 0.5
    assert readiness.propagate(10, 1.0, depth=1) == {10: 1.0, 7: 0.5, 8: 0.3}
