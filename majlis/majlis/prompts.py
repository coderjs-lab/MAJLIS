"""Prompt builders. System prompts are frozen per agent (cache-friendly);
everything that changes per stage goes into the user prompt."""
from __future__ import annotations

from typing import Iterable

from majlis.schemas import AgentConfig, EvidenceItem

SIM_DISCLAIMER = ("Fictional training exercise. You simulate a role; this is not an official position "
                  "of any real institution.")

RULES = [
    "Cite only clause ids that appear in the EVIDENCE section of the current message. Never cite a clause id "
    "you remember from elsewhere.",
    "Copy every quote exactly, character for character, from the clause text in EVIDENCE: at most 60 words, "
    "no ellipses, no corrections, and never translate a quote. A quote stays in the clause's own language.",
    "If EVIDENCE does not answer a question, put the question in insufficient_evidence. Never fill the gap "
    "from memory or general knowledge.",
    "A non-binding instrument (strategy, charter, guidance, framework, policy marked non_binding) is never an "
    "obligation: use claim_type recommendation for it.",
    "Claims of type obligation, permission, prohibition or definition must carry a clause_id and a quote.",
    "Stay inside your mandate. If a duty belongs to someone else, list it in responsibilities_disclaimed and "
    "send that agent a request (only to agents you are allowed to message).",
    "Take duties for responsibilities_claimed / responsibilities_disclaimed only from the closed duty list.",
    "Propose actions only from your action vocabulary. Anything else is rejected by code.",
    "Facts about the incident come only from WHAT YOU KNOW. Do not invent events, numbers or deadlines.",
]


def build_system_prompt(cfg: AgentConfig, duties: list[str], output_language: str | None = None) -> str:
    lang = output_language or cfg.output_language
    mandate_note = ("(unverified summary; not yet tied to source clauses)" if not cfg.mandate_sources
                    else f"(sources: {', '.join(cfg.mandate_sources)})")
    lines = [
        f"ROLE: {cfg.display_name} [id: {cfg.id}, kind: {cfg.kind}, jurisdiction: {cfg.jurisdiction}]",
        SIM_DISCLAIMER,
        "",
        f"MANDATE {mandate_note}:",
        cfg.mandate.strip(),
        "",
        "RULES:",
        *[f"{i + 1}. {r}" for i, r in enumerate(RULES)],
    ]
    if lang == "ar":
        lines.append(f"{len(RULES) + 1}. Output language is Arabic: write situation_summary, statements, "
                     "descriptions, questions and summaries in Arabic. Quotes stay in the clause's own language. "
                     "JSON keys and enum values stay in English.")
    else:
        lines.append(f"{len(RULES) + 1}. Output language is English. Quotes stay in the clause's own language.")
    lines += [
        "",
        f"ACTION VOCABULARY: {', '.join(cfg.action_vocabulary) if cfg.action_vocabulary else '(none: you answer only)'}",
        f"YOU MAY MESSAGE: {', '.join(cfg.can_message) if cfg.can_message else '(nobody)'}",
        f"CLOSED DUTY LIST: {', '.join(duties)}",
    ]
    return "\n".join(lines)


def format_evidence(evidence: Iterable[EvidenceItem]) -> str:
    out = []
    for e in evidence:
        art = f"Art. {e.article}" if e.article else "Art. ?"
        if e.paragraph:
            art += f"({e.paragraph})"
        out.append(f"[{e.clause_id}] ({e.doc_title}, {art}, {e.binding}, {e.language}) {e.text}")
    return "\n".join(out) if out else "(no clauses retrieved)"


def build_user_prompt(*, evidence: list[EvidenceItem], what_you_know: list[str], task: str) -> str:
    known = "\n".join(f"- {k}" for k in what_you_know) if what_you_know else "- (nothing yet)"
    return (f"EVIDENCE\n{format_evidence(evidence)}\n\n"
            f"WHAT YOU KNOW\n{known}\n\n"
            f"TASK\n{task.strip()}\n")


def turn_task(cfg: AgentConfig, *, stage_id: str, sim_time: str, round_no: int, duties: list[str]) -> str:
    intro = (f"Stage {stage_id} ({sim_time}), round {round_no}. " +
             ("Assess the new information delivered to you at this stage." if round_no == 1 else
              "Reconsider your assessment in light of the messages addressed to you at this stage."))
    return (
        f"{intro}\n"
        "(a) State what you now know (situation_summary). (b) Make claims, each citing a clause from EVIDENCE with "
        "a verbatim quote where it is a legal claim. (c) Propose actions from your vocabulary, each linked to the "
        "claim_ids that justify it. (d) Send requests to other agents if a duty or question belongs to them. "
        "(e) List duties you claim and duties you disclaim. (f) List questions EVIDENCE cannot answer.\n"
        f"Action vocabulary: {', '.join(cfg.action_vocabulary) or '(none)'}\n"
        f"Duty list: {', '.join(duties)}\n"
        f"can_message: {', '.join(cfg.can_message) or '(none)'}\n"
        "Return the AgentTurn JSON object."
    )


def advice_task(question: str, asker: str, stage_id: str) -> str:
    return (
        f"Stage {stage_id}. Question from {asker}:\n{question}\n\n"
        "Answer strictly from EVIDENCE. Each legal claim cites a clause from EVIDENCE with a verbatim quote. "
        "Global examples (other jurisdictions) must cite a clause_id from EVIDENCE with a verbatim quote; if "
        "EVIDENCE holds none, give no examples. Name suspected gaps. Set insufficient_evidence to true if "
        "EVIDENCE does not answer the question. Return the AdviceAnswer JSON object."
    )


def gap_task(gap: dict) -> str:
    return (
        "A deterministic detector found this candidate gap during the exercise:\n"
        f"id: {gap.get('gap_id')}, pattern: {gap.get('pattern')}, type: {gap.get('type')}\n"
        f"title: {gap.get('title')}\n"
        f"description: {gap.get('description')}\n"
        f"detector facts: {gap.get('detail')}\n\n"
        "Write a short title, description, implication and next_step strictly from the facts above and EVIDENCE. "
        "Add global_examples only if a clause in EVIDENCE shows how another jurisdiction handles this; each example "
        "cites that clause_id with a verbatim quote. If there is none, return an empty list and set "
        "insufficient_evidence to true."
    )
