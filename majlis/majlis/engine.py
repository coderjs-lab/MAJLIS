"""Scenario engine: owns time, state and visibility; runs the stage loop and
writes every step to the hash-chained ledger.

Fictional training exercise. Agents simulate institutions; nothing here is an
official position of any real institution.

The LLM proposes; code decides. The gate sees only engine state. Governed and
ungoverned runs differ only in whether gate decisions are enforced.
"""
from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

from majlis import aar, citation_check, gap_miner, metrics
from majlis.agents import Agent, LegalAdviser, TurnOutcome, load_agent_configs, load_duties, make_agent
from majlis.ledger import Ledger, file_sha256, git_commit, load_entries, write_manifest
from majlis.llm import LLMResult, backend_name, model_name
from majlis.policy_gate import PolicyGate, load_policy_file
from majlis.retrieval import KB
from majlis.schemas import (AgentConfig, AgentTurn, Claim, EvidenceItem, GapCandidate, LedgerEntry,
                            ProposedAction, Scenario, Stage)

ROOT = Path(__file__).resolve().parents[1]
MAX_ADVICE_PER_STAGE = 3
MAX_NARRATED_GAPS = 6
APPROVERS = ("reject_all", "approve_all", "interactive")
MODES = ("governed", "ungoverned")

EventHook = Callable[[LedgerEntry], None]


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------

def _resolve(p: Path | str) -> Path:
    p = Path(p)
    if p.is_absolute() or p.exists():
        return p
    return ROOT / p


def load_scenario(path: Path) -> Scenario:
    data = yaml.safe_load(_resolve(path).read_text(encoding="utf-8")) or {}
    return Scenario.model_validate(data)


def find_scenario(name_or_path: str | Path) -> Path:
    p = Path(name_or_path)
    if p.suffix in (".yaml", ".yml"):
        return _resolve(p)
    return ROOT / "configs" / "scenarios" / f"{name_or_path}.yaml"


def load_pack(pack: str) -> dict:
    return yaml.safe_load((ROOT / "configs" / "countries" / f"{pack}.yaml").read_text(encoding="utf-8")) or {}


def load_challenge_cards(path: Path | None = None) -> dict[str, Stage]:
    p = path or ROOT / "configs" / "scenarios" / "challenge_cards.yaml"
    data = yaml.safe_load(Path(p).read_text(encoding="utf-8")) or {}
    return {c["id"]: Stage.model_validate(c) for c in data.get("cards") or []}


def insert_stages(stages: list[Stage], extra: list[Stage] | None, after: str | None) -> list[Stage]:
    if not extra:
        return list(stages)
    out = list(stages)
    if after is None:
        return out + list(extra)
    ids = [s.id for s in out]
    if after not in ids:
        raise ValueError(f"--after stage {after!r} not in scenario stages {ids}")
    i = ids.index(after) + 1
    return out[:i] + list(extra) + out[i:]


# ---------------------------------------------------------------------------
# the run
# ---------------------------------------------------------------------------

