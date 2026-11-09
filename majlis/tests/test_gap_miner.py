from pathlib import Path

import yaml

from majlis import gap_miner
from majlis.gap_miner import extract_deadlines, mine
from tests.trust_helpers import citation, gate, turn, write_ledger

ROOT = Path(__file__).resolve().parents[1]
DUTIES = ["notify_data_protection_authority", "notify_health_regulator", "report_network_outage",
          "inform_affected_patients"]


def _claim(cid, clause_id, quote):
    return {"claim_id": cid, "statement": "s", "claim_type": "obligation", "clause_id": clause_id, "quote": quote}


def _verified(cid, clause_id):
    return {"claim_id": cid, "clause_id": clause_id, "status": "VERIFIED", "score": 100.0}


def test_g1_policy_void(tmp_path):
    entries = write_ledger(tmp_path, [
        ("T1", "engine", "inject", {"stage_id": "T1"}),
        ("T2", "gate", "gate_decision", gate("triage", "a1", "share_logs", "ESCALATE", events=["policy_void"],
                                             state={"service_down": True})),
        ("T2", "gate", "gate_decision", gate("triage", "a2", "share_logs", "ESCALATE", events=["policy_void"],
                                             state={"service_down": True})),
    ])
    gaps = mine(entries, DUTIES, {})
    assert len(gaps) == 1
    g = gaps[0]
    assert g.gap_id == "G1-001" and g.pattern == "G1_POLICY_VOID" and g.type == "policy"
    assert g.evidence.ledger_seqs == [1, 2]
    assert g.readiness_dimensions == [10, 7]
    assert "`share_logs`" in g.description and "`triage`" in g.description and "T2" in g.description
    assert "fail-closed" in g.description


def test_g1_same_question_from_two_agents(tmp_path):
    entries = write_ledger(tmp_path, [
        ("T2", "triage", "agent_turn", turn("triage", insufficient=["Who approves failover of health data abroad?"])),
        ("T2", "doh", "agent_turn", turn("doh", insufficient=["who approves  failover of health data abroad"])),
        ("T2", "tdra", "agent_turn", turn("tdra", insufficient=["Unrelated question about spectrum"])),
    ])
    gaps = gap_miner.detect_g1_questions(entries, gap_miner._Ids(), gap_miner.READINESS_DIMENSIONS)
    assert len(gaps) == 1
    assert gaps[0].detail["agents"] == ["triage", "doh"] and gaps[0].evidence.ledger_seqs == [0, 1]


def test_g1_question_from_one_agent_is_not_a_gap(tmp_path):
    entries = write_ledger(tmp_path, [
        ("T2", "triage", "agent_turn", turn("triage", insufficient=["Q one"])),
        ("T3", "triage", "agent_turn", turn("triage", 2, insufficient=["Q one"])),
    ])
    assert mine(entries, DUTIES, {}) == []


def test_g2_conflict(tmp_path):
    entries = write_ledger(tmp_path, [
        ("T2", "gate", "gate_decision", gate("triage", "a1", "failover_region", "ESCALATE", events=["conflict"],
                                             rule_ids=["R-DENY", "R-REQ"])),
    ])
    gaps = gap_miner.detect_g2(entries, gap_miner._Ids(), gap_miner.READINESS_DIMENSIONS)
    assert len(gaps) == 1 and gaps[0].gap_id == "G2-001" and gaps[0].readiness_dimensions == [10, 4]
    assert "`R-DENY`" in gaps[0].description


def test_g3_overlap_and_vacuum(tmp_path):
    entries = write_ledger(tmp_path, [
        ("T1", "doh", "agent_turn", turn("doh", claimed=["notify_health_regulator"],
                                         disclaimed=["notify_data_protection_authority"])),
        ("T1", "triage", "agent_turn", turn("triage", claimed=["notify_health_regulator"],
                                            requests=[{"to_agent": "data_office",
                                                       "question": "Who will inform affected patients?"}])),
        ("T1", "data_office", "agent_turn", turn("data_office", disclaimed=["notify_data_protection_authority"],
                                                 claimed=["report_network_outage", "not_a_duty"])),
    ])
    gaps = gap_miner.detect_g3(entries, DUTIES, gap_miner._Ids(), gap_miner.READINESS_DIMENSIONS)
    by_duty = {g.detail["duty"]: g for g in gaps}
    assert set(by_duty) == {"notify_health_regulator", "notify_data_protection_authority",
                            "inform_affected_patients"}
    overlap = by_duty["notify_health_regulator"]
    assert overlap.detail["kind"] == "overlap" and overlap.evidence.ledger_seqs == [0, 1]
    vac = by_duty["notify_data_protection_authority"]
    assert vac.detail["kind"] == "vacuum" and vac.detail["disclaimed_by"] == ["doh", "data_office"]
    assert by_duty["inform_affected_patients"].detail["requested_by"] == ["triage"]
    assert [g.gap_id for g in gaps] == ["G3-001", "G3-002", "G3-003"]
    assert all(g.readiness_dimensions == [7, 10] for g in gaps)


def test_extract_deadlines():
    assert extract_deadlines("within 72 hours of becoming aware") == ["72 hours"]
    assert extract_deadlines("within 24-hour") == ["24 hours"]
    assert extract_deadlines("without undue delay and not later than 72 hours") == ["72 hours", "without undue delay"]
    assert extract_deadlines("within 5 business days") == ["5 business days"]
    assert extract_deadlines("خلال 72 ساعة من علمه") == ["72 hours"]
    assert extract_deadlines("خلال ٣ أيام") == ["3 days"]
    assert extract_deadlines("فوراً ودون تأخير") == ["immediately", "without undue delay"]
    assert extract_deadlines("leader by 2031") == []


