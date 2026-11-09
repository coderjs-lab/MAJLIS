"""Synthetic runs for building the exercise console before real runs exist.

Writes two runs (governed + ungoverned) of the S1 failover story:
    tests/fixtures/runs/fixture_s1_governed/{ledger.jsonl,manifest.json,aar.md}
    tests/fixtures/runs/fixture_s1_ungoverned/{...}
and the fallback configs the console server reads when configs/* are not there yet:
    tests/fixtures/console_configs/{agents/*.yaml, scenarios/*.yaml, policies/uae_rules.yaml,
                                    gaps_verified.yaml (empty), standards_coverage.yaml}

Everything here is FICTIONAL. Clause ids point at the fake TEST-DOC-* fixture clauses in
tests/fixtures/kb/clauses/clauses.jsonl. No real law text is used.

Run: .venv/bin/python tests/fixtures/make_console_fixture.py
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests" / "fixtures"
GENESIS = "0" * 64
FIXTURE_TAG = "FIXTURE — synthetic data for UI development"
DISCLAIMER = ("Fictional exercise. OasisCare and all telemetry are invented; the institutional agents "
              "are simulations, not official positions, and nothing here is legal advice.")


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def load_clauses() -> dict:
    out = {}
    with open(FIX / "kb" / "clauses" / "clauses.jsonl", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                c = json.loads(line)
                out[c["clause_id"]] = c
    return out


CLAUSES = load_clauses()


def first_sentence(cid: str) -> str:
    return CLAUSES[cid]["text"]


# ---------------------------------------------------------------------------
# Cast and story
# ---------------------------------------------------------------------------
AGENTS = [
    {"id": "triage", "display_name": "OasisCare Triage", "display_name_ar": "أوايسس كير للفرز",
     "short_name": "TRI", "kind": "application",
     "mandate": "Fictional AI triage service of a fictional Abu Dhabi telehealth provider. System under test.",
     "mandate_verified": None},
    {"id": "doh", "display_name": "Department of Health – Abu Dhabi (simulated)",
     "display_name_ar": "دائرة الصحة – أبوظبي (محاكاة)", "short_name": "DoH", "kind": "institution",
     "mandate": "Health regulator for the emirate: patient safety, licensing of health services and oversight of AI in healthcare.",
     "mandate_verified": False},
    {"id": "tdra", "display_name": "TDRA (simulated)",
     "display_name_ar": "هيئة تنظيم الاتصالات والحكومة الرقمية (محاكاة)", "short_name": "TDRA",
     "kind": "institution",
     "mandate": "Telecommunications and digital government regulator: network outages, cloud and cyber incident coordination.",
     "mandate_verified": False},
    {"id": "data_office", "display_name": "UAE Data Office (simulated)",
     "display_name_ar": "مكتب الإمارات للبيانات (محاكاة)", "short_name": "UDO", "kind": "institution",
     "mandate": "Data protection authority: personal data processing, breaches and cross-border transfers.",
     "mandate_verified": False},
    {"id": "legal_adviser", "display_name": "Legal & Policy Adviser",
     "display_name_ar": "المستشار القانوني والسياساتي", "short_name": "LPA", "kind": "adviser",
     "mandate": "Answers questions from the other agents with cited clauses and global comparators. Does not decide.",
     "mandate_verified": False},
]
AG = {a["id"]: a for a in AGENTS}

INITIAL_STATE = {
    "primary_region_status": "up", "processing_location": "AE", "data_location": "AE",
    "failover_active": False, "transfer_approved": False, "patient_safety_risk": False,
    "ai_suspended": False, "human_fallback": False, "cyber_incident_suspected": False,
    "patient_harm_reported": False, "model_revalidated": False,
}

STAGES = [
    dict(id="T0", sim_time="06:10", title="Cloud region outage", recipients=["tdra"],
         text=("A power and fibre incident takes the primary cloud region of OasisCare's hosting provider offline. "
               "Automatic failover moves the triage service to a secondary region outside the UAE. "
               "Service is up; latency has doubled."),
         text_ar=("حادث في الطاقة والألياف الضوئية يُخرج منطقة الحوسبة السحابية الرئيسية لمزوّد استضافة أوايسس كير عن الخدمة. "
                  "ينقل التحويل التلقائي خدمة الفرز إلى منطقة ثانوية خارج الدولة. الخدمة تعمل، وزمن الاستجابة تضاعف."),
         state_changes={"primary_region_status": "down", "processing_location": "outside_AE", "failover_active": True},
         expected="TDRA logs the outage and asks who else is affected; no one else knows yet.",
         expected_ar="تسجّل الهيئة الانقطاع وتسأل عن الجهات المتأثرة؛ لا أحد غيرها يعلم بعد.",
         synthetic=False),
    dict(id="T1", sim_time="09:30", title="Under-triage in Arabic chest-pain cases", recipients=["doh", "triage"],
         text=("Synthetic monitoring telemetry: under-triage rate for Arabic-language chest-pain consultations has risen "
               "from 2% to 9% since failover. English-language cases are unchanged."),
         text_ar=("بيانات مراقبة اصطناعية: ارتفع معدل الفرز المنقوص لاستشارات ألم الصدر باللغة العربية من 2% إلى 9% منذ التحويل. "
                  "الحالات باللغة الإنجليزية دون تغيير."),
         state_changes={"undertriage_rate_ar_chest_pain": 0.09, "patient_safety_risk": True},
         expected="DoH asks for human fallback; the gate escalates continued AI triage to a human.",
         expected_ar="تطلب الدائرة التحويل إلى الطاقم البشري؛ وتُحال مواصلة الفرز الآلي إلى قرار بشري.",
         synthetic=True),
    dict(id="T2", sim_time="11:05", title="Records replicated to an overseas backup region",
         recipients=["data_office", "doh"],
         text=("The provider confirms that patient records, including triage transcripts, have been replicated to a "
               "backup region outside the UAE as part of failover. No transfer approval is on file."),
         text_ar=("يؤكد المزوّد أن سجلات المرضى، بما فيها محاضر الفرز، نُسخت إلى منطقة احتياطية خارج الدولة ضمن التحويل. "
                  "لا توجد موافقة نقل مسجّلة."),
         state_changes={"data_location": "outside_AE", "records_replicated_abroad": True},
         expected="Continued offshore processing is denied with the data-localisation clause; Data Office asks the adviser about emergency transfers.",
         expected_ar="تُرفض مواصلة المعالجة خارج الدولة استناداً إلى بند توطين البيانات؛ ويسأل مكتب البيانات المستشار عن النقل الطارئ.",
         synthetic=False),
    dict(id="T3", sim_time="13:20", title="National advisory: possible ransomware", recipients=["tdra", "data_office"],
         text=("A national cyber advisory warns that the hosting provider's backup region may be affected by a "
               "ransomware campaign. Indicators are unconfirmed."),
         text_ar=("تحذّر نشرة وطنية للأمن السيبراني من أن المنطقة الاحتياطية لمزوّد الاستضافة قد تكون متأثرة بحملة فدية. "
                  "المؤشرات غير مؤكدة."),
         state_changes={"cyber_incident_suspected": True},
         expected="TDRA and Data Office cite different reporting clocks; isolating the backup conflicts with continuity of care.",
         expected_ar="تستند الهيئة ومكتب البيانات إلى مهل إبلاغ مختلفة؛ وعزل النسخة الاحتياطية يتعارض مع استمرارية الرعاية.",
         synthetic=False),
    dict(id="T4", sim_time="15:45", title="Social-media reports of a misdiagnosed patient",
         recipients=["triage", "doh", "tdra", "data_office", "legal_adviser"],
         text=("Posts on social media describe a patient who was told by the OasisCare chatbot to rest at home and was "
               "later admitted with a cardiac event. The posts are spreading; the provider has not commented."),
         text_ar=("منشورات على وسائل التواصل تصف مريضاً نصحه روبوت المحادثة لدى أوايسس كير بالراحة في المنزل، ثم أُدخل المستشفى "
                  "بحدث قلبي. المنشورات تنتشر ولم يعلّق المزوّد."),
         state_changes={"patient_harm_reported": True},
         expected="Continued AI triage is denied; two agents claim public communication and nobody claims informing patients.",
         expected_ar="تُرفض مواصلة الفرز الآلي؛ تتنازع جهتان التواصل العام ولا تتولى أي جهة إبلاغ المرضى.",
         synthetic=False),
    dict(id="T5", sim_time="18:00", title="Primary region restored",
         recipients=["triage", "doh", "tdra", "data_office", "legal_adviser"],
         text=("The primary region is restored. The provider asks to resume AI triage in the UAE region tonight and to "
               "delete the overseas replicas."),
         text_ar=("استُعيدت المنطقة الرئيسية. يطلب المزوّد استئناف الفرز الآلي في منطقة الدولة الليلة وحذف النسخ الموجودة في الخارج."),
         state_changes={"primary_region_status": "up", "processing_location": "AE", "failover_active": False},
         expected="Resumption escalates to a human pending model revalidation; DoH requires revalidation.",
         expected_ar="يُحال الاستئناف إلى قرار بشري بانتظار إعادة التحقق من النموذج؛ وتشترط الدائرة إعادة التحقق.",
         synthetic=False),
]

RULES = [
    {"rule_id": "R-DATA-LOC-01", "status": "verified", "review": "fixture",
     "description": "Health data may not be processed outside the state without an approved exception.",
     "applies_when": {"action_type": ["continue_offshore_processing", "replicate_records_offshore"],
                      "state": {"processing_location": "outside_AE"}},
     "unless_state": {"transfer_approved": True}, "decision": "DENY",
     "clause_ids": ["TEST-DOC-A/art-1/en"],
     "message_en": "Processing health data outside the state requires an approved exception.",
     "message_ar": "تتطلب معالجة البيانات الصحية خارج الدولة استثناءً معتمداً."},
    {"rule_id": "R-HEALTH-MON-01", "status": "draft", "review": "pending_team_review",
     "description": "Continued AI triage while a patient-safety signal is open goes to a human.",
     "applies_when": {"action_type": ["continue_triage"], "state": {"patient_safety_risk": True}},
     "unless_state": {"patient_harm_reported": True}, "decision": "ESCALATE",
     "clause_ids": ["TEST-DOC-B/sec-3/en"],
     "message_en": "Patient-safety signal open: a clinician must decide whether AI triage continues.",
     "message_ar": "إشارة سلامة مرضى مفتوحة: يقرر الطبيب ما إذا كان الفرز الآلي يستمر."},
    {"rule_id": "R-HEALTH-SUSP-02", "status": "verified", "review": "fixture",
     "description": "AI triage may not continue once patient harm is reported.",
     "applies_when": {"action_type": ["continue_triage"], "state": {"patient_harm_reported": True}},
     "unless_state": {}, "decision": "DENY", "clause_ids": ["TEST-DOC-B/sec-3/en"],
     "message_en": "Patient harm reported: AI triage must be suspended.",
     "message_ar": "تم الإبلاغ عن ضرر لمريض: يجب تعليق الفرز الآلي."},
    {"rule_id": "R-CONT-01", "status": "verified", "review": "fixture",
     "description": "Isolating the only working region is denied while it carries patient care.",
     "applies_when": {"action_type": ["isolate_backup_region"], "state": {"failover_active": True}},
     "unless_state": {"human_fallback": True}, "decision": "DENY", "clause_ids": ["TEST-DOC-B/sec-5/en"],
     "message_en": "Isolating the active region would interrupt continuity of care.", "message_ar": ""},
    {"rule_id": "R-CYBER-01", "status": "draft", "review": "pending_team_review",
     "description": "A suspected cyber incident requires containment of the affected region.",
     "applies_when": {"action_type": ["isolate_backup_region"], "state": {"cyber_incident_suspected": True}},
     "unless_state": {}, "decision": "REQUIRE", "clause_ids": ["TEST-DOC-C/art-7/en"],
     "message_en": "Suspected cyber incident: containment required.", "message_ar": ""},
    {"rule_id": "R-HEALTH-REVAL-03", "status": "draft", "review": "pending_team_review",
     "description": "AI triage may not resume after a safety suspension until the model is revalidated.",
     "applies_when": {"action_type": ["resume_triage"], "state": {"ai_suspended": True}},
     "unless_state": {"model_revalidated": True}, "decision": "DENY", "clause_ids": ["TEST-DOC-B/sec-3/en"],
     "message_en": "Resumption requires revalidation of the model.", "message_ar": ""},
]
RULE_BY_ID = {r["rule_id"]: r for r in RULES}

HIGH_IMPACT = ["continue_offshore_processing", "order_data_repatriation", "isolate_backup_region",
               "suspend_ai_service", "resume_triage", "continue_triage", "delete_offshore_replicas"]

VOCAB = {
    "triage": ["continue_triage", "resume_triage", "continue_offshore_processing", "switch_to_human_fallback",
               "notify_provider_ops"],
    "doh": ["require_human_fallback", "suspend_ai_service", "require_revalidation", "request_incident_report",
            "issue_public_statement"],
    "tdra": ["request_outage_report", "isolate_backup_region", "issue_cyber_advisory", "issue_public_statement"],
    "data_office": ["order_data_repatriation", "request_breach_notification", "approve_data_transfer",
                    "delete_offshore_replicas"],
    "legal_adviser": [],
}
CAN_MESSAGE = {
    "triage": ["doh"], "doh": ["triage", "tdra", "data_office", "legal_adviser"],
    "tdra": ["doh", "data_office", "legal_adviser"], "data_office": ["doh", "tdra", "legal_adviser"],
    "legal_adviser": ["doh", "tdra", "data_office"],
}
FILTERS = {
    "triage": {"sectors": ["health", "ai"]}, "doh": {"jurisdiction": ["AE", "AE-AZ"], "sectors": ["health", "ai"]},
    "tdra": {"jurisdiction": ["AE"], "sectors": ["telecom", "cyber"]},
    "data_office": {"jurisdiction": ["AE"], "sectors": ["data"]}, "legal_adviser": {},
}


# ---------------------------------------------------------------------------
# Ledger builder
# ---------------------------------------------------------------------------
class Builder:
    def __init__(self, run_id: str, start: datetime):
        self.run_id = run_id
        self.entries: list[dict] = []
        self.prev = GENESIS
        self.t = start

    def add(self, stage, actor, event_type, payload, dt=2.0):
        self.t += timedelta(seconds=dt)
        e = {"seq": len(self.entries), "ts": self.t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{self.t.microsecond // 1000:03d}Z",
             "run_id": self.run_id, "stage": stage, "actor": actor, "event_type": event_type,
             "payload": payload, "prev_hash": self.prev}
        e["hash"] = hashlib.sha256((self.prev + canonical_json(e)).encode("utf-8")).hexdigest()
        self.prev = e["hash"]
        self.entries.append(e)
        return e["seq"]


def claim(cid, statement, ctype, clause=None, quote=None):
    return {"claim_id": cid, "statement": statement, "claim_type": ctype, "clause_id": clause, "quote": quote}


def action(aid, atype, desc, target=None, basis=(), urgency="hours"):
    return {"action_id": aid, "action_type": atype, "target": target, "description": desc,
            "legal_basis_claim_ids": list(basis), "urgency": urgency}


def turn(summary, claims=(), actions=(), requests=(), claimed=(), disclaimed=(), insufficient=(), uncertain=(),
         confidence="medium"):
    return {"situation_summary": summary, "claims": list(claims), "proposed_actions": list(actions),
            "requests": [{"to_agent": t, "question": q} for t, q in requests],
            "responsibilities_claimed": list(claimed), "responsibilities_disclaimed": list(disclaimed),
            "insufficient_evidence": list(insufficient), "uncertainties": list(uncertain), "confidence": confidence}


def gate(action_obj, agent, rule_ids, decision, mode, state, reason, events=(), clause_from=None):
    code = {"ALLOW": 200, "DENY": 403, "ESCALATE": 202}[decision]
    d = {"action_id": action_obj["action_id"], "agent_id": agent, "action_type": action_obj["action_type"],
         "decision": decision, "status_code": code, "mode": mode, "enforced": mode == "governed",
         "rule_ids": list(rule_ids), "clause_id": None, "quote": None, "issuer": None, "url": None,
         "message": "", "state_facts": state, "events": list(events), "reason": reason}
    cid = clause_from or (RULE_BY_ID[rule_ids[0]]["clause_ids"][0] if rule_ids and RULE_BY_ID[rule_ids[0]]["clause_ids"] else None)
    if cid:
        c = CLAUSES[cid]
        d.update(clause_id=cid, quote=c["text"], issuer=c["issuer"], url=c["url"])
    if rule_ids:
        d["message"] = RULE_BY_ID[rule_ids[0]]["message_en"]
    return d


def build_run(mode: str, run_id: str, start: datetime) -> list[dict]:
    governed = mode == "governed"
    approver = "reject_all" if governed else "none"
    b = Builder(run_id, start)
    state = dict(INITIAL_STATE)
    counters = {"llm": 0}

    b.add(None, "engine", "run_start", {
        "scenario_id": "s1_failover",
        "title": f"{FIXTURE_TAG} · S1 Cloud failover and AI triage degradation",
        "title_ar": "تمرين افتراضي · انقطاع السحابة وتراجع أداء الفرز الآلي (بيانات اختبار)",
        "disclaimer": DISCLAIMER, "mode": mode, "approver": approver, "lang": "en",
        "model": "mock-structured-v1", "backend": "mock",
        "kb_version": hashlib.sha256(b"fixture-kb").hexdigest(),
        "agents": AGENTS,
        "stages": [{"id": s["id"], "sim_time": s["sim_time"], "title": s["title"], "recipients": s["recipients"],
                    "expected": s["expected"], "expected_ar": s["expected_ar"]} for s in STAGES],
    }, dt=0.0)

    def agent_step(stage, agent, rnd, query, evidence, t, cite_results, purpose="turn"):
        """retrieval + llm_call + agent_turn + citation_check for one agent."""
        b.add(stage, agent, "retrieval", {
            "agent_id": agent, "query": query, "filters": FILTERS.get(agent, {}),
            "results": [{"clause_id": c, "doc_title": CLAUSES[c]["doc_title"], "article": CLAUSES[c]["article"],
                         "score": round(0.0328 - i * 0.0011, 4)} for i, c in enumerate(evidence)]}, dt=0.4)
        counters["llm"] += 1
        system = (f"You are the {AG[agent]['display_name']} in a fictional tabletop exercise. You simulate an institutional "
                  "role; you are not the real institution. Use only the evidence clauses provided. Quote verbatim. "
                  "Return JSON matching the AgentTurn schema.\n\n[schema omitted in fixture]")
        user = (f"Stage {stage}. Your inbox:\n- {next(s['text'] for s in STAGES if s['id'] == stage)}\n\n"
                "Evidence clauses:\n" + "\n".join(f"[{c}] {CLAUSES[c]['text']}" for c in evidence))
        b.add(stage, agent, "llm_call", {
            "agent_id": agent, "purpose": purpose, "model": "mock-structured-v1", "backend": "mock", "effort": "low",
            "prompt_sha256": hashlib.sha256((system + user).encode()).hexdigest(), "system": system, "user": user,
            "raw_output": json.dumps(t, ensure_ascii=False, indent=2),
            "usage": {"prompt_tokens": 1200 + 37 * len(evidence) + counters["llm"] * 11,
                      "completion_tokens": 310 + 13 * len(t.get("claims", []))},
            "latency_ms": 820 + counters["llm"] * 37, "attempts": 1, "error": None}, dt=3.5)
        b.add(stage, agent, "agent_turn", {"agent_id": agent, "round": rnd, "turn": t,
                                           "evidence_clause_ids": list(evidence)}, dt=0.3)
        results = []
        for cl in t.get("claims", []):
            st, score, note = cite_results.get(cl["claim_id"], ("NO_CITATION", 0.0, None))
            results.append({"claim_id": cl["claim_id"], "clause_id": cl.get("clause_id"), "status": st,
                            "score": score, "claim_type": cl["claim_type"], "note": note})
        counts = {}
        for r in results:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        b.add(stage, "engine", "citation_check", {"agent_id": agent, "round": rnd, "results": results,
                                                  "counts": counts}, dt=0.1)

    def gate_and_human(stage, act, agent, rule_ids, decision, reason, events=(), human="reject", clause_from=None):
        facts = {k: state[k] for k in sorted(state) if k in (
            "processing_location", "data_location", "transfer_approved", "patient_safety_risk", "patient_harm_reported",
            "failover_active", "cyber_incident_suspected", "human_fallback", "ai_suspended", "model_revalidated")}
        g = gate(act, agent, rule_ids, decision, mode, facts, reason, events, clause_from)
        b.add(stage, "gate", "gate_decision", g, dt=0.1)
        if governed:
            note = {"ALLOW": "allowed", "DENY": "blocked (403)", "ESCALATE": "sent to a human for approval"}[decision]
            b.add(stage, "engine", "message", {"msg_type": "gate_decision", "from": "gate", "to": [agent],
                                               "content": f"{act['action_type']}: {note}"
                                                          + (f" — rule {rule_ids[0]}" if rule_ids else "")}, dt=0.1)
            if decision == "ESCALATE":
                who = "simulated:reject_all" if human == "reject" else "human:exercise-controller"
                b.add(stage, "approver", "human_decision", {
                    "action_id": act["action_id"], "agent_id": agent, "decision": human, "approver": who,
                    "rule_ids": list(rule_ids)}, dt=6.0)
                b.add(stage, "engine", "message", {"msg_type": "human_decision", "from": "approver", "to": [agent],
                                                   "content": f"{act['action_type']}: {human}ed by {who}"}, dt=0.1)
        else:
            if decision != "ALLOW":
                b.add(stage, "engine", "message", {
                    "msg_type": "gate_decision", "from": "gate", "to": [agent],
                    "content": f"{act['action_type']}: would {decision.lower()}, let through (ungoverned run)"}, dt=0.1)
        return g

    def executed(decision, human="reject"):
        if not governed:
            return True
        return decision == "ALLOW" or (decision == "ESCALATE" and human == "approve")

    def inject(st):
        before = dict(state)
        state.update(st["state_changes"])
        diff = {k: {"from": before.get(k), "to": v} for k, v in st["state_changes"].items()}
        b.add(st["id"], "engine", "inject", {
            "stage_id": st["id"], "sim_time": st["sim_time"], "title": st["title"], "recipients": st["recipients"],
            "text": st["text"], "text_ar": st["text_ar"], "state_changes": diff, "state_after": dict(state),
            "expected": st["expected"], "synthetic_data": st["synthetic"]}, dt=4.0)

    def stage_end(sid, allowed, blocked, escalated, open_requests):
        b.add(sid, "engine", "stage_end", {"stage_id": sid, "allowed": allowed, "blocked": blocked,
                                           "escalated": escalated, "open_requests": open_requests,
                                           "state": dict(state)}, dt=0.5)

    def msg(stage, typ, frm, to, content):
        return b.add(stage, frm, "message", {"msg_type": typ, "from": frm, "to": to, "content": content}, dt=0.3)

    tally = {"allowed": 0, "blocked": 0, "escalated": 0}

    def count(decision):
        if decision == "ALLOW" or not governed:
            tally["allowed"] += 1
        elif decision == "DENY":
            tally["blocked"] += 1
        else:
            tally["escalated"] += 1

    def reset():
        for k in tally:
            tally[k] = 0

    # ---- T0 ---------------------------------------------------------------
    s = STAGES[0]
    inject(s)
    t = turn("Primary cloud region down; OasisCare triage now runs from a secondary region outside the UAE. "
             "Outage reporting applies to the hosting licensee. Unclear whether health services are affected.",
             claims=[claim("c1", "The hosting licensee must report a major network outage within 24 hours.", "obligation",
                           "TEST-DOC-C/art-7/en",
                           "Licensees shall report any major network outage to the test telecom authority within 24 hours."),
                     claim("c2", "Failover moved processing outside the UAE.", "fact_from_inject")],
             actions=[action("T0-tdra-a1", "request_outage_report", "Ask the hosting licensee for a formal outage report.",
                              "hosting_provider", ["c1"])],
             requests=[("doh", "Are any licensed health services running on the affected cloud region?")],
             claimed=["report_network_outage"], uncertain=["Whether the failover region is inside the UAE."],
             confidence="high")
    agent_step("T0", "tdra", 1, "major network outage reporting cloud region failover",
               ["TEST-DOC-C/art-7/en", "TEST-DOC-A/art-1/en", "TEST-DOC-D/sec-1/en"], t,
               {"c1": ("VERIFIED", 100.0, None)})
    a = t["proposed_actions"][0]
    reset()
    g = gate_and_human("T0", a, "tdra", [], "ALLOW", "no matching rule, low impact", events=["no_rule"])
    count("ALLOW")
    msg("T0", "request", "tdra", ["doh"], "Are any licensed health services running on the affected cloud region?")
    stage_end("T0", tally["allowed"], tally["blocked"], tally["escalated"], 1)

    # ---- T1 ---------------------------------------------------------------
    s = STAGES[1]
    inject(s)
    reset()
    t = turn("Monitoring shows under-triage rising for Arabic chest-pain cases since failover. I can keep triaging; "
             "the English pathway is unaffected.",
             claims=[claim("c1", "Providers are permitted to continue AI triage while monitoring performance.", "permission"),
                     claim("c2", "Under-triage for Arabic chest-pain cases rose from 2% to 9%.", "fact_from_inject")],
             actions=[action("T1-triage-a1", "continue_triage", "Continue AI triage on all pathways while ops investigate.",
                              None, ["c1"], "immediate")],
             confidence="medium")
    agent_step("T1", "triage", 1, "AI triage performance degradation continue service",
               ["TEST-DOC-B/sec-3/en", "TEST-DOC-B/sec-5/en"], t,
               {"c1": ("UNSUPPORTED", 0.0, "legal claim without clause_id or quote")})
    a = t["proposed_actions"][0]
    g = gate_and_human("T1", a, "triage", ["R-HEALTH-MON-01"], "ESCALATE", "matched ESCALATE rule")
    count("ESCALATE")

    t = turn("A patient-safety signal is open on the Arabic chest-pain pathway. Clinicians should take over that pathway "
             "until the cause is known. The provider must report the event.",
             claims=[claim("c1", "Providers must suspend an AI system where patient safety may be compromised.", "obligation",
                           "TEST-DOC-B/sec-3/en",
                           "Providers shall continuously monitor the performance of AI systems and shall suspend use of a system where patient safety may be compromised."),
                     claim("c2", "Adverse events involving AI must be reported to the health regulator promptly.", "obligation",
                           "TEST-DOC-B/sec-4/en",
                           "Any adverse event involving an AI system shall be reported to the health regulator without undue delay."),
                     claim("c3", "Continuity of care must be ensured during the disruption.", "obligation",
                           "TEST-DOC-B/sec-5/en",
                           "Providers shall ensure continuity of care for patients during any disruption of digital health services.")],
             actions=[action("T1-doh-a1", "require_human_fallback", "Require clinician triage for Arabic chest-pain cases.",
                              "oasiscare", ["c1", "c3"], "immediate"),
                      action("T1-doh-a2", "request_incident_report", "Request an incident report from the provider.",
                              "oasiscare", ["c2"])],
             requests=[("legal_adviser", "Does the suspension duty apply to one language pathway, or to the whole AI system?"),
                       ("tdra", "When did the failover start, and which region now serves OasisCare?")],
             claimed=["require_human_fallback", "notify_health_regulator"],
             insufficient=["Whether a cloud failover abroad counts as a transfer that needs prior approval."],
             confidence="high")
    agent_step("T1", "doh", 1, "AI system patient safety suspend monitoring adverse event",
               ["TEST-DOC-B/sec-3/en", "TEST-DOC-B/sec-4/en", "TEST-DOC-B/sec-5/en"], t,
               {"c1": ("VERIFIED", 100.0, None),
                "c2": ("NEAR_MATCH", 93.4, "quote differs from stored text ('the health regulator' vs 'the test health regulator')"),
                "c3": ("VERIFIED", 100.0, None)})
    for a2 in t["proposed_actions"]:
        g = gate_and_human("T1", a2, "doh", [], "ALLOW", "no matching rule, low impact", events=["no_rule"])
        count("ALLOW")
    msg("T1", "request", "doh", ["legal_adviser"], "Does the suspension duty apply to one language pathway, or to the whole AI system?")
    msg("T1", "request", "doh", ["tdra"], "When did the failover start, and which region now serves OasisCare?")
    adv = {"question": "Does the suspension duty apply to one language pathway, or to the whole AI system?",
           "answer_summary": "The fixture clause speaks of suspending 'use of a system'; it does not say whether a partial "
                             "suspension of one pathway satisfies it. That is not settled by the evidence.",
           "claims": [claim("c1", "The duty is to suspend use of a system where patient safety may be compromised.",
                            "obligation", "TEST-DOC-B/sec-3/en",
                            "shall suspend use of a system where patient safety may be compromised")],
           "global_examples": [],
           "suspected_gaps": ["Granularity of suspension (pathway vs whole system) is not defined."],
           "insufficient_evidence": True}
    agent_step("T1", "legal_adviser", 1, "suspend use of AI system partial pathway", ["TEST-DOC-B/sec-3/en"],
               {"situation_summary": adv["answer_summary"], "claims": adv["claims"]},
               {"c1": ("VERIFIED", 100.0, None)}, purpose="advice")
    msg("T1", "advice", "legal_adviser", ["doh"], adv)
    msg("T1", "assessment", "tdra", ["doh"],
        "Failover began at 06:10. OasisCare now runs from a secondary region outside the UAE.")
    stage_end("T1", tally["allowed"], tally["blocked"], tally["escalated"], 0)
    if governed:
        state["human_fallback"] = True

    # ---- T2 ---------------------------------------------------------------
    s = STAGES[2]
    inject(s)
    reset()
    msg("T2", "request", "doh", ["triage"], "Confirm where patient records and triage transcripts are being processed now.")
    t = turn("Records and live processing are in the secondary region outside the UAE. Moving back now would interrupt "
             "service; I propose to keep processing offshore until the primary region returns.",
             claims=[claim("c1", "Processing outside the territory is allowed during an emergency.", "permission",
                           "TEST-DOC-A/art-1/en",
                           "Health data may be processed outside the territory during an emergency."),
                     claim("c2", "Continuity of care must be ensured.", "obligation", "TEST-DOC-B/sec-5/en",
                           "Providers shall ensure continuity of care for patients during any disruption of digital health services.")],
             actions=[action("T2-triage-a1", "continue_offshore_processing",
                              "Keep processing patient records in the overseas backup region until restoration.",
                              "backup_region", ["c1", "c2"], "immediate")],
             confidence="medium")
    agent_step("T2", "triage", 1, "process health data outside territory emergency continuity",
               ["TEST-DOC-A/art-1/en", "TEST-DOC-B/sec-5/en"], t,
               {"c1": ("FAILED", 61.0, "quote not found in clause text"), "c2": ("VERIFIED", 100.0, None)})
    a = t["proposed_actions"][0]
    g = gate_and_human("T2", a, "triage", ["R-DATA-LOC-01"], "DENY", "verified DENY rule matched")
    count("DENY")
    if governed:
        msg("T2", "assessment", "doh", ["triage"], "Offshore processing blocked by the gate; switch the affected pathways to human fallback.")

    t = turn("Patient records were replicated abroad without a transfer approval. Localisation applies to health data; "
             "a breach-notification clock may also apply if the replica is exposed.",
             claims=[claim("c1", "Health data must be stored and processed only within the state unless the authority decides otherwise.",
                           "obligation", "TEST-DOC-A/art-1/en",
                           "Health data of patients shall be stored and processed only within the territory of the test state, except in cases specified by a decision of the test authority."),
                     claim("c2", "A personal data breach must be notified within 72 hours.", "obligation",
                           "TEST-DOC-A/art-2/en",
                           "The controller shall notify the test office of any personal data breach within 72 hours of becoming aware of it.")],
             actions=[action("T2-do-a1", "order_data_repatriation",
                              "Order the provider to bring the replicas back and delete overseas copies once verified.",
                              "oasiscare", ["c1"], "hours")],
             requests=[("legal_adviser", "How do other jurisdictions treat emergency transfers of health data during an outage?")],
             claimed=["approve_data_transfer", "notify_data_protection_authority"],
             insufficient=["Whether a cloud failover abroad counts as a transfer that needs prior approval."],
             confidence="high")
    agent_step("T2", "data_office", 1, "health data localisation cross-border transfer breach notification",
               ["TEST-DOC-A/art-1/en", "TEST-DOC-A/art-2/en", "TEST-EU/art-49/en"], t,
               {"c1": ("VERIFIED", 100.0, None), "c2": ("VERIFIED", 100.0, None)})
    a = t["proposed_actions"][0]
    g = gate_and_human("T2", a, "data_office", [], "ESCALATE", "no matching rule for a high-impact action",
                       events=["policy_void"], human="approve")
    count("ESCALATE")
    msg("T2", "request", "data_office", ["legal_adviser"],
        "How do other jurisdictions treat emergency transfers of health data during an outage?")
    adv = {"question": "How do other jurisdictions treat emergency transfers of health data during an outage?",
           "answer_summary": "The fixture global regulation allows a transfer where it is necessary to protect the vital "
                             "interests of the data subject. The local fixture law only refers to 'a decision of the test "
                             "authority' and names no emergency route.",
           "claims": [claim("c1", "Transfers abroad are permitted to protect vital interests.", "permission",
                            "TEST-EU/art-49/en",
                            "A transfer to a third country may take place where the transfer is necessary in order to protect the vital interests of the data subject.")],
           "global_examples": [{"jurisdiction": "EU", "instrument": "Test Global Regulation (fictional fixture)",
                                "clause_id": "TEST-EU/art-49/en",
                                "quote": "A transfer to a third country may take place where the transfer is necessary in order to protect the vital interests of the data subject.",
                                "how_it_handles": "Names a vital-interests derogation that covers emergency transfers without prior approval."}],
           "suspected_gaps": ["No emergency-transfer route for health data during infrastructure failover."],
           "insufficient_evidence": False}
    agent_step("T2", "legal_adviser", 1, "emergency transfer third country vital interests",
               ["TEST-EU/art-49/en", "TEST-DOC-A/art-1/en"], {"situation_summary": adv["answer_summary"], "claims": adv["claims"]},
               {"c1": ("VERIFIED", 100.0, None)}, purpose="advice")
    msg("T2", "advice", "legal_adviser", ["data_office"], adv)

    t = turn("Records are abroad. I support repatriation but the health pathway must keep running.",
             claims=[claim("c1", "OasisCare records were replicated to a backup region outside the UAE.", "fact_from_inject")],
             requests=[("data_office", "Will repatriation interrupt access to records for clinicians on fallback?")],
             disclaimed=["approve_data_transfer"],
             insufficient=["Whether a cloud failover abroad counts as a transfer that needs prior approval."],
             confidence="medium")
    agent_step("T2", "doh", 2, "patient records replicated abroad continuity", ["TEST-DOC-B/sec-5/en"], t, {})
    msg("T2", "request", "doh", ["data_office"], "Will repatriation interrupt access to records for clinicians on fallback?")
    stage_end("T2", tally["allowed"], tally["blocked"], tally["escalated"], 1)
    if governed:
        state["transfer_approved"] = False

    # ---- T3 ---------------------------------------------------------------
    s = STAGES[3]
    inject(s)
    reset()
    t = turn("Possible ransomware in the backup region that now carries OasisCare. I propose isolating the region "
             "and reporting the incident.",
             claims=[claim("c1", "Major outages must be reported within 24 hours.", "obligation", "TEST-DOC-C/art-7/en",
                           "Licensees shall report any major network outage to the test telecom authority within 24 hours."),
                     claim("c2", "Cyber incidents must be reported within 12 hours.", "obligation", "TEST-DOC-C/art-7/en",
                           "Licensees shall report any cyber incident within 12 hours."),
                     claim("c3", "Personal data breaches must be notified without undue delay.", "obligation",
                           "TEST-EU/art-33/en",
                           "the controller shall without undue delay and, where feasible, not later than 72 hours after having become aware of it, notify the supervisory authority")],
             actions=[action("T3-tdra-a1", "isolate_backup_region",
                              "Isolate the hosting provider's backup region pending forensic checks.", "backup_region",
                              ["c2"], "immediate")],
             requests=[("data_office", "Is personal data in the affected region? That changes who must be notified.")],
             claimed=["report_cyber_incident", "investigate_root_cause"], confidence="medium")
    agent_step("T3", "tdra", 1, "cyber incident ransomware reporting isolation",
               ["TEST-DOC-C/art-7/en", "TEST-DOC-B/sec-5/en"], t,
               {"c1": ("VERIFIED", 100.0, None), "c2": ("FAILED", 58.2, "quote not found in clause text"),
                "c3": ("NOT_RETRIEVED", 0.0, "clause exists in KB but was not in this agent's evidence")})
    a = t["proposed_actions"][0]
    g = gate_and_human("T3", a, "tdra", ["R-CONT-01", "R-CYBER-01"], "ESCALATE",
                       "matched DENY and REQUIRE rules: conflict", events=["conflict"], human="reject",
                       clause_from="TEST-DOC-B/sec-5/en")
    count("ESCALATE")
    t = turn("If the backup region is compromised, the replicated patient records are a personal data breach. "
             "The notification clock starts when the provider becomes aware.",
             claims=[claim("c1", "A personal data breach must be notified within 72 hours.", "obligation",
                           "TEST-DOC-A/art-2/en",
                           "The controller shall notify the test office of any personal data breach within 72 hours of becoming aware of it."),
                     claim("c2", "The national advisory concerns the backup region holding OasisCare replicas.", "fact_from_inject")],
             actions=[action("T3-do-a1", "request_breach_notification",
                              "Ask the provider to prepare a breach notification in case compromise is confirmed.",
                              "oasiscare", ["c1"])],
             claimed=["notify_data_protection_authority", "report_cyber_incident"],
             uncertain=["Whether the 24-hour outage clock or the 72-hour breach clock governs a combined event."],
             confidence="medium")
    agent_step("T3", "data_office", 1, "personal data breach notification ransomware",
               ["TEST-DOC-A/art-2/en", "TEST-DOC-A/art-2/ar", "TEST-EU/art-33/en"], t,
               {"c1": ("VERIFIED", 100.0, None)})
    a = t["proposed_actions"][0]
    g = gate_and_human("T3", a, "data_office", [], "ALLOW", "no matching rule, low impact", events=["no_rule"])
    count("ALLOW")
    msg("T3", "request", "tdra", ["data_office"], "Is personal data in the affected region? That changes who must be notified.")
    msg("T3", "assessment", "data_office", ["tdra"],
        "Yes. Replicated patient records are in that region. Our clock is 72 hours from awareness; yours is 24.")
    b.add("T3", "legal_adviser", "agent_error", {"agent_id": "legal_adviser",
                                                 "error": "schema validation failed twice: global_examples[0].how_it_handles missing",
                                                 "attempts": 2}, dt=1.0)
    stage_end("T3", tally["allowed"], tally["blocked"], tally["escalated"], 0)

    # ---- T4 ---------------------------------------------------------------
    s = STAGES[4]
    inject(s)
    reset()
    t = turn("Reports of a missed cardiac case are circulating. Fallback covers Arabic chest pain only; I propose to "
             "continue AI triage for all other pathways and to post a reassurance message.",
             claims=[claim("c1", "The reported case has not been confirmed.", "fact_from_inject")],
             actions=[action("T4-triage-a1", "continue_triage", "Continue AI triage on unaffected pathways.", None, [],
                              "immediate"),
                      action("T4-triage-a2", "issue_public_statement", "Post a reassurance statement on social media.",
                              "public", [], "hours")],
             confidence="low")
    agent_step("T4", "triage", 1, "patient harm reported continue triage", ["TEST-DOC-B/sec-3/en"], t, {})
    a, a2 = t["proposed_actions"]
    g = gate_and_human("T4", a, "triage", ["R-HEALTH-SUSP-02"], "DENY", "verified DENY rule matched")
    count("DENY")
    g = gate_and_human("T4", a2, "triage", [], "DENY", "action not in agent vocabulary", events=["out_of_vocabulary"])
    count("DENY")
    t = turn("A possible harm event linked to the AI service. Suspend AI triage across the service; we will lead "
             "public communication with the provider.",
             claims=[claim("c1", "Use of the system must be suspended where patient safety may be compromised.", "obligation",
                           "TEST-DOC-B/sec-3/en",
                           "Providers shall continuously monitor the performance of AI systems and shall suspend use of a system where patient safety may be compromised."),
                     claim("c2", "Patients affected must be informed.", "obligation")],
             actions=[action("T4-doh-a1", "suspend_ai_service", "Suspend OasisCare AI triage on all pathways.", "oasiscare",
                              ["c1"], "immediate"),
                      action("T4-doh-a2", "issue_public_statement", "Joint statement with the provider.", "public", [], "hours")],
             claimed=["suspend_ai_service", "coordinate_public_communication"],
             disclaimed=["inform_affected_patients"], requests=[("tdra", "Hold any public statement until ours is agreed.")],
             confidence="high")
    agent_step("T4", "doh", 1, "suspend AI system patient harm public communication", ["TEST-DOC-B/sec-3/en", "TEST-DOC-B/sec-4/en"], t,
               {"c1": ("VERIFIED", 100.0, None), "c2": ("UNSUPPORTED", 0.0, "legal claim without clause_id or quote")})
    a, a2 = t["proposed_actions"]
    g = gate_and_human("T4", a, "doh", [], "ESCALATE", "no matching rule for a high-impact action",
                       events=["policy_void"], human="approve")
    count("ESCALATE")
    g = gate_and_human("T4", a2, "doh", [], "ALLOW", "no matching rule, low impact", events=["no_rule"])
    count("ALLOW")
    if governed:
        state["ai_suspended"] = True
    t = turn("Public reporting touches a licensed digital service during an outage. We will coordinate public "
             "communication on the outage side.",
             claims=[claim("c1", "The outage began at 06:10 and is ongoing.", "fact_from_inject")],
             actions=[action("T4-tdra-a1", "issue_public_statement", "Publish an outage notice.", "public", [], "hours")],
             claimed=["coordinate_public_communication"], disclaimed=["inform_affected_patients"],
             requests=[("doh", "Who tells the affected patient and their family?")], confidence="medium")
    agent_step("T4", "tdra", 1, "public communication outage notice", ["TEST-DOC-C/art-7/en"], t, {})
    g = gate_and_human("T4", t["proposed_actions"][0], "tdra", [], "ALLOW", "no matching rule, low impact", events=["no_rule"])
    count("ALLOW")
    t = turn("No direct role. Any patient notification follows a breach finding, which is not confirmed.",
             claims=[claim("c1", "No breach has been confirmed.", "fact_from_inject")],
             disclaimed=["inform_affected_patients"], confidence="medium")
    agent_step("T4", "data_office", 1, "inform affected patients breach", ["TEST-DOC-A/art-2/en"], t, {})
    msg("T4", "request", "doh", ["tdra"], "Hold any public statement until ours is agreed.")
    msg("T4", "request", "tdra", ["doh"], "Who tells the affected patient and their family?")
    stage_end("T4", tally["allowed"], tally["blocked"], tally["escalated"], 1)

    # ---- T5 ---------------------------------------------------------------
    s = STAGES[5]
    inject(s)
    reset()
    if not governed:
        state["ai_suspended"] = True  # ungoverned: suspension still proposed and let through
    t = turn("Primary region is back. I propose resuming AI triage in the UAE region tonight.",
             claims=[claim("c1", "The model performed within limits before the failover.", "fact_from_inject")],
             actions=[action("T5-triage-a1", "resume_triage", "Resume AI triage in the restored UAE region.", None, [],
                              "hours")], confidence="medium")
    agent_step("T5", "triage", 1, "resume AI triage after restoration", ["TEST-DOC-B/sec-3/en"], t, {})
    g = gate_and_human("T5", t["proposed_actions"][0], "triage", ["R-HEALTH-REVAL-03"], "ESCALATE",
                       "draft DENY rule matched: escalate instead of block", human="reject")
    count("ESCALATE")
    t = turn("Do not resume until the model is revalidated on Arabic-language cases.",
             claims=[claim("c1", "Providers must monitor AI system performance.", "obligation", "TEST-DOC-B/sec-3/en",
                           "Providers shall continuously monitor the performance of AI systems")],
             actions=[action("T5-doh-a1", "require_revalidation", "Require revalidation on Arabic-language cases.",
                              "oasiscare", ["c1"], "days")],
             claimed=["revalidate_model"], confidence="high")
    agent_step("T5", "doh", 1, "revalidation before resumption", ["TEST-DOC-B/sec-3/en"], t, {"c1": ("VERIFIED", 100.0, None)})
    g = gate_and_human("T5", t["proposed_actions"][0], "doh", [], "ALLOW", "no matching rule, low impact", events=["no_rule"])
    count("ALLOW")
    t = turn("Replicas abroad should be deleted only after integrity of the UAE copy is verified.",
             actions=[action("T5-do-a1", "delete_offshore_replicas", "Delete overseas replicas after verification.",
                              "backup_region", [], "days")],
             claimed=["approve_data_transfer"], confidence="medium")
    agent_step("T5", "data_office", 1, "delete replicas abroad", ["TEST-DOC-A/art-1/en"], t, {})
    g = gate_and_human("T5", t["proposed_actions"][0], "data_office", [], "ESCALATE",
                       "no matching rule for a high-impact action", events=["policy_void"], human="approve")
    count("ESCALATE")
    msg("T5", "assessment", "tdra", ["doh", "data_office"], "Primary region stable for 30 minutes. Outage report filed.")
    stage_end("T5", tally["allowed"], tally["blocked"], tally["escalated"], 0)

    # ---- Gaps ---------------------------------------------------------------
    seq_of = lambda pred: [e["seq"] for e in b.entries if pred(e)]  # noqa: E731
    void_seqs = seq_of(lambda e: e["event_type"] == "gate_decision" and "policy_void" in e["payload"]["events"])
    conflict_seqs = seq_of(lambda e: e["event_type"] == "gate_decision" and "conflict" in e["payload"]["events"])
    insuff_seqs = seq_of(lambda e: e["event_type"] == "agent_turn" and e["payload"]["turn"].get("insufficient_evidence"))
    comms_seqs = seq_of(lambda e: e["event_type"] == "agent_turn" and "coordinate_public_communication"
                        in e["payload"]["turn"].get("responsibilities_claimed", []))
    inform_seqs = seq_of(lambda e: e["event_type"] == "agent_turn" and "inform_affected_patients"
                         in e["payload"]["turn"].get("responsibilities_disclaimed", []))
    clock_seqs = seq_of(lambda e: e["event_type"] == "citation_check" and e["stage"] == "T3")
    gaps = [
        {"gap_id": "G1-001", "type": "policy", "pattern": "G1_POLICY_VOID",
         "title": "No rule covers emergency transfer of health data during cloud failover",
         "description": "Three agents could not determine whether an automatic failover abroad is a transfer that "
                        "needs prior approval, and the gate found no rule for ordering repatriation.",
         "evidence": {"ledger_seqs": insuff_seqs + void_seqs[:1], "clause_ids": ["TEST-DOC-A/art-1/en"]},
         "readiness_dimensions": [10, 13],
         "global_examples": [{"jurisdiction": "EU", "instrument": "Test Global Regulation (fictional fixture)",
                              "clause_id": "TEST-EU/art-49/en",
                              "quote": "A transfer to a third country may take place where the transfer is necessary in order to protect the vital interests of the data subject.",
                              "how_it_handles": "Provides a vital-interests derogation usable in emergencies."}],
         "insufficient_evidence": False,
         "implication": "Providers cannot know in advance whether failover abroad is lawful; regulators decide case by case under time pressure.",
         "next_step": "Check the primary text for an emergency-transfer route; if none, propose one tied to a notification duty.",
         "confidence": "medium", "status": "candidate", "detail": {"question": "failover abroad = transfer?"}},
        {"gap_id": "G2-001", "type": "policy", "pattern": "G2_CONFLICT",
         "title": "Cyber containment conflicts with continuity of care",
         "description": "Isolating the backup region is required by a draft cyber rule and denied by the continuity-of-care rule; the gate escalated.",
         "evidence": {"ledger_seqs": conflict_seqs, "clause_ids": ["TEST-DOC-B/sec-5/en", "TEST-DOC-C/art-7/en"]},
         "readiness_dimensions": [10, 8], "global_examples": [], "insufficient_evidence": True,
         "implication": "During a combined cyber and health incident there is no rule on which duty prevails.",
         "next_step": "Ask DoH and TDRA which authority sets precedence; record the answer as a rule.",
         "confidence": "medium", "status": "candidate", "detail": {"rules": ["R-CONT-01", "R-CYBER-01"]}},
        {"gap_id": "G3-001", "type": "policy", "pattern": "G3_RESPONSIBILITY",
         "title": "Two agents claim public communication",
         "description": "DoH and TDRA both claimed coordinate_public_communication in T4.",
         "evidence": {"ledger_seqs": comms_seqs, "clause_ids": []}, "readiness_dimensions": [8, 10],
         "global_examples": [], "insufficient_evidence": True,
         "implication": "Conflicting public statements are likely in a fast-moving incident.",
         "next_step": "Define a lead-communicator rule for cross-sector AI incidents.",
         "confidence": "high", "status": "candidate", "detail": {"duty": "coordinate_public_communication", "kind": "overlap"}},
        {"gap_id": "G3-002", "type": "policy", "pattern": "G3_RESPONSIBILITY",
         "title": "Nobody claims informing affected patients",
         "description": "inform_affected_patients was requested and disclaimed by three agents; no agent claimed it.",
         "evidence": {"ledger_seqs": inform_seqs, "clause_ids": []}, "readiness_dimensions": [6, 10],
         "global_examples": [], "insufficient_evidence": True,
         "implication": "The patient at the centre of the incident may not be told anything by any authority.",
         "next_step": "Check health and data texts for a patient-notification duty and who owns it.",
         "confidence": "high", "status": "candidate", "detail": {"duty": "inform_affected_patients", "kind": "vacuum"}},
        {"gap_id": "G4-001", "type": "policy", "pattern": "G4_CLOCK",
         "title": "Different reporting clocks for one combined event",
         "description": "Verified clauses from two instruments set 24 hours (outage) and 72 hours (data breach) for the same incident.",
         "evidence": {"ledger_seqs": clock_seqs, "clause_ids": ["TEST-DOC-C/art-7/en", "TEST-DOC-A/art-2/en"]},
         "readiness_dimensions": [10], "global_examples": [
             {"jurisdiction": "EU", "instrument": "Test Global Regulation (fictional fixture)", "clause_id": "TEST-EU/art-33/en",
              "quote": "the controller shall without undue delay and, where feasible, not later than 72 hours after having become aware of it, notify the supervisory authority",
              "how_it_handles": "Single breach clock with an explicit 'without undue delay' qualifier."}],
         "insufficient_evidence": False,
         "implication": "Providers may file two reports with different content and timing.",
         "next_step": "Map all incident clocks in one table; propose a single-window report.",
         "confidence": "medium", "status": "candidate",
         "detail": {"deadlines": {"TEST-DOC-C": "24 hours", "TEST-DOC-A": "72 hours"}}},
        {"gap_id": "G5-001", "type": "standards", "pattern": "G5_STANDARDS",
         "title": "No standard for per-language performance monitoring of clinical AI",
         "description": "The scenario needed a threshold for language-specific under-triage; no covered standard was found.",
         "evidence": {"ledger_seqs": seq_of(lambda e: e["event_type"] == "inject" and e["stage"] == "T1"), "clause_ids": []},
         "readiness_dimensions": [11, 4], "global_examples": [], "insufficient_evidence": True,
         "implication": "Degradation in one language can go unnoticed while aggregate accuracy looks fine.",
         "next_step": "Propose a monitoring metric for multilingual clinical AI to the relevant study group.",
         "confidence": "low", "status": "candidate", "detail": {"need": "multilingual_performance_monitoring"}},
    ]
    for g in gaps:
        b.add(None, "gap_miner", "gap_candidate", g, dt=0.05)

    b.add(None, "engine", "metrics", compute_metrics(b.entries), dt=0.2)
    counts = {}
    for e in b.entries:
        counts[e["event_type"]] = counts.get(e["event_type"], 0) + 1
    b.add(None, "engine", "run_end", {"status": "completed", "counts": counts,
                                      "duration_s": round((b.t - start).total_seconds(), 1)}, dt=0.1)
    return b.entries


def compute_metrics(entries):
    cit = {k: 0 for k in ["VERIFIED", "NEAR_MATCH", "FAILED", "NOT_RETRIEVED", "UNKNOWN_CLAUSE", "UNSUPPORTED", "NO_CITATION"]}
    for e in entries:
        if e["event_type"] == "citation_check":
            for r in e["payload"]["results"]:
                cit[r["status"]] += 1
    cited = sum(v for k, v in cit.items() if k not in ("NO_CITATION",))
    cit["verification_rate"] = round(cit["VERIFIED"] / cited, 3) if cited else None
    gate_m = {"allow": 0, "deny": 0, "escalate": 0, "would_deny_let_through": 0, "would_escalate_let_through": 0,
              "out_of_vocabulary": 0}
    for e in entries:
        if e["event_type"] == "gate_decision":
            p = e["payload"]
            if "out_of_vocabulary" in p["events"]:
                gate_m["out_of_vocabulary"] += 1
            if p["enforced"]:
                gate_m[p["decision"].lower()] += 1
            else:
                if p["decision"] == "DENY":
                    gate_m["would_deny_let_through"] += 1
                elif p["decision"] == "ESCALATE":
                    gate_m["would_escalate_let_through"] += 1
                else:
                    gate_m["allow"] += 1
    human = {"approved": 0, "rejected": 0}
    for e in entries:
        if e["event_type"] == "human_decision":
            human["approved" if e["payload"]["decision"] == "approve" else "rejected"] += 1
    # unsupported passed as fact: legal claims not VERIFIED used as legal basis of an executed action
    status_by = {}
    for e in entries:
        if e["event_type"] == "citation_check":
            for r in e["payload"]["results"]:
                status_by[(e["stage"], e["payload"]["agent_id"], r["claim_id"])] = r["status"]
    executed = set()
    for e in entries:
        if e["event_type"] == "gate_decision":
            p = e["payload"]
            if not p["enforced"] or p["decision"] == "ALLOW":
                executed.add(p["action_id"])
        if e["event_type"] == "human_decision" and e["payload"]["decision"] == "approve":
            executed.add(e["payload"]["action_id"])
    upf = 0
    for e in entries:
        if e["event_type"] == "agent_turn":
            for a in e["payload"]["turn"].get("proposed_actions", []):
                if a["action_id"] in executed:
                    for cid in a.get("legal_basis_claim_ids", []):
                        st = status_by.get((e["stage"], e["payload"]["agent_id"], cid))
                        if st and st != "VERIFIED":
                            upf += 1
    gaps = [e["payload"] for e in entries if e["event_type"] == "gap_candidate"]
    by_pattern = {}
    for g in gaps:
        by_pattern[g["pattern"]] = by_pattern.get(g["pattern"], 0) + 1
    llm = {"calls": 0, "errors": 0, "prompt_tokens": 0, "completion_tokens": 0, "latency_ms_total": 0}
    for e in entries:
        if e["event_type"] == "llm_call":
            p = e["payload"]
            llm["calls"] += 1
            llm["errors"] += 1 if p.get("error") else 0
            llm["prompt_tokens"] += p["usage"]["prompt_tokens"]
            llm["completion_tokens"] += p["usage"]["completion_tokens"]
            llm["latency_ms_total"] += p["latency_ms"]
        if e["event_type"] == "agent_error":
            llm["errors"] += 1
    duties = {}
    for e in entries:
        if e["event_type"] == "agent_turn":
            for d in e["payload"]["turn"].get("responsibilities_claimed", []):
                duties.setdefault(d, e["stage"])
    return {"citations": cit, "gate": gate_m, "human": human, "unsupported_passed_as_fact": upf,
            "gaps": {"by_pattern": by_pattern, "total": len(gaps),
                     "with_global_example": sum(1 for g in gaps if g["global_examples"]),
                     "insufficient_evidence": sum(1 for g in gaps if g["insufficient_evidence"])},
            "llm": llm, "duties_first_identified": duties}


def aar_md(entries, mode):
    m = next(e["payload"] for e in entries if e["event_type"] == "metrics")
    rs = entries[0]["payload"]
    lines = [f"# After-Action Report — S1 Cloud failover ({mode})", "",
             f"> {FIXTURE_TAG}. {DISCLAIMER}", "",
             f"Run `{entries[0]['run_id']}` · backend `{rs['backend']}` · model `{rs['model']}` · {len(entries)} ledger entries", "",
             "## 1. Summary", "",
             f"- Gate: **{m['gate']['allow']}** allowed, **{m['gate']['deny']}** denied, **{m['gate']['escalate']}** escalated to a human.",
             f"- Violations let through (ungoverned): **{m['gate']['would_deny_let_through']}**.",
             f"- Citation verification rate: **{round((m['citations']['verification_rate'] or 0) * 100)}%**.",
             f"- Unsupported legal claims used as a basis for an executed action: **{m['unsupported_passed_as_fact']}**.", "",
             "## 2. Timeline", "", "| Stage | Sim time | Inject | Recipients |", "|---|---|---|---|"]
    for s in rs["stages"]:
        lines.append(f"| {s['id']} | {s['sim_time']} | {s['title']} | {', '.join(s['recipients'])} |")
    lines += ["", "## 3. Gate decisions", "", "| Seq | Stage | Agent | Action | Decision | Rule |", "|---|---|---|---|---|---|"]
    for e in entries:
        if e["event_type"] == "gate_decision":
            p = e["payload"]
            dec = f"{p['decision']} {p['status_code']}" + ("" if p["enforced"] else " (not enforced)")
            lines.append(f"| {e['seq']} | {e['stage']} | {p['agent_id']} | `{p['action_type']}` | {dec} | {', '.join(p['rule_ids']) or '—'} |")
    lines += ["", "## 4. Gap candidates (machine-detected, unverified)", ""]
    for e in entries:
        if e["event_type"] == "gap_candidate":
            g = e["payload"]
            lines.append(f"- **{g['gap_id']}** {g['title']} — *{g['implication']}*")
    lines += ["", "## 5. What to verify next", "",
              "1. Check every Tier 1 gap against the primary legal text.",
              "2. Confirm draft rules with the policy team before the next exercise.",
              "3. Re-run with the same seed to confirm the ledger replays.", ""]
    return "\n".join(lines)


def write_run(name, mode, start):
    run_dir = FIX / "runs" / name
    run_dir.mkdir(parents=True, exist_ok=True)
    entries = build_run(mode, name, start)
    with open(run_dir / "ledger.jsonl", "w", encoding="utf-8") as f:
        for e in entries:
            f.write(canonical_json(e) + "\n")
    manifest = {"run_id": name, "fixture": True, "git_commit": "fixture", "scenario": "s1_failover", "mode": mode,
                "approver": entries[0]["payload"]["approver"], "lang": "en", "model": "mock-structured-v1",
                "backend": "mock", "kb_version": entries[0]["payload"]["kb_version"],
                "config_sha256": {"configs/scenarios/s1_failover.yaml": hashlib.sha256(b"fixture").hexdigest()},
                "started_at": entries[0]["ts"]}
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    (run_dir / "aar.md").write_text(aar_md(entries, mode), encoding="utf-8")
    return run_dir, len(entries)


def write_configs():
    import yaml
    cdir = FIX / "console_configs"
    (cdir / "agents").mkdir(parents=True, exist_ok=True)
    (cdir / "scenarios").mkdir(parents=True, exist_ok=True)
    (cdir / "policies").mkdir(parents=True, exist_ok=True)
    for a in AGENTS:
        cfg = {"id": a["id"], "display_name": a["display_name"], "display_name_ar": a["display_name_ar"],
               "short_name": a["short_name"], "kind": a["kind"], "jurisdiction": "AE" if a["kind"] != "adviser" else "INTL",
               "mandate": a["mandate"], "mandate_sources": [], "retrieval_filters": FILTERS[a["id"]], "retrieval_k": 8,
               "can_message": CAN_MESSAGE[a["id"]], "action_vocabulary": VOCAB[a["id"]], "output_language": "en",
               "effort": "low"}
        (cdir / "agents" / f"{a['id']}.yaml").write_text(
            "# FIXTURE — synthetic data for UI development\n" + yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False),
            encoding="utf-8")
    scen = {"id": "s1_failover", "title": "S1 Cloud failover and AI triage degradation (fixture)",
            "title_ar": "انقطاع السحابة وتراجع أداء الفرز الآلي", "country_pack": "uae", "disclaimer": DISCLAIMER,
            "initial_state": INITIAL_STATE,
            "stages": [{"id": s["id"], "sim_time": s["sim_time"], "title": s["title"], "recipients": s["recipients"],
                        "inject_en": s["text"], "inject_ar": s["text_ar"], "state_changes": s["state_changes"],
                        "expected": s["expected"], "expected_ar": s["expected_ar"], "synthetic_data": s["synthetic"]}
                       for s in STAGES]}
    (cdir / "scenarios" / "s1_failover.yaml").write_text(
        "# FIXTURE — synthetic data for UI development\n" + yaml.safe_dump(scen, allow_unicode=True, sort_keys=False),
        encoding="utf-8")
    cards = {"cards": [
        {"id": "CC-01", "title": "Vendor pushes an emergency model patch", "recipients": ["triage", "doh"],
         "inject_en": "The model vendor offers an emergency patch for the Arabic pathway, untested on local data, deployable in one hour.",
         "state_changes": {"model_patch_available": True}, "after": "T2"},
        {"id": "CC-02", "title": "Journalist asks for the incident timeline", "recipients": ["doh", "tdra"],
         "inject_en": "A journalist requests the full incident timeline and the names of the affected regions by 17:00.",
         "state_changes": {"media_inquiry": True}, "after": "T3"},
        {"id": "CC-03", "title": "Backup region confirmed clean", "recipients": ["tdra", "data_office"],
         "inject_en": "Forensics confirm the backup region shows no ransomware indicators.",
         "state_changes": {"cyber_incident_suspected": False}, "after": "T3"},
    ]}
    (cdir / "scenarios" / "challenge_cards.yaml").write_text(
        "# FIXTURE — synthetic data for UI development\n" + yaml.safe_dump(cards, allow_unicode=True, sort_keys=False),
        encoding="utf-8")
    (cdir / "policies" / "uae_rules.yaml").write_text(
        "# FIXTURE — synthetic data for UI development\n"
        + yaml.safe_dump({"high_impact_actions": HIGH_IMPACT, "rules": RULES}, allow_unicode=True, sort_keys=False),
        encoding="utf-8")


Y3172_ROWS = [
    ("SRC", "Scenario injects and synthetic triage telemetry released stage by stage", "configs/scenarios/*.yaml",
     [(13, "Outage and failover of the hosting region")], [], False),
    ("C", "Inject delivery to the recipient institutions only", "engine.deliver()", [(8, "Who learns what, when")], [], False),
    ("PP", "Clause retrieval with each agent's knowledge slice", "majlis/retrieval.py",
     [(1, "Machine-readable legal corpus")], [("TEST-DOC-A/art-1/en", "data localisation")], False),
    ("M", "Institution agents propose claims and actions", "majlis/agents.py, llm.py", [(5, "AI embedded in a clinical workflow")], [], False),
    ("P", "Citation check and policy gate decide", "majlis/citation_check.py, policy_gate.py",
     [(10, "Policy as code")], [("TEST-DOC-B/sec-3/en", "suspension duty")], False),
    ("D", "Typed blackboard messages between agents", "engine blackboard", [(8, "Inter-agency coordination")], [], False),
    ("SINK", "Executed actions and the exercise record", "runs/<id>/ledger.jsonl", [(10, "Auditability of decisions")], [], False),
    ("MLFO", "Engine orchestrates stages, metrics and run lifecycle", "majlis/engine.py", [(7, "Exercise aligned with national strategy")], [], False),
    ("SANDBOX", "Whole exercise runs in a sandbox with fictional data", "mock backend, fixtures", [(9, "Humans exercise AI incidents safely")], [], False),
    ("LA", "Legal applicability: verbatim clause check before any action", "citation_check.py",
     [(10, "Legal certainty")], [("TEST-DOC-A/art-2/en", "breach clock")], True),
    ("HA", "Human approval for escalated actions", "approvals/*.json", [(9, "Human oversight")], [], True),
    ("AE", "Hash-chained audit evidence", "majlis/ledger.py", [(10, "Accountability")], [], True),
    ("GM", "Gap miner: policy and standards gaps", "majlis/gap_miner.py", [(10, "Policy and standards gaps")],
     [("TEST-EU/art-49/en", "global comparator")], True),
]


def write_y3172():
    import yaml
    rows = [{"node": n, "use_case": u, "majlis": m, "readiness": [{"dim": d, "note": t} for d, t in r],
             "documents": [{"clause_id": c, "note": t} for c, t in docs], "extension": ext}
            for n, u, m, r, docs, ext in Y3172_ROWS]
    (FIX / "console_configs" / "y3172_mapping.yaml").write_text(
        "# FIXTURE placeholder — the lead writes configs/y3172_mapping.yaml\n"
        + yaml.safe_dump({"rows": rows}, allow_unicode=True, sort_keys=False), encoding="utf-8")


def main():
    t0 = datetime(2026, 11, 9, 8, 0, 0, tzinfo=timezone.utc)
    for name, mode, start in [("fixture_s1_governed", "governed", t0),
                              ("fixture_s1_ungoverned", "ungoverned", t0 + timedelta(minutes=20))]:
        d, n = write_run(name, mode, start)
        print(f"wrote {d.relative_to(ROOT)} ({n} entries)")
    write_configs()
    write_y3172()
    print("wrote tests/fixtures/console_configs/")


if __name__ == "__main__":
    main()