class _Run:
    def __init__(self, scenario: Scenario, scen_path: Path, *, mode: str, approver: str, lang: str, pack: str,
                 stages: list[Stage], run_dir: Path, run_id: str, kb_dir: Path, rules_path: Path,
                 on_event: EventHook | None, approval_timeout: float):
        self.sc = scenario
        self.mode, self.approver, self.lang = mode, approver, lang
        self.stages = stages
        self.run_dir, self.run_id = run_dir, run_id
        self.on_event = on_event
        self.approval_timeout = approval_timeout
        self.t0 = time.monotonic()

        self.pack = load_pack(pack)
        agents_dir = _resolve(self.pack.get("agents_dir", "configs/agents"))
        cfgs = load_agent_configs(agents_dir)
        order = [a for a in self.pack.get("agents") or [] if a in cfgs] or list(cfgs)
        order += [a for a in cfgs if a not in order]
        self.cfgs: dict[str, AgentConfig] = {a: cfgs[a] for a in order}
        self.duties_path = _resolve(self.pack.get("duties", "configs/duties.yaml"))
        self.duties = load_duties(self.duties_path)
        self.kb = KB.load(kb_dir)
        self.rules_path = rules_path
        rules, high_impact = load_policy_file(rules_path)
        self.gate = PolicyGate(rules, self.kb, high_impact, {a: c.action_vocabulary for a, c in self.cfgs.items()})
        self.agents: dict[str, Agent] = {a: make_agent(c, self.kb, self.duties, lang) for a, c in self.cfgs.items()}
        self.adviser: Optional[LegalAdviser] = next(
            (ag for ag in self.agents.values() if isinstance(ag, LegalAdviser)), None)
        self.institutions = [a for a, c in self.cfgs.items() if c.kind == "institution"]
        self.cov_path = _resolve(self.pack.get("standards_coverage", "configs/standards_coverage.yaml"))
        self.standards_coverage = (yaml.safe_load(self.cov_path.read_text(encoding="utf-8")) or {}
                                   if self.cov_path.exists() else {})

        self.state: dict[str, Any] = dict(scenario.initial_state)
        # visibility memory
        self.injects: dict[str, list[str]] = {a: [] for a in self.cfgs}      # injects delivered to each agent
        self.board: list[dict] = []                                           # routed messages
        self.own: dict[str, list[str]] = {a: [] for a in self.cfgs}           # own earlier turns
        self.ledger = Ledger(run_dir, run_id)
        scen_files = [scen_path, self.duties_path, rules_path, ROOT / "configs" / "countries" / f"{pack}.yaml",
                      *sorted(agents_dir.glob("*.yaml"))]
        if self.cov_path.exists():
            scen_files.append(self.cov_path)
        self.config_hashes = {str(_rel(p)): file_sha256(p) for p in scen_files if Path(p).exists()}

    # -- ledger -------------------------------------------------------------
    def log(self, stage: str | None, actor: str, event_type: str, payload: dict) -> LedgerEntry:
        e = self.ledger.append(stage, actor, event_type, payload)
        if self.on_event:
            try:
                self.on_event(e)
            except Exception:
                pass
        return e

    # -- visibility -----------------------------------------------------------
    def what_you_know(self, agent: str, stage_idx: int) -> list[str]:
        out = list(self.injects[agent])
        kind = self.cfgs[agent].kind
        for m in self.board:
            t = m["msg_type"]
            if t in ("request", "advice") and agent in m["to"]:
                out.append(f"[{m['stage']}] {t.upper()} from {m['from']}: {m['text']}")
            elif t == "assessment" and agent in m["to"] and m["from"] != agent and m["stage_idx"] < stage_idx:
                out.append(f"[{m['stage']}] ASSESSMENT by {m['from']}: {m['text']}")
            elif t in ("gate_decision", "human_decision") and agent in m["to"]:
                out.append(f"[{m['stage']}] {t.upper().replace('_', ' ')}: {m['text']}")
        out += self.own[agent]
        return out

    def _post(self, stage: Stage, stage_idx: int, msg_type: str, frm: str, to: list[str], content: dict,
              text: str) -> None:
        self.board.append({"stage": stage.id, "stage_idx": stage_idx, "msg_type": msg_type, "from": frm,
                           "to": list(to), "text": text})
        self.log(stage.id, frm, "message", {"msg_type": msg_type, "from": frm, "to": list(to), "content": content})

    # -- llm/retrieval logging -----------------------------------------------
    def _log_retrieval(self, stage: str | None, agent: str, query: str, filters: dict,
                       evidence: list[EvidenceItem]) -> None:
        self.log(stage, agent, "retrieval", {
            "agent_id": agent, "query": query, "filters": filters,
            "results": [{"clause_id": e.clause_id, "doc_title": e.doc_title, "article": e.article,
                         "score": round(float(e.score), 6)} for e in evidence]})

    def _log_llm(self, stage: str | None, agent: str, purpose: str, r: LLMResult) -> None:
        self.log(stage, agent, "llm_call", {
            "agent_id": agent, "purpose": purpose, "model": r.model, "backend": r.backend, "effort": r.effort,
            "prompt_sha256": r.prompt_sha256, "system": r.system, "user": r.user, "raw_output": r.raw_text,
            "usage": r.usage, "latency_ms": r.latency_ms, "attempts": r.attempts, "error": r.error})

    def _check(self, stage: str | None, agent: str, rnd: int, claims: list[Claim],
               evidence: list[EvidenceItem]) -> dict[str, str]:
        results = citation_check.check_claims(claims, {e.clause_id for e in evidence}, self.kb)
        counts: dict[str, int] = {}
        for r in results:
            counts[r.status] = counts.get(r.status, 0) + 1
        self.log(stage, "engine", "citation_check", {
            "agent_id": agent, "round": rnd, "results": [r.model_dump() for r in results], "counts": counts})
        return {r.claim_id: r.status for r in results}

    # -- turns ---------------------------------------------------------------
    @staticmethod
    def _namespace(turn: AgentTurn, agent: str, stage: str, rnd: int) -> None:
        """Make claim/action ids unique across the run (metrics join on them)."""
        pre = f"{agent}-{stage}-r{rnd}-"
        cmap = {}
        for c in turn.claims:
            new = c.claim_id if c.claim_id.startswith(pre) else pre + c.claim_id
            cmap[c.claim_id] = new
            c.claim_id = new
        for a in turn.proposed_actions:
            a.action_id = a.action_id if a.action_id.startswith(pre) else pre + a.action_id
            a.legal_basis_claim_ids = [cmap.get(x, x if x.startswith(pre) else pre + x)
                                       for x in a.legal_basis_claim_ids]

    def _run_round(self, stage: Stage, idx: int, rnd: int, agents: list[str],
                   inbox: dict[str, list[str]]) -> list[tuple[str, TurnOutcome | Exception]]:
        jobs = []
        for a in agents:
            jobs.append((a, dict(
                stage_id=stage.id, sim_time=stage.sim_time, round_no=rnd,
                what_you_know=self.what_you_know(a, idx),
                inject_texts=self._inject_query_texts(stage) if a in stage.recipients else [],
                messages=inbox.get(a, []))))

        def work(a: str, kw: dict):
            try:
                return self.agents[a].take_turn(**kw)
            except Exception as e:  # retrieval / unexpected failure: recorded, run continues
                return e

        if not jobs:
            return []
        with ThreadPoolExecutor(max_workers=max(1, len(jobs))) as ex:
            futs = [(a, ex.submit(work, a, kw)) for a, kw in jobs]
            return [(a, f.result()) for a, f in futs]

    def _inject_query_texts(self, stage: Stage) -> list[str]:
        return [t for t in (stage.inject_en, stage.inject_ar) if t]

    def _record_turn(self, stage: Stage, idx: int, rnd: int, agent: str, out: TurnOutcome | Exception,
                     summary: dict, requests_out: list[tuple[str, str, str, int]]) -> None:
        if isinstance(out, Exception):
            self.log(stage.id, agent, "agent_error", {"agent_id": agent, "error": f"{type(out).__name__}: {out}",
                                                      "attempts": 0, "round": rnd})
            return
        self._log_retrieval(stage.id, agent, out.query, out.filters, out.evidence)
        self._log_llm(stage.id, agent, "agent_turn", out.llm)
        if out.turn is None:
            self.log(stage.id, agent, "agent_error", {"agent_id": agent, "error": out.error or "no output",
                                                      "attempts": out.llm.attempts, "round": rnd})
            return
        turn = out.turn
        self._namespace(turn, agent, stage.id, rnd)
        payload = {"agent_id": agent, "round": rnd, "turn": turn.model_dump(),
                   "evidence_clause_ids": [e.clause_id for e in out.evidence]}
        if out.dropped_duties:
            payload["dropped_duties"] = out.dropped_duties
        if out.dropped_requests:
            payload["dropped_requests"] = out.dropped_requests
        self.log(stage.id, agent, "agent_turn", payload)
        status = self._check(stage.id, agent, rnd, turn.claims, out.evidence)

        cfg = self.cfgs[agent]
        for action in turn.proposed_actions:
            if cfg.kind == "application":
                self._gate(stage, idx, agent, action, summary)
            elif action.action_type not in cfg.action_vocabulary:
                d = self.gate.decide(action, agent, dict(self.state), self.mode)
                self.log(stage.id, "gate", "gate_decision", d.model_dump())
                summary["blocked"].append(action.action_id)
            else:
                summary["institution_actions"].append({"agent_id": agent, "action_id": action.action_id,
                                                       "action_type": action.action_type})

        verified = [c for c in turn.claims if status.get(c.claim_id) == "VERIFIED"]
        content = {"situation_summary": turn.situation_summary,
                   "verified_claims": [c.model_dump() for c in verified],
                   "proposed_actions": [a.action_type for a in turn.proposed_actions],
                   "round": rnd}
        text = turn.situation_summary + "".join(
            f" | {c.statement} [{c.clause_id}: \"{c.quote}\"]" for c in verified)
        self._post(stage, idx, "assessment", agent, [i for i in self.institutions if i != agent], content, text)
        for r in turn.requests:
            requests_out.append((agent, r.to_agent, r.question, rnd))
        self.own[agent].append(f"[{stage.id} r{rnd}] YOUR EARLIER TURN: {turn.situation_summary} "
                               f"(proposed: {', '.join(a.action_type for a in turn.proposed_actions) or 'none'})")

    # -- gate + human --------------------------------------------------------
    def _gate(self, stage: Stage, idx: int, agent: str, action: ProposedAction, summary: dict) -> None:
        d = self.gate.decide(action, agent, dict(self.state), self.mode, lang=self.lang)
        self.log(stage.id, "gate", "gate_decision", d.model_dump())
        to = [agent, *self.institutions]
        txt = f"{action.action_type} -> {d.decision} {d.status_code}" + (f" ({d.message})" if d.message else "") + \
              ("" if d.enforced else " [not enforced: ungoverned]")
        self._post(stage, idx, "gate_decision", "gate", to,
                   {"action_id": d.action_id, "agent_id": agent, "action_type": d.action_type,
                    "decision": d.decision, "status_code": d.status_code, "enforced": d.enforced,
                    "rule_ids": d.rule_ids, "clause_id": d.clause_id}, txt)
        if not d.enforced or d.decision == "ALLOW":
            summary["allowed"].append(action.action_id)
            return
        if d.decision == "DENY":
            summary["blocked"].append(action.action_id)
            return
        summary["escalated"].append(action.action_id)
        decision, by = self._human(action.action_id)
        self.log(stage.id, "approver", "human_decision", {
            "action_id": action.action_id, "agent_id": agent, "decision": decision, "approver": by,
            "rule_ids": d.rule_ids})
        self._post(stage, idx, "human_decision", "approver", list(self.cfgs),
                   {"action_id": action.action_id, "decision": decision, "approver": by},
                   f"{action.action_type}: human {decision} ({by})")
        (summary["allowed"] if decision == "approve" else summary["blocked"]).append(action.action_id)

    def _human(self, action_id: str) -> tuple[str, str]:
        if self.approver == "approve_all":
            return "approve", "simulated:approve_all"
        if self.approver == "reject_all":
            return "reject", "simulated:reject_all"
        appr = self.run_dir / "approvals"
        appr.mkdir(exist_ok=True)
        f = appr / f"{action_id}.json"
        deadline = time.monotonic() + self.approval_timeout
        while time.monotonic() < deadline:
            if f.exists():
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    dec = "approve" if str(data.get("decision", "")).lower() == "approve" else "reject"
                    return dec, f"human:{data.get('by') or 'unknown'}"
                except (json.JSONDecodeError, OSError):
                    pass
            time.sleep(0.5)
        return "reject", "timeout"

    # -- adviser -------------------------------------------------------------
    def _advise(self, stage: Stage, idx: int, reqs: list[tuple[str, str, str]], budget: list[int],
                inbox: dict[str, list[str]], open_requests: list[dict]) -> None:
        todo = []
        for asker, to, q in reqs:
            if budget[0] > 0 and self.adviser is not None:
                budget[0] -= 1
                todo.append((asker, q))
            else:
                open_requests.append({"from": asker, "to": to, "question": q, "reason": "advice cap reached"})
        if not todo:
            return
        with ThreadPoolExecutor(max_workers=len(todo)) as ex:
            futs = [(asker, q, ex.submit(self._safe_answer, q, asker, stage.id)) for asker, q in todo]
            results = [(asker, q, f.result()) for asker, q, f in futs]
        aid = self.adviser.id
        for n, (asker, q, out) in enumerate(results, 1):
            if isinstance(out, Exception):
                self.log(stage.id, aid, "agent_error", {"agent_id": aid, "error": f"{type(out).__name__}: {out}",
                                                        "attempts": 0})
                open_requests.append({"from": asker, "to": aid, "question": q, "reason": "adviser error"})
                continue
            self._log_retrieval(stage.id, aid, out.query, out.filters, out.evidence)
            self._log_llm(stage.id, aid, "advice", out.llm)
            if out.answer is None:
                self.log(stage.id, aid, "agent_error", {"agent_id": aid, "error": out.error or "no output",
                                                        "attempts": out.llm.attempts})
                open_requests.append({"from": asker, "to": aid, "question": q, "reason": "adviser error"})
                continue
            ans = out.answer
            pre = f"{aid}-{stage.id}-q{n}-"
            for c in ans.claims:
                c.claim_id = pre + c.claim_id
            claims = list(ans.claims) + [
                Claim(claim_id=f"{pre}ge{i + 1}", statement=g.how_it_handles, claim_type="recommendation",
                      clause_id=g.clause_id, quote=g.quote) for i, g in enumerate(ans.global_examples)]
            status = self._check(stage.id, aid, 1, claims, out.evidence)
            verified = [c for c in ans.claims if status.get(c.claim_id) == "VERIFIED"]
            content = {"question": q, "asker": asker, "answer": ans.model_dump(),
                       "citation_status": status,
                       "evidence_clause_ids": [e.clause_id for e in out.evidence]}
            text = ans.answer_summary + "".join(
                f" | {c.statement} [{c.clause_id}: \"{c.quote}\"]" for c in verified)
            self._post(stage, idx, "advice", aid, [asker], content, text)
            inbox.setdefault(asker, []).append(f"ADVICE: {ans.answer_summary}")

    def _safe_answer(self, q: str, asker: str, stage_id: str):
        try:
            return self.adviser.answer(q, asker, stage_id)
        except Exception as e:
            return e

    def _route_requests(self, stage: Stage, idx: int, reqs: list[tuple[str, str, str, int]],
                        budget: list[int], inbox: dict[str, list[str]], open_requests: list[dict],
                        deliver_now: bool = True) -> None:
        adv_id = self.adviser.id if self.adviser else None
        for asker, to, q, rnd in reqs:
            self._post(stage, idx, "request", asker, [to], {"question": q, "round": rnd}, q)
            if to != adv_id:
                if deliver_now:
                    inbox.setdefault(to, []).append(f"REQUEST from {asker}: {q}")
                else:  # no round 3: the recipient sees it in its next turn
                    open_requests.append({"from": asker, "to": to, "question": q, "reason": "delivered next stage"})
        self._advise(stage, idx, [(a, t, q) for a, t, q, _ in reqs if t == adv_id], budget, inbox, open_requests)

    # -- stage loop ----------------------------------------------------------
    def run_stage(self, idx: int, stage: Stage) -> None:
        self.state.update(stage.state_changes)
        self.log(stage.id, "engine", "inject", {
            "stage_id": stage.id, "sim_time": stage.sim_time, "title": stage.title,
            "recipients": stage.recipients, "text": stage.inject_en, "text_ar": stage.inject_ar,
            "state_changes": stage.state_changes, "state_after": dict(self.state), "expected": stage.expected,
            "synthetic_data": stage.synthetic_data})
        text = stage.inject_ar if (self.lang == "ar" and stage.inject_ar) else stage.inject_en
        label = " (synthetic data, fictional numbers)" if stage.synthetic_data else ""
        for a in stage.recipients:
            if a in self.injects:
                self.injects[a].append(f"[{stage.id} {stage.sim_time}] INJECT{label}: {text}")

        summary = {"allowed": [], "blocked": [], "escalated": [], "institution_actions": []}
        open_requests: list[dict] = []
        budget = [MAX_ADVICE_PER_STAGE]
        adv_id = self.adviser.id if self.adviser else None

        r1 = [a for a in self.cfgs if a in stage.recipients and a != adv_id]
        inbox: dict[str, list[str]] = {}
        reqs: list[tuple[str, str, str, int]] = []
        for agent, out in self._run_round(stage, idx, 1, r1, {}):
            self._record_turn(stage, idx, 1, agent, out, summary, reqs)
        self._route_requests(stage, idx, reqs, budget, inbox, open_requests)

        r2 = [a for a in self.cfgs if a in inbox and a != adv_id]
        reqs2: list[tuple[str, str, str, int]] = []
        for agent, out in self._run_round(stage, idx, 2, r2, inbox):
            self._record_turn(stage, idx, 2, agent, out, summary, reqs2)
        # no round 3: round-2 requests are posted (delivered next stage); adviser answers within the cap
        self._route_requests(stage, idx, reqs2, budget, {}, open_requests, deliver_now=False)

        self.log(stage.id, "engine", "stage_end", {
            "stage_id": stage.id, "allowed": summary["allowed"], "blocked": summary["blocked"],
            "escalated": summary["escalated"], "institution_actions": summary["institution_actions"],
            "open_requests": open_requests, "state": dict(self.state)})

    # -- after the last stage --------------------------------------------------
    def finish(self) -> None:
        entries = load_entries(self.ledger.path)
        gaps = gap_miner.mine(entries, self.duties, self.standards_coverage)
        for g in self._pick_for_narration(gaps):
            self._narrate(g)
        for g in gaps:
            self.log(None, "gap_miner", "gap_candidate", g.model_dump())
        m = metrics.compute(load_entries(self.ledger.path))
        self.log(None, "engine", "metrics", m)

    def _pick_for_narration(self, gaps: list[GapCandidate]) -> list[GapCandidate]:
        if self.adviser is None:
            return []
        picked, seen = [], set()
        for g in gaps:  # one per pattern first, then the rest
            if g.pattern not in seen:
                seen.add(g.pattern)
                picked.append(g)
        picked += [g for g in gaps if g not in picked]
        return picked[:MAX_NARRATED_GAPS]

    def _narrate(self, g: GapCandidate) -> None:
        aid = self.adviser.id
        ev = [self._evidence_item(c) for c in g.evidence.clause_ids]
        try:
            out = self.adviser.narrate_gap(g.model_dump(), [e for e in ev if e is not None])
        except Exception as e:
            self.log(None, aid, "agent_error", {"agent_id": aid, "error": f"{type(e).__name__}: {e}", "attempts": 0,
                                                "gap_id": g.gap_id})
            return
        self._log_retrieval(None, aid, out.query, out.filters, out.evidence)
        self._log_llm(None, aid, "gap_narrative", out.llm)
        if out.narration is None:
            self.log(None, aid, "agent_error", {"agent_id": aid, "error": out.error or "no output",
                                                "attempts": out.llm.attempts, "gap_id": g.gap_id})
            return
        n = out.narration
        pre = f"{aid}-{g.gap_id}-"
        claims = [Claim(claim_id=f"{pre}ge{i + 1}", statement=x.how_it_handles, claim_type="recommendation",
                        clause_id=x.clause_id, quote=x.quote) for i, x in enumerate(n.global_examples)]
        status = self._check(None, aid, 1, claims, out.evidence) if claims else {}
        verified = [x for i, x in enumerate(n.global_examples) if status.get(f"{pre}ge{i + 1}") == "VERIFIED"]
        g.detail = {**g.detail, "template_title": g.title, "template_description": g.description,
                    "narrative": {"title": n.title, "description": n.description}, "narrated_by": aid,
                    "unverified_examples_dropped": len(n.global_examples) - len(verified)}
        g.description = n.description
        g.implication = n.implication
        g.next_step = n.next_step
        g.global_examples = verified
        g.insufficient_evidence = not verified

    def _evidence_item(self, clause_id: str) -> EvidenceItem | None:
        c = self.kb.get(clause_id)
        if c is None:
            return None
        return EvidenceItem(**{k: getattr(c, k) for k in EvidenceItem.model_fields if hasattr(c, k)})

    # -- entry point -----------------------------------------------------------
    def run_start(self, scen_path: Path) -> None:
        write_manifest(self.run_dir, {
            "run_id": self.run_id, "scenario_id": self.sc.id, "scenario_file": str(_rel(scen_path)),
            "git_commit": git_commit(ROOT), "config_sha256": self.config_hashes, "kb_version": self.kb.version,
            "kb_dense_available": getattr(self.kb, "dense_available", False),
            "model": model_name() if backend_name() == "glm" else "mock", "backend": backend_name(),
            "mode": self.mode, "approver": self.approver, "lang": self.lang, "pack": self.pack.get("id"),
            "stages": [s.id for s in self.stages], "rules_file": str(_rel(self.rules_path)),
            "disclaimer": self.sc.disclaimer})
        self.log(None, "engine", "run_start", {
            "scenario_id": self.sc.id, "title": self.sc.title, "title_ar": self.sc.title_ar,
            "disclaimer": self.sc.disclaimer, "mode": self.mode, "approver": self.approver, "lang": self.lang,
            "model": model_name() if backend_name() == "glm" else "mock", "backend": backend_name(),
            "kb_version": self.kb.version, "initial_state": dict(self.state),
            "agents": [{"id": c.id, "display_name": c.display_name, "display_name_ar": c.display_name_ar,
                        "short_name": c.short_name, "kind": c.kind, "mandate": c.mandate,
                        "mandate_verified": bool(c.mandate_sources)} for c in self.cfgs.values()],
            "stages": [{"id": s.id, "sim_time": s.sim_time, "title": s.title, "recipients": s.recipients,
                        "expected": s.expected, "expected_ar": s.expected_ar} for s in self.stages]})

    def run_end(self, status: str, error: str | None = None) -> None:
        counts: dict[str, int] = {}
        for e in load_entries(self.ledger.path):
            counts[e.get("event_type")] = counts.get(e.get("event_type"), 0) + 1
        p = {"status": status, "counts": counts, "duration_s": round(time.monotonic() - self.t0, 3)}
        if error:
            p["error"] = error
        self.log(None, "engine", "run_end", p)


