"""End-to-end S1 with the offline mock backend on the stub KB. No API key is used."""
import json
from pathlib import Path

import pytest

from majlis.engine import load_challenge_cards, load_scenario, run_scenario
from majlis.ledger import load_entries, verify_chain
from majlis.schemas import Stage

ROOT = Path(__file__).resolve().parents[1]
KB = ROOT / "tests" / "fixtures" / "kb"
RULES = ROOT / "tests" / "fixtures" / "rules_test.yaml"
SCEN = ROOT / "configs" / "scenarios" / "s1_failover.yaml"
DISCLAIMER = "Fictional training exercise. You simulate a role; this is not an official position of any real institution."


@pytest.fixture(autouse=True)
def _mock_backend(monkeypatch):
    monkeypatch.setenv("MAJLIS_BACKEND", "mock")


def _run(tmp_path, mode="governed", approver="reject_all", rules=RULES, **kw):
    return run_scenario(SCEN, mode=mode, approver=approver, lang=kw.pop("lang", "en"), runs_dir=tmp_path,
                        kb_dir=KB, rules_path=rules, **kw)


def _of(entries, et):
    return [e for e in entries if e["event_type"] == et]


def test_scenario_file():
    sc = load_scenario(SCEN)
    assert [s.id for s in sc.stages] == ["T0", "T1", "T2", "T3", "T4", "T5"]
    assert sc.stages[0].state_changes == {"failover_active": True}
    assert "triage" in sc.stages[2].recipients and sc.stages[2].state_changes["processing_location"] == "outside_AE"
    assert sc.stages[5].state_changes == {"processing_location": "AE", "primary_restored": True}
    assert DISCLAIMER in sc.disclaimer
    assert len(load_challenge_cards()) == 5


@pytest.mark.parametrize("mode", ["governed", "ungoverned"])
def test_s1_end_to_end(tmp_path, mode):
    rdir = _run(tmp_path, mode=mode)
    entries = load_entries(rdir / "ledger.jsonl")
    ok, n, broken = verify_chain(entries)
    assert ok and broken is None and n == len(entries)
    assert entries[0]["event_type"] == "run_start" and entries[-1]["event_type"] == "run_end"
    assert entries[-1]["payload"]["status"] == "completed"
    assert (rdir / "manifest.json").exists() and (rdir / "aar.md").read_text().strip()
    assert len(_of(entries, "stage_end")) == 6
    assert _of(entries, "gap_candidate") and _of(entries, "metrics")
    assert not _of(entries, "agent_error")
    gates = _of(entries, "gate_decision")
    assert gates
    if mode == "ungoverned":
        assert all(g["payload"]["enforced"] is False for g in gates)
    else:
        assert all(g["payload"]["enforced"] is True for g in gates)
    statuses = {r["status"] for e in _of(entries, "citation_check") for r in e["payload"]["results"]}
    assert {"VERIFIED", "NEAR_MATCH", "FAILED"} <= statuses
    # every llm_call carries the simulation disclaimer in its system prompt
    assert all(DISCLAIMER in e["payload"]["system"] for e in _of(entries, "llm_call"))


def test_inject_visibility(tmp_path):
    rdir = _run(tmp_path)
    entries = load_entries(rdir / "ledger.jsonl")
    injects = [(e["payload"]["recipients"], e["payload"]["text"], e["payload"]["text_ar"])
               for e in _of(entries, "inject")]
    calls = _of(entries, "llm_call")
    assert calls
    for c in calls:
        agent, user = c["payload"]["agent_id"], c["payload"]["user"]
        for recipients, en, ar in injects:
            if agent not in recipients:
                assert en not in user, f"{agent} saw a private inject"
                assert not ar or ar not in user


def _escalation_rules(tmp_path):
    p = tmp_path / "rules_esc.yaml"
    p.write_text("""
high_impact_actions: [deploy_model_update, share_logs]
rules:
  - rule_id: X-ESC-SAFETY
    status: verified
    review: test_fixture
    description: test-only escalation on the safety signal
    applies_when: {action_type: [continue_triage], state: {patient_safety_signal: true}}
    decision: ESCALATE
    clause_ids: [TEST-DOC-A/art-1/en]
  - rule_id: X-DENY-ABROAD
    status: verified
    review: test_fixture
    description: test-only deny while processing abroad
    applies_when: {action_type: [continue_triage, suspend_ai_triage], state: {processing_location: outside_AE}}
    decision: DENY
    clause_ids: [TEST-DOC-A/art-1/en]
""", encoding="utf-8")
    return p


def test_escalate_and_interactive_approval(tmp_path):
    rules = _escalation_rules(tmp_path)
    run_id = "interactive_run"
    appr = tmp_path / run_id / "approvals"
    appr.mkdir(parents=True)
    (appr / "triage-T1-r1-a1.json").write_text(json.dumps({"decision": "approve", "by": "tester"}))
    rdir = _run(tmp_path, approver="interactive", rules=rules, run_id=run_id, approval_timeout=0.2)
    entries = load_entries(rdir / "ledger.jsonl")
    assert verify_chain(entries)[0]
    humans = {e["payload"]["action_id"]: e["payload"] for e in _of(entries, "human_decision")}
    assert humans["triage-T1-r1-a1"]["decision"] == "approve"
    assert humans["triage-T1-r1-a1"]["approver"] == "human:tester"
    assert any(h["approver"] == "timeout" and h["decision"] == "reject" for h in humans.values())
    denies = [g["payload"] for g in _of(entries, "gate_decision") if g["payload"]["decision"] == "DENY"]
    assert denies and denies[0]["status_code"] == 403 and denies[0]["clause_id"] == "TEST-DOC-A/art-1/en"


def test_judge_inject_and_arabic(tmp_path):
    extra = [Stage(id="J1", sim_time="live", recipients=["doh", "data_office"],
                   inject_en="The overseas vendor requests raw logs for debugging.",
                   state_changes={"logs_requested_abroad": True})]
    rdir = _run(tmp_path, lang="ar", extra_stages=extra, extra_after="T3")
    entries = load_entries(rdir / "ledger.jsonl")
    stages = [e["payload"]["stage_id"] for e in _of(entries, "inject")]
    assert stages == ["T0", "T1", "T2", "T3", "J1", "T4", "T5"]
    j1 = [e for e in _of(entries, "inject") if e["payload"]["stage_id"] == "J1"][0]
    assert j1["payload"]["state_after"]["logs_requested_abroad"] is True
    sys_prompts = [e["payload"]["system"] for e in _of(entries, "llm_call")]
    assert all("Arabic" in s for s in sys_prompts)
    assert rdir.name.endswith("_ar")
