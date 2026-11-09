"""Verbatim citation checker.

A model's legal claim counts only if its quote appears in the cited clause's
stored text. Checks run in a fixed order (CONTRACTS.md), first match wins:

    1. legal claim type, missing clause_id or quote  -> UNSUPPORTED
    2. non-legal claim type, no clause_id            -> NO_CITATION
    3. clause_id not in the KB                       -> UNKNOWN_CLAUSE
    4. clause not among the evidence shown to agent  -> NOT_RETRIEVED
    5. normalised quote is a substring of the clause -> VERIFIED
    6. rapidfuzz partial_ratio >= 90                 -> NEAR_MATCH
    7. otherwise                                     -> FAILED

Only VERIFIED claims may be used as a legal basis downstream. No LLM is called.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable, Protocol

from rapidfuzz import fuzz

from majlis.schemas import LEGAL_CLAIM_TYPES, CitationResult, Claim, Clause

NEAR_MATCH_THRESHOLD = 90.0
MIN_QUOTE_WORDS = 3       # a quote must have at least 3 words ...
MIN_QUOTE_CHARS = 15      # ... or at least 15 characters (Arabic words are short)
STATUSES = ("VERIFIED", "NEAR_MATCH", "FAILED", "NOT_RETRIEVED",
            "UNKNOWN_CLAUSE", "UNSUPPORTED", "NO_CITATION")


class ClauseLookup(Protocol):
    """The only part of retrieval.KB this module needs."""
    def get(self, clause_id: str) -> Clause | None: ...


_QUOTE_MAP = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"', "″": '"',
    "«": '"', "»": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-",
    "―": "-", "−": "-",
    # Arabic: alef forms -> bare alef, alef maqsura -> yeh
    "آ": "ا", "أ": "ا", "إ": "ا", "ٱ": "ا",
    "ى": "ي",
})
# Arabic diacritics (tanween, harakat, shadda, sukun), superscript alef, tatweel.
_ARABIC_STRIP = re.compile("[ً-ْٰـ]")
_WS = re.compile(r"\s+")
_WRAPPING = " \"'.\u2026"


def normalise_quote(text: str | None) -> str:
    """Normalise text for verbatim comparison. Applied identically to the
    quote and the clause text, so it can only remove presentation noise."""
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", text)
    t = t.translate(_QUOTE_MAP)
    t = _ARABIC_STRIP.sub("", t)
    t = _WS.sub(" ", t).strip()
    return t.casefold()


def _as_claim(c: Claim | dict) -> Claim:
    return c if isinstance(c, Claim) else Claim(**c)


def check_claim(claim: Claim | dict, evidence_ids: set[str], kb: ClauseLookup) -> CitationResult:
    c = _as_claim(claim)

    def result(status: str, score: float = 0.0, note: str | None = None) -> CitationResult:
        return CitationResult(claim_id=c.claim_id, clause_id=c.clause_id, status=status,
                              score=round(score, 1), claim_type=c.claim_type, note=note)

    is_legal = c.claim_type in LEGAL_CLAIM_TYPES
    if is_legal and (not c.clause_id or not (c.quote or "").strip()):
        return result("UNSUPPORTED", note="legal claim without clause_id and quote")
    if not is_legal and not c.clause_id:
        return result("NO_CITATION")
    clause = kb.get(c.clause_id)
    if clause is None:
        return result("UNKNOWN_CLAUSE", note="clause_id not in knowledge base")
    if c.clause_id not in evidence_ids:
        return result("NOT_RETRIEVED", note="clause was not in the evidence shown to the agent")
    # Models often wrap a quote in quotation marks or ellipses; those are not
    # part of the clause text, so only they are trimmed from the ends.
    q = normalise_quote(c.quote).strip(_WRAPPING)
    if not q:
        # Non-legal claim citing a clause but quoting nothing: nothing to verify.
        return result("FAILED", note="clause cited without a quote")
    if len(q.split()) < MIN_QUOTE_WORDS and len(q) < MIN_QUOTE_CHARS:
        # A fragment like "the" or "72 hours" appears in many clauses and
        # proves nothing about what the clause says.
        return result("FAILED", note="quote too short to establish the claim")
    text = normalise_quote(clause.text)
    if q in text:
        return result("VERIFIED", 100.0)
    score = float(fuzz.partial_ratio(q, text))
    if score >= NEAR_MATCH_THRESHOLD:
        return result("NEAR_MATCH", score, note="quote is close to, but not exactly, the clause text")
    return result("FAILED", score, note="quote not found in clause text")


def check_claims(claims: Iterable[Claim | dict], evidence_ids: set[str], kb: ClauseLookup) -> list[CitationResult]:
    """Check every claim of one agent turn against the KB and its evidence set."""
    return [check_claim(c, set(evidence_ids), kb) for c in claims]


def summarise(results: Iterable[CitationResult | dict]) -> dict[str, int]:
    """Count results by status (all seven statuses present, zero if absent)."""
    counts = {s: 0 for s in STATUSES}
    for r in results:
        status = r.status if isinstance(r, CitationResult) else r["status"]
        counts[status] = counts.get(status, 0) + 1
    return counts