def _rel(p: Path | str) -> Path:
    p = Path(p).resolve()
    try:
        return p.relative_to(ROOT)
    except ValueError:
        return p


def run_scenario(scenario_path: Path, *, mode: str, approver: str, lang: str, pack: str = "uae",
                 extra_stages: list[Stage] | None = None, runs_dir: Path = Path("runs"),
                 run_id: str | None = None, extra_after: str | None = None, kb_dir: Path | None = None,
                 rules_path: Path | None = None, on_event: EventHook | None = None,
                 approval_timeout: float | None = None) -> Path:
    """Run a scenario end to end and return the run directory."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    if approver not in APPROVERS:
        raise ValueError(f"approver must be one of {APPROVERS}")
    if lang not in ("en", "ar"):
        raise ValueError("lang must be en or ar")
    scen_path = find_scenario(scenario_path)
    sc = load_scenario(scen_path)
    pack_cfg = load_pack(pack)
    stages = insert_stages(sc.stages, extra_stages, extra_after)
    rid = run_id or f"{datetime.now().strftime('%Y%m%d-%H%M%S')}_{sc.id}_{mode}_{lang}"
    rdir = _resolve(runs_dir) / rid if not Path(runs_dir).is_absolute() else Path(runs_dir) / rid
    n = 1
    while (rdir / "ledger.jsonl").exists():
        n += 1
        rdir = rdir.parent / f"{rid}-{n}"
    rid = rdir.name
    timeout = approval_timeout if approval_timeout is not None else float(
        os.environ.get("MAJLIS_APPROVAL_TIMEOUT", "600"))
    run = _Run(sc, scen_path, mode=mode, approver=approver, lang=lang, pack=pack, stages=stages, run_dir=rdir,
               run_id=rid, kb_dir=_resolve(kb_dir or pack_cfg.get("kb_dir", "kb")),
               rules_path=_resolve(rules_path or pack_cfg.get("rules", "configs/policies/uae_rules.yaml")),
               on_event=on_event, approval_timeout=timeout)
    run.run_start(scen_path)
    try:
        for i, st in enumerate(stages):
            run.run_stage(i, st)
        run.finish()
    except Exception as e:
        run.run_end("failed", f"{type(e).__name__}: {e}")
        raise
    run.run_end("completed")
    (rdir / "aar.md").write_text(aar.render_aar(load_entries(run.ledger.path)), encoding="utf-8")
    return rdir
