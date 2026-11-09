"""LLM layer tests. Offline only: the GLM endpoint is never contacted."""
import json

import pytest

from majlis import llm
from majlis.schemas import AdviceAnswer, AgentTurn, EvidenceItem


@pytest.fixture(autouse=True)
def _mock_backend(monkeypatch):
    monkeypatch.setenv("MAJLIS_BACKEND", "mock")


def _ev(cid="TEST-DOC-A/art-2/en", text="The controller shall notify the test office of any breach. Second sentence.",
        jurisdiction="AE", binding="binding"):
    return EvidenceItem(clause_id=cid, doc_id=cid.split("/")[0], doc_title="Test doc", issuer="Test", jurisdiction=jurisdiction,
                        instrument_type="test_fixture", binding=binding, article="2", url="https://example.invalid",
                        text=text)


def _ctx(stage="T1", **kw):
    c = {"agent_id": "triage", "kind": "application", "stage": stage, "round": 1, "evidence": [_ev()],
         "vocabulary": ["continue_triage", "suspend_ai_triage", "fallback_to_human", "notify_regulator"],
         "duties": ["notify_health_regulator", "suspend_ai_service", "require_human_fallback"],
         "can_message": ["legal_adviser", "doh"],
         "inject_text": "Synthetic telemetry: under-triage rate for chest-pain cases rose."}
    c.update(kw)
    return c


def test_mock_turn_is_valid_and_quotes_verbatim():
    r = llm.structured_call("sys", "user", AgentTurn, purpose="agent_turn", agent_id="triage", context=_ctx())
    assert r.error is None and r.backend == "mock" and r.attempts == 1
    t = r.parsed
    assert isinstance(t, AgentTurn)
    legal = [c for c in t.claims if c.clause_id]
    assert legal and legal[0].quote == "The controller shall notify the test office of any breach."
    assert t.proposed_actions[0].action_type == "continue_triage"
    assert all(a.action_type in _ctx()["vocabulary"] for a in t.proposed_actions)
    assert set(t.responsibilities_claimed + t.responsibilities_disclaimed) <= set(_ctx()["duties"])
    assert json.loads(r.raw_text)["situation_summary"].startswith("[mock]")
    assert r.prompt_sha256 == llm.prompt_hash(r.system, "user")
    assert "OUTPUT FORMAT" in r.system and "situation_summary" in r.system


def test_mock_is_deterministic_and_stage_dependent():
    a = llm.structured_call("s", "u", AgentTurn, purpose="p", agent_id="tdra", context=_ctx("T0", agent_id="tdra"))
    b = llm.structured_call("s", "u", AgentTurn, purpose="p", agent_id="tdra", context=_ctx("T0", agent_id="tdra"))
    assert a.raw_text == b.raw_text
    assert a.parsed.requests and a.parsed.requests[0].to_agent == "legal_adviser"
    t3 = llm.structured_call("s", "u", AgentTurn, purpose="p", agent_id="tdra", context=_ctx("T3"))
    quotes = [c.quote for c in t3.parsed.claims if c.clause_id]
    assert quotes[0] != "The controller shall notify the test office of any breach."  # altered on T3


def test_mock_advice_valid():
    ctx = {"agent_id": "legal_adviser", "stage": "T0", "question": "Q?",
           "evidence": [_ev(), _ev("TEST-DOC-C/art-7/en", "Other rule text here.", jurisdiction="EU")]}
    r = llm.structured_call("s", "u", AdviceAnswer, purpose="advice", agent_id="legal_adviser", context=ctx)
    a = r.parsed
    assert isinstance(a, AdviceAnswer) and not a.insufficient_evidence
    assert a.global_examples[0].clause_id == "TEST-DOC-C/art-7/en"
    empty = llm.structured_call("s", "u", AdviceAnswer, purpose="advice", agent_id="legal_adviser",
                                context={"question": "Q?", "evidence": []}).parsed
    assert empty.insufficient_evidence and not empty.claims


def test_glm_body_shape(monkeypatch):
    monkeypatch.setenv("MAJLIS_MODEL", "glm-test")
    body = llm.build_glm_body("SYS", "USER", effort="medium")
    assert body == {
        "model": "glm-test",
        "messages": [{"role": "system", "content": "SYS"}, {"role": "user", "content": "USER"}],
        "response_format": {"type": "json_object"},
        "thinking": {"type": "enabled"},
        "reasoning_effort": "high",
        "max_tokens": 8000,
    }
    assert llm.build_glm_body("S", "U", effort="max")["reasoning_effort"] == "max"
    assert llm.build_glm_body("S", "U", effort="weird")["reasoning_effort"] == "low"
    monkeypatch.setenv("MAJLIS_GLM_BASE_URL", "https://example.invalid/v4/")
    assert llm.glm_url() == "https://example.invalid/v4/chat/completions"


def test_glm_validation_retry_without_network(monkeypatch):
    """The repair loop: first output invalid, second valid. _glm_request is stubbed (no HTTP)."""
    monkeypatch.setenv("MAJLIS_BACKEND", "glm")
    calls = []
    good = json.dumps({"situation_summary": "ok"})

    def fake(body):
        calls.append(body)
        return ("```json\n{\"claims\": 3}\n```" if len(calls) == 1 else good), {"prompt_tokens": 5}, 1

    monkeypatch.setattr(llm, "_glm_request", fake)
    r = llm.structured_call("S", "U", AgentTurn, purpose="p", agent_id="x", effort="low")
    assert r.parsed is not None and r.error is None and r.attempts == 2
    assert "FAILED VALIDATION" in calls[1]["messages"][1]["content"]
    assert r.usage["prompt_tokens"] == 10

    calls.clear()
    monkeypatch.setattr(llm, "_glm_request", lambda body: ("not json", {}, 1))
    r = llm.structured_call("S", "U", AgentTurn, purpose="p", agent_id="x")
    assert r.parsed is None and r.error and r.attempts == 2


def test_extract_json_strips_fences():
    assert llm.extract_json("```json\n{\"a\": 1}\n```") == '{"a": 1}'
    assert llm.extract_json("Here: {\"a\": 1} done") == '{"a": 1}'


def test_schema_example_has_all_fields():
    ex = llm.schema_example(AgentTurn)
    assert set(ex) == set(AgentTurn.model_fields)
    assert set(ex["claims"][0]) == {"claim_id", "statement", "claim_type", "clause_id", "quote"}
