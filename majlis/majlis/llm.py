"""LLM layer: one function, `structured_call`, two backends (glm, mock).

The LLM only proposes. Everything it returns is validated against a Pydantic
schema here and then checked again by deterministic code (citation checker,
policy gate). Secrets: the API key is read from the environment / .env and is
never logged, printed or stored in an LLMResult.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, get_args, get_origin

from pydantic import BaseModel, ValidationError

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_URL = "https://api.z.ai/api/paas/v4"
DEFAULT_MODEL = "glm-5.3"
MAX_TOKENS = 8000
HTTP_TIMEOUT_S = 300.0
MAX_HTTP_RETRIES = 3
MOCK_MODEL = "mock"

_ENV_LOADED = False


def load_env() -> None:
    """Load .env from the project root, then ../../.env, never overriding the
    existing environment. Values are not printed."""
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    try:
        from dotenv import load_dotenv
        for p in (ROOT / ".env", ROOT.parent.parent / ".env"):
            if p.is_file():
                load_dotenv(p, override=False)
    except Exception:  # pragma: no cover - dotenv missing is not fatal
        pass
    _ENV_LOADED = True


@dataclass
class LLMResult:
    parsed: Optional[BaseModel]
    raw_text: str
    usage: dict
    prompt_sha256: str
    latency_ms: int
    model: str
    backend: str
    attempts: int
    error: Optional[str]
    # extras for the ledger (the exact prompt that was sent)
    system: str = ""
    user: str = ""
    effort: str = "low"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def backend_name() -> str:
    load_env()
    b = (os.environ.get("MAJLIS_BACKEND") or "").strip().lower()
    if b in ("glm", "mock"):
        return b
    return "glm" if os.environ.get("GLM_API_KEY") else "mock"


def model_name() -> str:
    load_env()
    return os.environ.get("MAJLIS_MODEL") or DEFAULT_MODEL


def normalise_effort(effort: str | None) -> str:
    e = (effort or os.environ.get("MAJLIS_EFFORT") or "low").strip().lower()
    if e == "medium":
        return "high"
    return e if e in ("low", "high", "max") else "low"


def prompt_hash(system: str, user: str) -> str:
    return hashlib.sha256((system + "\n\n" + user).encode("utf-8")).hexdigest()


def _resolve(node: dict, defs: dict) -> dict:
    ref = node.get("$ref")
    if ref:
        return defs.get(ref.split("/")[-1], {})
    return node


def _placeholder(node: dict, defs: dict, name: str, depth: int = 0) -> Any:
    node = _resolve(node, defs)
    if "anyOf" in node:
        non_null = [n for n in node["anyOf"] if n.get("type") != "null"]
        return _placeholder(non_null[0], defs, name, depth) if non_null else None
    if "enum" in node:
        return node["enum"][0]
    if "const" in node:
        return node["const"]
    t = node.get("type")
    if t == "object" or "properties" in node:
        if depth > 4:
            return {}
        return {k: _placeholder(v, defs, k, depth + 1) for k, v in node.get("properties", {}).items()}
    if t == "array":
        return [_placeholder(node.get("items", {}), defs, name, depth + 1)]
    if t == "boolean":
        return False
    if t in ("integer", "number"):
        return 0
    return f"<{name}>"


def schema_example(schema: type[BaseModel]) -> dict:
    js = schema.model_json_schema()
    return _placeholder(js, js.get("$defs", {}), schema.__name__)


def schema_block(schema: type[BaseModel]) -> str:
    js = schema.model_json_schema()
    return (
        "OUTPUT FORMAT\n"
        f"Return one JSON object (no prose, no code fences) that validates against this JSON Schema "
        f"({schema.__name__}):\n"
        + json.dumps(js, ensure_ascii=False, separators=(",", ":"))
        + "\nShape example (field names only; placeholder values, replace them):\n"
        + json.dumps(schema_example(schema), ensure_ascii=False, separators=(",", ":"))
    )


_FENCE = re.compile(r"^\s*```(?:json|JSON)?\s*(.*?)\s*```\s*$", re.S)


def extract_json(text: str) -> str:
    t = (text or "").strip()
    m = _FENCE.match(t)
    if m:
        t = m.group(1).strip()
    if not t.startswith("{"):
        i, j = t.find("{"), t.rfind("}")
        if i != -1 and j > i:
            t = t[i:j + 1]
    return t


def parse_and_validate(text: str, schema: type[BaseModel]) -> BaseModel:
    return schema.model_validate(json.loads(extract_json(text)))


def build_glm_body(system: str, user: str, *, model: str | None = None, effort: str | None = None) -> dict:
    """The exact request body sent to the GLM chat-completions endpoint."""
    return {
        "model": model or model_name(),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_object"},
        "thinking": {"type": "enabled"},
        "reasoning_effort": normalise_effort(effort),
        "max_tokens": MAX_TOKENS,
    }


def glm_url() -> str:
    load_env()
    base = (os.environ.get("MAJLIS_GLM_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    return f"{base}/chat/completions"


# ---------------------------------------------------------------------------
# GLM backend
# ---------------------------------------------------------------------------

class _HTTPFailure(Exception):
    pass


def _glm_request(body: dict) -> tuple[str, dict, int]:
    """POST once (with retries on 429/5xx). Returns (content, usage, http_attempts)."""
    import httpx

    load_env()
    key = os.environ.get("GLM_API_KEY")
    if not key:
        raise _HTTPFailure("GLM_API_KEY is not set")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    attempts = 0
    last = ""
    with httpx.Client(timeout=HTTP_TIMEOUT_S) as client:
        for i in range(MAX_HTTP_RETRIES):
            attempts += 1
            try:
                r = client.post(glm_url(), headers=headers, json=body)
            except httpx.HTTPError as e:  # network error: retry
                last = f"{type(e).__name__}"
                time.sleep(2 ** i)
                continue
            if r.status_code == 429 or r.status_code >= 500:
                last = f"HTTP {r.status_code}"
                time.sleep(2 ** (i + 1))
                continue
            if r.status_code >= 400:
                raise _HTTPFailure(f"HTTP {r.status_code}: {r.text[:300]}")
            data = r.json()
            try:
                content = data["choices"][0]["message"]["content"] or ""
            except (KeyError, IndexError, TypeError):
                raise _HTTPFailure("unexpected response shape")
            return content, dict(data.get("usage") or {}), attempts
    raise _HTTPFailure(f"retries exhausted ({last})")


def _call_glm(system: str, user: str, schema: type[BaseModel], effort: str) -> LLMResult:
    model = model_name()
    t0 = time.monotonic()
    usage: dict = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    attempts = 0
    raw = ""
    error: str | None = None
    cur_user = user
    for attempt in range(2):
        body = build_glm_body(system, cur_user, model=model, effort=effort)
        try:
            raw, u, n = _glm_request(body)
        except _HTTPFailure as e:
            attempts += 1
            error = f"http: {e}"
            break
        attempts += n
        for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
            usage[k] = usage.get(k, 0) + int(u.get(k) or 0)
        try:
            parsed = parse_and_validate(raw, schema)
            return LLMResult(parsed, raw, usage, prompt_hash(system, user), int((time.monotonic() - t0) * 1000),
                             model, "glm", attempts, None, system, user, effort)
        except (ValidationError, json.JSONDecodeError, ValueError) as e:
            error = f"validation: {str(e)[:1500]}"
            if attempt == 0:
                cur_user = (user + "\n\nYOUR PREVIOUS OUTPUT FAILED VALIDATION:\n" + error +
                            "\nReturn only one JSON object that validates against the schema.")
    return LLMResult(None, raw, usage, prompt_hash(system, user), int((time.monotonic() - t0) * 1000),
                     model, "glm", attempts, error, system, user, effort)


# ---------------------------------------------------------------------------
# Mock backend (offline, deterministic)
# ---------------------------------------------------------------------------

_SENT = re.compile(r"(?<=[.!?؟;])\s+")

# keyword -> action triggers (lowercase substrings of the inject / question)
_ACTION_KEYWORDS: dict[str, list[str]] = {
    "continue_triage": ["telemetry", "under-triage", "triage rate", "misdiagnos", "restored", "nurses"],
    "suspend_ai_triage": ["ransomware", "misdiagnos"],
    "fallback_to_human": ["under-triage", "nurses", "misdiagnos"],
    "process_in_region": ["restored", "replicated", "backup region"],
    "notify_regulator": ["ransomware", "cyber", "misdiagnos", "under-triage"],
    "notify_patients": ["misdiagnos", "family", "journalist", "patients were told"],
    "deploy_model_update": ["model update", "update"],
    "share_logs": ["logs"],
    "request_suspension": ["under-triage", "misdiagnos"],
    "require_human_fallback": ["under-triage", "nurses", "chest-pain"],
    "request_incident_report": ["outage", "ransomware", "misdiagnos", "under-triage"],
    "require_revalidation": ["restored", "model update", "drift"],
    "issue_guidance": ["social-media", "social media", "journalist", "public"],
    "request_patient_notification": ["misdiagnos", "family", "journalist"],
    "request_outage_report": ["outage", "fibre", "power"],
    "coordinate_operator": ["failover", "failed over", "outage", "restored"],
    "issue_advisory": ["cyber", "ransomware"],
    "request_breach_notification": ["replicated", "ransomware", "breach", "logs"],
    "order_processing_halt": ["replicated", "overseas"],
    "request_transfer_justification": ["replicated", "overseas", "abroad", "logs", "outside the uae"],
}
_SAFETY_WORDS = ["under-triage", "chest-pain", "misdiagnos", "telemetry", "nurses"]

# duty -> trigger keywords
_DUTY_KEYWORDS: dict[str, list[str]] = {
    "report_network_outage": ["outage", "fibre", "failover", "failed over"],
    "notify_health_regulator": ["under-triage", "misdiagnos", "telemetry"],
    "suspend_ai_service": ["under-triage", "misdiagnos", "ransomware"],
    "require_human_fallback": ["under-triage", "nurses"],
    "notify_data_protection_authority": ["replicated", "breach", "ransomware", "logs"],
    "approve_data_transfer": ["replicated", "overseas", "outside the uae", "logs"],
    "report_cyber_incident": ["ransomware", "cyber"],
    "inform_affected_patients": ["misdiagnos", "family", "journalist", "patients were told"],
    "coordinate_public_communication": ["social-media", "social media", "journalist", "public"],
    "approve_model_update": ["model update"],
    "revalidate_model": ["restored", "model update", "drift"],
    "investigate_root_cause": ["ransomware", "outage"],
}
# which duties each simulated role believes it owns (mock only; G3 overlap on
# coordinate_public_communication, vacuum on inform_affected_patients)
_MOCK_HOME_DUTIES: dict[str, set[str]] = {
    "tdra": {"report_network_outage", "coordinate_public_communication", "investigate_root_cause"},
    "doh": {"suspend_ai_service", "require_human_fallback", "revalidate_model", "approve_model_update",
            "coordinate_public_communication"},
    "data_office": {"approve_data_transfer"},
    "triage": {"notify_health_regulator", "notify_data_protection_authority", "report_network_outage"},
}
_MOCK_INSUFFICIENT = {
    "T1": "Is there a defined threshold of AI performance drift that makes it a reportable incident?",
    "T4": "Is there a duty to inform patients that an AI error affected their triage?",
}


def first_sentence(text: str, max_words: int = 60) -> str:
    s = _SENT.split((text or "").strip(), maxsplit=1)[0].strip()
    words = s.split()
    if len(words) > max_words:
        s = " ".join(words[:max_words])
    return s


def _alter(quote: str) -> str:
    """Slight deterministic change so the checker sees a NEAR_MATCH/FAILED."""
    words = quote.split()
    if not words:
        return "altered"
    i = len(words) // 2
    w = words[i]
    words[i] = (w[::-1] if len(w) > 3 and w[::-1] != w else w + "x")
    return " ".join(words)


def _ev(item: Any) -> dict:
    if isinstance(item, BaseModel):
        return item.model_dump()
    return dict(item)


def _mock_turn(ctx: dict) -> dict:
    agent = ctx.get("agent_id", "agent")
    stage = str(ctx.get("stage", "T?"))
    rnd = int(ctx.get("round", 1))
    # round 2 reacts only to the messages received this stage, not to the inject again
    text = ((ctx.get("inject_text") or "") if rnd == 1 else "") + " " + " ".join(ctx.get("messages") or [])
    low = text.lower()
    evidence = [_ev(e) for e in (ctx.get("evidence") or [])]
    vocab = list(ctx.get("vocabulary") or [])
    duties = list(ctx.get("duties") or [])
    can_message = list(ctx.get("can_message") or [])
    kind = ctx.get("kind", "institution")

    claims: list[dict] = [{
        "claim_id": "c1", "statement": f"[mock] {agent} received new information at {stage}.",
        "claim_type": "fact_from_inject", "clause_id": None, "quote": None,
    }]
    basis: list[str] = []
    if evidence:
        top = evidence[0]
        q = first_sentence(top.get("text", ""))
        legal = top.get("binding") == "binding"
        if stage == "T3":
            q = _alter(q)
        claims.append({
            "claim_id": "c2",
            "statement": f"[mock] {top.get('doc_title', '')} art. {top.get('article') or '?'} appears relevant.",
            "claim_type": "obligation" if legal else "recommendation",
            "clause_id": top.get("clause_id"), "quote": q,
        })
        basis = ["c2"]
        if stage == "T3" and len(evidence) > 1:
            claims.append({
                "claim_id": "c3", "statement": "[mock] A second provision is cited with an invented quote.",
                "claim_type": "obligation", "clause_id": evidence[1].get("clause_id"),
                "quote": "[mock] this sentence does not appear in the clause",
            })
    if stage == "T4":
        claims.append({
            "claim_id": "c4", "statement": "[mock] Cites a clause that was never retrieved.",
            "claim_type": "recommendation", "clause_id": "MOCK-UNKNOWN/art-0", "quote": "not a real clause",
        })

    matched = [a for a in vocab if any(k in low for k in _ACTION_KEYWORDS.get(a, []))]
    if kind == "application":
        if any(k in low for k in _SAFETY_WORDS) and "continue_triage" in vocab:
            matched = ["continue_triage"] + [a for a in matched if a != "continue_triage"]
        if not matched and "continue_triage" in vocab:
            matched = ["continue_triage"]
    actions = [{
        "action_id": f"a{i + 1}", "action_type": a, "target": None,
        "description": f"[mock] {agent} proposes {a}.", "legal_basis_claim_ids": basis,
        "urgency": "immediate" if i == 0 else "hours",
    } for i, a in enumerate(matched[:2])]

    requests = []
    if rnd == 1 and stage in ("T0", "T2") and "legal_adviser" in can_message:
        requests.append({"to_agent": "legal_adviser",
                         "question": f"[mock] Which obligations, if any, does the {stage} event trigger for {agent}?"})

    triggered = [d for d in duties if any(k in low for k in _DUTY_KEYWORDS.get(d, []))]
    home = _MOCK_HOME_DUTIES.get(agent, set())
    claimed = [d for d in triggered if d in home]
    disclaimed = [d for d in triggered if d not in home]

    insufficient = [_MOCK_INSUFFICIENT[stage]] if stage in _MOCK_INSUFFICIENT and rnd == 1 else []
    return {
        "situation_summary": f"[mock] {agent} assessment for {stage} round {rnd}: {len(evidence)} evidence clauses, "
                             f"{len(actions)} proposed actions.",
        "claims": claims,
        "proposed_actions": actions,
        "requests": requests,
        "responsibilities_claimed": claimed,
        "responsibilities_disclaimed": disclaimed,
        "insufficient_evidence": insufficient,
        "uncertainties": ["[mock] offline mock backend output; not a model judgement."],
        "confidence": "low",
    }


def _mock_advice(ctx: dict) -> dict:
    q = ctx.get("question") or "[mock] question"
    evidence = [_ev(e) for e in (ctx.get("evidence") or [])]
    claims, examples = [], []
    if evidence:
        top = evidence[0]
        claims.append({
            "claim_id": "c1", "statement": f"[mock] {top.get('doc_title', '')} is the closest provision in EVIDENCE.",
            "claim_type": "obligation" if top.get("binding") == "binding" else "recommendation",
            "clause_id": top.get("clause_id"), "quote": first_sentence(top.get("text", "")),
        })
        foreign = [e for e in evidence if not str(e.get("jurisdiction", "")).startswith("AE")] or evidence
        ex = foreign[0]
        examples.append({
            "jurisdiction": ex.get("jurisdiction", ""), "instrument": ex.get("doc_title", ""),
            "clause_id": ex.get("clause_id"), "quote": first_sentence(ex.get("text", "")),
            "how_it_handles": "[mock] This provision addresses a comparable situation.",
        })
    return {
        "question": q,
        "answer_summary": f"[mock] Answer drawn from {len(evidence)} evidence clauses.",
        "claims": claims,
        "global_examples": examples,
        "suspected_gaps": ["[mock] No provision in EVIDENCE links this event to the other regimes."] if evidence else [],
        "insufficient_evidence": not evidence,
    }


def _mock_generic(schema: type[BaseModel], ctx: dict) -> dict:
    data = schema_example(schema)
    gap = ctx.get("gap") or {}
    for k in ("title", "description", "implication", "next_step"):
        if k in data:
            base = gap.get(k) or gap.get("title") or k
            data[k] = f"[mock] {base}" if k in ("title", "description") else f"[mock] {k.replace('_', ' ')} for {gap.get('gap_id', 'gap')}"
    if "global_examples" in data:
        adv = _mock_advice(ctx)
        data["global_examples"] = adv["global_examples"]
    if "insufficient_evidence" in data:
        data["insufficient_evidence"] = not ctx.get("evidence")
    return data


def _call_mock(system: str, user: str, schema: type[BaseModel], effort: str, context: dict | None) -> LLMResult:
    from majlis.schemas import AdviceAnswer, AgentTurn  # local import keeps llm.py importable alone

    t0 = time.monotonic()
    ctx = context or {}
    if issubclass(schema, AgentTurn):
        data = _mock_turn(ctx)
    elif issubclass(schema, AdviceAnswer):
        data = _mock_advice(ctx)
    else:
        data = _mock_generic(schema, ctx)
    raw = json.dumps(data, ensure_ascii=False)
    error = None
    try:
        parsed = schema.model_validate(data)
    except ValidationError as e:  # pragma: no cover - mock is built to validate
        parsed, error = None, f"validation: {e}"
    usage = {"prompt_tokens": (len(system) + len(user)) // 4, "completion_tokens": len(raw) // 4,
             "total_tokens": (len(system) + len(user) + len(raw)) // 4, "estimated": True}
    return LLMResult(parsed, raw, usage, prompt_hash(system, user), int((time.monotonic() - t0) * 1000),
                     MOCK_MODEL, "mock", 1, error, system, user, effort)


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def structured_call(system: str, user: str, schema: type[BaseModel], *, purpose: str, agent_id: str,
                    effort: str | None = None, context: dict | None = None) -> LLMResult:
    """Call the configured backend and return a schema-validated result.

    `system` is the frozen role prompt; the JSON schema block for `schema` is
    appended here so every backend sees the same format instructions.
    """
    eff = normalise_effort(effort)
    full_system = system.rstrip() + "\n\n" + schema_block(schema)
    if backend_name() == "glm":
        return _call_glm(full_system, user, schema, eff)
    return _call_mock(full_system, user, schema, eff, context)
