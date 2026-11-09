import pytest

from majlis.policy_gate import PolicyGate, load_policy_file, load_rules, quote_prefix, state_matches
from majlis.schemas import ProposedAction
from tests.trust_helpers import RULES_FILE, load_fake_kb

KB = load_fake_kb()
RULES, HIGH_IMPACT = load_policy_file(RULES_FILE)
VOCAB = {
    "triage": ["share_logs", "transfer_data", "failover_region", "suspend_service", "notify_regulator",
               "send_status_update", "rotate_keys", "restart_pod"],
    "doh": ["notify_regulator"],
}
GATE = PolicyGate(RULES, KB, HIGH_IMPACT, VOCAB)


def act(action_type, action_id="a1"):
    return ProposedAction(action_id=action_id, action_type=action_type, description="test")


# (case, agent, action_type, state, decision, status, reason, events, rule_ids)
TABLE = [
    ("out_of_vocabulary", "doh", "transfer_data", {}, "DENY", 403, "step1_out_of_vocabulary",
     ["out_of_vocabulary"], []),
    ("unknown agent", "nobody", "notify_regulator", {}, "DENY", 403, "step1_out_of_vocabulary",
     ["out_of_vocabulary"], []),
    ("conflict deny+require", "triage", "failover_region", {"service_down": True, "target_region": "eu-west"},
     "ESCALATE", 202, "step2_conflict", ["conflict"], ["T-DENY-FAILOVER-ABROAD", "T-REQUIRE-CONTINUITY"]),
    ("verified deny", "triage", "transfer_data", {"data_contains_phi": True}, "DENY", 403,
     "step3_verified_deny", [], ["T-DENY-TRANSFER"]),
    ("verified deny, list state", "triage", "failover_region", {"service_down": False, "target_region": "us-east"},
     "DENY", 403, "step3_verified_deny", [], ["T-DENY-FAILOVER-ABROAD"]),
    ("draft deny -> escalate", "triage", "suspend_service", {"patient_safety_risk": False}, "ESCALATE", 202,
     "step4_escalate", [], ["T-DRAFT-DENY-SUSPEND"]),
    ("escalate rule", "triage", "send_status_update", {"audience": "public"}, "ESCALATE", 202,
     "step4_escalate", [], ["T-ESC-PUBLIC"]),
    ("missing clause -> draft", "triage", "rotate_keys", {}, "ESCALATE", 202, "step4_escalate",
     ["rule_clause_missing"], ["T-DENY-MISSING-CLAUSE"]),
    ("allow only", "triage", "notify_regulator", {}, "ALLOW", 200, "step5_allow", [], ["T-ALLOW-NOTIFY"]),
    ("require only", "triage", "failover_region", {"service_down": True, "target_region": "local"},
     "ALLOW", 200, "step5_allow", [], ["T-REQUIRE-CONTINUITY"]),
    ("policy void (high impact)", "triage", "share_logs", {"service_down": True}, "ESCALATE", 202,
     "step6_policy_void", ["policy_void"], []),
    ("unless_state suppresses -> void", "triage", "transfer_data",
     {"data_contains_phi": True, "transfer_approved": True}, "ESCALATE", 202, "step6_policy_void",
     ["policy_void"], []),
    ("no rule (low impact)", "triage", "restart_pod", {}, "ALLOW", 200, "step7_no_rule", ["no_rule"], []),
    ("state key missing -> no match", "triage", "send_status_update", {}, "ALLOW", 200, "step7_no_rule",
     ["no_rule"], []),
]


@pytest.mark.parametrize("case,agent,action_type,state,decision,status,reason,events,rule_ids", TABLE,
                         ids=[t[0] for t in TABLE])
def test_decision_table(case, agent, action_type, state, decision, status, reason, events, rule_ids):
    d = GATE.decide(act(action_type), agent, state, "governed")
    assert (d.decision, d.status_code, d.reason) == (decision, status, reason)
    assert d.events == events
    assert sorted(d.rule_ids) == sorted(rule_ids)
    assert d.enforced is True and d.mode == "governed"


def test_verified_deny_carries_clause_quote_and_url():
    d = GATE.decide(act("transfer_data"), "triage", {"data_contains_phi": True}, "governed")
    clause = KB.get("TEST-DOC-A/art-1/en")
    assert d.clause_id == clause.clause_id
    assert d.issuer == clause.issuer and d.url == clause.url
    assert d.quote and clause.text.startswith(d.quote)        # verbatim prefix
    assert d.message == "Patient data must stay in the test state."
    assert d.state_facts == {"data_contains_phi": True, "transfer_approved": None}


def test_arabic_message():
    d = GATE.decide(act("transfer_data"), "triage", {"data_contains_phi": True}, "governed", lang="ar")
    assert d.message.startswith("يجب")
    # Falls back to English when the rule has no Arabic message.
    d = GATE.decide(act("notify_regulator"), "triage", {}, "governed", lang="ar")
    assert d.message == "Reporting is allowed."


def test_ungoverned_same_decision_not_enforced():
    for case, agent, action_type, state, decision, status, reason, *_ in TABLE:
        d = GATE.decide(act(action_type), agent, state, "ungoverned")
        assert (d.decision, d.status_code, d.reason) == (decision, status, reason), case
        assert d.enforced is False and d.mode == "ungoverned"


def test_accepts_dict_action():
    d = GATE.decide({"action_id": "x", "action_type": "notify_regulator", "description": "d"}, "triage", {})
    assert d.decision == "ALLOW" and d.action_id == "x"


def test_quote_prefix_is_verbatim():
    text = "one  two\tthree " + " ".join(f"w{i}" for i in range(100))
    q = quote_prefix(text, 60)
    assert text.startswith(q) and len(q.split()) == 60
    assert quote_prefix("short text", 60) == "short text"


def test_state_matches():
    assert state_matches({"a": [1, 2], "b": True}, {"a": 2, "b": True})
    assert not state_matches({"a": [1, 2]}, {"a": 3})
    assert not state_matches({"a": 1}, {})
    assert state_matches({}, {})


def test_loaders():
    assert [r.rule_id for r in load_rules(RULES_FILE)] == [r.rule_id for r in RULES]
    assert "share_logs" in HIGH_IMPACT and "restart_pod" not in HIGH_IMPACT
