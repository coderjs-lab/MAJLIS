"""One generic Agent class driven by AgentConfig, plus the Legal Adviser.

Agents never decide anything: they retrieve evidence, ask the LLM for a
structured proposal, and return it. Duties outside the closed vocabulary and
requests to agents outside can_message are dropped here and recorded.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional

import yaml
from pydantic import BaseModel, Field

from majlis import prompts
from majlis.llm import LLMResult, structured_call
from majlis.schemas import (AdviceAnswer, AgentConfig, AgentTurn, EvidenceItem, GapNarrative, GlobalExample,
                            RetrievalFilters)


def load_agent_configs(dir: Path) -> dict[str, AgentConfig]:
    out: dict[str, AgentConfig] = {}
    for p in sorted(Path(dir).glob("*.yaml")):
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        cfg = AgentConfig.model_validate(data)
        out[cfg.id] = cfg
    return out


def load_duties(path: Path) -> list[str]:
    return list((yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}).get("duties") or [])


class GapNarration(GapNarrative):
    """GapNarrative plus cited global examples (local to the engine's narration call)."""
    global_examples: List[GlobalExample] = Field(default_factory=list)
    insufficient_evidence: bool = False


@dataclass
class TurnOutcome:
    turn: Optional[AgentTurn]
    evidence: list[EvidenceItem]
    llm: LLMResult
    query: str
    filters: dict
    dropped_duties: list[str] = field(default_factory=list)
    dropped_requests: list[dict] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class AdviceOutcome:
    answer: Optional[AdviceAnswer]
    evidence: list[EvidenceItem]
    llm: LLMResult
    query: str
    filters: dict
    error: Optional[str] = None


@dataclass
class NarrationOutcome:
    narration: Optional[GapNarration]
    evidence: list[EvidenceItem]
    llm: LLMResult
    query: str
    filters: dict
    error: Optional[str] = None


def _trim(s: str, n: int = 1200) -> str:
    s = " ".join((s or "").split())
    return s[:n]


class Agent:
    def __init__(self, cfg: AgentConfig, kb: Any, duties: list[str], lang: str | None = None):
        self.cfg = cfg
        self.kb = kb
        self.duties = list(duties)
        self.lang = lang or cfg.output_language
        self.system_prompt = prompts.build_system_prompt(cfg, self.duties, self.lang)  # frozen

    @property
    def id(self) -> str:
        return self.cfg.id

    def build_query(self, inject_texts: list[str], messages: list[str]) -> str:
        return _trim(" ".join([*inject_texts, *messages]))

    def retrieve(self, query: str, filters: RetrievalFilters | None, k: int) -> list[EvidenceItem]:
        if not query.strip():
            return []
        return list(self.kb.search(query, filters, k=k))

    def multi_retrieve(self, passes: list[tuple[str, RetrievalFilters, int]], cap: int) -> list[EvidenceItem]:
        """Run several (query, filters, k) passes and interleave them, de-duplicated, up to `cap`.
        Interleaving keeps the best hit of every pass in the evidence (e.g. binding law is never
        crowded out by long strategy documents)."""
        lists = [self.retrieve(q, f, k) for q, f, k in passes if q.strip()]
        out: dict[str, EvidenceItem] = {}
        for i in range(max((len(l) for l in lists), default=0)):
            for l in lists:
                if i < len(l):
                    out.setdefault(l[i].clause_id, l[i])
        return list(out.values())[:cap]

    def turn_passes(self, situational: str) -> list[tuple[str, RetrievalFilters, int]]:
        f = self.cfg.retrieval_filters
        binding = f.model_copy(update={"binding": ["binding"]})
        k = self.cfg.retrieval_k
        passes = [(situational, f, k), (situational, binding, max(3, k // 2))]
        if self.cfg.retrieval_focus:
            passes.append((_trim(f"{self.cfg.retrieval_focus} {situational}"), binding, 3))
        return passes

    def take_turn(self, *, stage_id: str, sim_time: str, round_no: int, what_you_know: list[str],
                  inject_texts: list[str], messages: list[str]) -> TurnOutcome:
        query = self.build_query(inject_texts, messages)
        filters = self.cfg.retrieval_filters
        evidence = self.multi_retrieve(self.turn_passes(query), cap=self.cfg.retrieval_k + 2)
        task = prompts.turn_task(self.cfg, stage_id=stage_id, sim_time=sim_time, round_no=round_no,
                                 duties=self.duties)
        user = prompts.build_user_prompt(evidence=evidence, what_you_know=what_you_know, task=task)
        ctx = {
            "agent_id": self.id, "kind": self.cfg.kind, "stage": stage_id, "round": round_no,
            "evidence": evidence, "vocabulary": self.cfg.action_vocabulary, "duties": self.duties,
            "can_message": self.cfg.can_message, "inject_text": " ".join(inject_texts), "messages": messages,
            "output_language": self.lang,
        }
        res = structured_call(self.system_prompt, user, AgentTurn, purpose="agent_turn", agent_id=self.id,
                              effort=self.cfg.effort, context=ctx)
        out = TurnOutcome(None, evidence, res, query, filters.model_dump(exclude_none=True), error=res.error)
        turn = res.parsed
        if turn is None:
            return out
        allowed = set(self.duties)
        out.dropped_duties = sorted({d for d in turn.responsibilities_claimed + turn.responsibilities_disclaimed
                                     if d not in allowed})
        turn.responsibilities_claimed = [d for d in dict.fromkeys(turn.responsibilities_claimed) if d in allowed]
        turn.responsibilities_disclaimed = [d for d in dict.fromkeys(turn.responsibilities_disclaimed)
                                            if d in allowed]
        keep = []
        for r in turn.requests:
            if r.to_agent in self.cfg.can_message and r.to_agent != self.id:
                keep.append(r)
            else:
                out.dropped_requests.append(r.model_dump())
        turn.requests = keep
        out.turn = turn
        return out


class LegalAdviser(Agent):
    """Answers questions from any agent; no sector filter, all jurisdictions."""

    def _filters(self) -> RetrievalFilters:
        return RetrievalFilters()

    GLOBAL_JURISDICTIONS = ["EU", "US", "SG", "INTL", "SA"]

    def adviser_passes(self, query: str) -> list[tuple[str, RetrievalFilters, int]]:
        """Overall best, binding law, and non-UAE practice (so global examples are always available)."""
        k = self.cfg.retrieval_k
        return [(query, RetrievalFilters(), k),
                (query, RetrievalFilters(binding=["binding"]), 4),
                (query, RetrievalFilters(jurisdiction=self.GLOBAL_JURISDICTIONS), 4)]

    def answer(self, question: str, asker: str, stage: str) -> AdviceOutcome:
        query = _trim(question)
        filters = self._filters()
        evidence = self.multi_retrieve(self.adviser_passes(query), cap=self.cfg.retrieval_k + 4)
        user = prompts.build_user_prompt(evidence=evidence, what_you_know=[f"{asker} asks you a question."],
                                         task=prompts.advice_task(question, asker, stage))
        ctx = {"agent_id": self.id, "kind": "adviser", "stage": stage, "evidence": evidence, "question": question,
               "asker": asker, "output_language": self.lang}
        res = structured_call(self.system_prompt, user, AdviceAnswer, purpose="advice", agent_id=self.id,
                              effort=self.cfg.effort, context=ctx)
        return AdviceOutcome(res.parsed, evidence, res, query, filters.model_dump(exclude_none=True), res.error)

    def narrate_gap(self, gap: dict, evidence: list[EvidenceItem] | None = None) -> NarrationOutcome:
        query = _trim(f"{gap.get('title', '')} {gap.get('description', '')}")
        filters = self._filters()
        found = self.multi_retrieve(self.adviser_passes(query), cap=self.cfg.retrieval_k + 4)
        merged: dict[str, EvidenceItem] = {}
        for e in [*(evidence or []), *found]:
            merged.setdefault(e.clause_id, e)
        ev = list(merged.values())
        user = prompts.build_user_prompt(evidence=ev, what_you_know=["The exercise has ended."],
                                         task=prompts.gap_task(gap))
        ctx = {"agent_id": self.id, "kind": "adviser", "stage": "post", "evidence": ev, "gap": gap,
               "question": gap.get("title"), "output_language": self.lang}
        res = structured_call(self.system_prompt, user, GapNarration, purpose="gap_narrative", agent_id=self.id,
                              effort=self.cfg.effort, context=ctx)
        return NarrationOutcome(res.parsed, ev, res, query, filters.model_dump(exclude_none=True), res.error)


def make_agent(cfg: AgentConfig, kb: Any, duties: list[str], lang: str | None = None) -> Agent:
    cls = LegalAdviser if cfg.kind == "adviser" else Agent
    return cls(cfg, kb, duties, lang)