def _clock_ledger(tmp_path, claims, results):
    return write_ledger(tmp_path, [
        ("T2", "doh", "agent_turn", turn("doh", claims=claims)),
        ("T2", "engine", "citation_check", citation("doh", 1, results)),
    ])


def test_g4_72h_vs_24h_vs_undue_delay(tmp_path):
    claims = [
        _claim("c1", "TEST-DOC-A/art-2/en", "notify the test office of any personal data breach within 72 hours"),
        _claim("c2", "TEST-DOC-C/art-7/en", "report any major network outage to the test telecom authority within 24 hours"),
        _claim("c3", "TEST-DOC-B/sec-4/en", "shall be reported to the test health regulator without undue delay"),
    ]
    entries = _clock_ledger(tmp_path, claims, [_verified(c["claim_id"], c["clause_id"]) for c in claims])
    gaps = mine(entries, DUTIES, {})
    assert len(gaps) == 1
    g = gaps[0]
    assert g.gap_id == "G4-001" and g.pattern == "G4_CLOCK" and g.readiness_dimensions == [7, 3]
    assert g.detail["deadlines_by_doc"] == {"TEST-DOC-A": ["72 hours"], "TEST-DOC-B": ["without undue delay"],
                                            "TEST-DOC-C": ["24 hours"]}
    assert g.evidence.clause_ids == sorted(c["clause_id"] for c in claims)
    assert g.evidence.ledger_seqs == [0, 1]


def test_g4_ignores_unverified_claims(tmp_path):
    claims = [
        _claim("c1", "TEST-DOC-A/art-2/en", "within 72 hours"),
        _claim("c2", "TEST-DOC-C/art-7/en", "within 24 hours"),
    ]
    results = [_verified("c1", "TEST-DOC-A/art-2/en"),
               {"claim_id": "c2", "clause_id": "TEST-DOC-C/art-7/en", "status": "NEAR_MATCH", "score": 95.0}]
    assert mine(_clock_ledger(tmp_path, claims, results), DUTIES, {}) == []


def test_g4_same_deadline_or_same_doc_is_not_a_gap(tmp_path):
    claims = [
        _claim("c1", "TEST-DOC-A/art-2/en", "within 72 hours"),
        _claim("c2", "TEST-DOC-A/art-2/ar", "خلال 72 ساعة"),       # same doc, same clock
        _claim("c3", "TEST-EU/art-33/en", "not later than 72 hours"),
    ]
    entries = _clock_ledger(tmp_path, claims, [_verified(c["claim_id"], c["clause_id"]) for c in claims])
    assert mine(entries, DUTIES, {}) == []


def test_g5_from_fixture_shape():
    coverage = {"needs": [
        {"id": "N1", "need": "Need one", "standard": "ITU-T-Y3172", "section": "8.1", "quote": "q",
         "covered": False, "note": "Nothing addresses it.", "readiness_dimensions": [6, 9], "proposal": "HA"},
        {"id": "N2", "need": "Need two", "standard": "ITU-T-Y3173", "section": "7", "quote": None,
         "covered": "partial", "note": "Touches it.", "readiness_dimensions": [], "proposal": None},
        {"id": "N3", "need": "Need three", "standard": "ITU-T-Y3172", "covered": True},
    ]}
    gaps = mine([], DUTIES, coverage)
    assert [g.gap_id for g in gaps] == ["G5-001", "G5-002"]
    a, b = gaps
    assert a.type == "standards" and a.confidence == "medium" and a.readiness_dimensions == [6, 9]
    assert a.title == "ITU-T Y.3172 does not specify: Need one"
    assert "Nothing addresses it." in a.description
    assert a.detail["proposal"] == "HA" and a.detail["quote"] == "q" and a.detail["section"] == "8.1"
    assert b.confidence == "low" and b.title == "ITU-T Y.3173 only partly specifies: Need two"
    assert b.readiness_dimensions == [10, 13]   # default map when the row gives none
    assert a.evidence.clause_ids == []


def test_g5_real_config_loads():
    path = ROOT / "configs" / "standards_coverage.yaml"
    coverage = yaml.safe_load(path.read_text(encoding="utf-8"))
    gaps = mine([], DUTIES, coverage)
    expected = [n for n in coverage["needs"] if n.get("covered") is not True]
    assert len(gaps) == len(expected)
    assert all(g.pattern == "G5_STANDARDS" and g.readiness_dimensions for g in gaps)


def test_dimension_override():
    gaps = mine([], DUTIES, {"pattern_dimensions": {"G5": [1]},
                             "needs": [{"id": "N", "need": "n", "covered": False}]})
    assert gaps[0].readiness_dimensions == [1]


def test_mine_is_deterministic(tmp_path):
    entries = write_ledger(tmp_path, [
        ("T1", "doh", "agent_turn", turn("doh", claimed=["notify_health_regulator"])),
        ("T1", "tdra", "agent_turn", turn("tdra", claimed=["notify_health_regulator"])),
    ])
    assert [g.model_dump() for g in mine(entries, DUTIES, {})] == [g.model_dump() for g in mine(entries, DUTIES, {})]
