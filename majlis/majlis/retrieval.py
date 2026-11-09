"""Retrieval over the clause-level KB. See CONTRACTS.md.

Pipeline (default mode "rerank"): BM25 and bge-m3 dense rankings are fused with RRF into a candidate
pool of RERANK_POOL clauses, which the bge-reranker-v2-m3 cross-encoder re-orders. BM25 alone is weak on
our eval (lay paraphrases, and Arabic questions against an English-only corpus) but widens the pool;
the cross-encoder does the precise ordering. Without the dense index or the reranker (tests, CPU-only
machines, MAJLIS_RERANK=0) the same call falls back to hybrid, then BM25.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
import warnings
from collections import Counter
from pathlib import Path
from typing import Optional

import numpy as np
from rank_bm25 import BM25Okapi

from majlis.schemas import Clause, EvidenceItem, RetrievalFilters

MODEL_NAME = "BAAI/bge-m3"
RERANK_MODEL = "BAAI/bge-reranker-v2-m3"
RRF_K = 60
TOP_N = 50
RERANK_POOL = 30

# English stopwords (closed-class words plus modal verbs that every legal clause uses)
_STOP = frozenset("""a about above after again against all am an and any are as at be because been before being
below between both but by can could did do does doing down during each few for from further had has have
having he her here hers herself him himself his how i if in into is it its itself just me more most my
myself no nor not now of off on once only or other our ours ourselves out over own same she should so some
such than that the their theirs them themselves then there these they this those through to too under
until up very was we were what when where which while who whom why will with would you your yours
yourself yourselves must shall may might also""".split())
_STEMMER = None

_HARAKAT = re.compile(r"[ً-ْٰ]")
_ALEF = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه", "ـ": None})
_WS = re.compile(r"\s+")


def normalise_for_search(text: str) -> str:
    s = unicodedata.normalize("NFKC", text or "").casefold()
    s = _HARAKAT.sub("", s).translate(_ALEF)
    return _WS.sub(" ", s).strip()


def _stem(t: str) -> str:
    global _STEMMER
    if _STEMMER is None:
        try:
            import snowballstemmer
            _STEMMER = snowballstemmer.stemmer("english").stemWord
        except ImportError:  # pragma: no cover
            _STEMMER = lambda w: w
    return _STEMMER(t)


def tokenise(text: str) -> list[str]:
    """BM25 tokens: normalised words, English stopwords dropped, English words Snowball-stemmed
    ("records"/"recorded" -> "record"); Arabic tokens are kept as normalised surface forms."""
    out = []
    for t in re.findall(r"\w+", normalise_for_search(text)):
        if t in _STOP or (len(t) < 2 and not t.isdigit()):
            continue
        out.append(_stem(t) if t.isascii() else t)
    return out


def search_field(c: Clause) -> str:
    return normalise_for_search(f"{c.heading or ''} {c.text}")


_ENCODER = None


def get_encoder():
    """Lazy, module-level cached bge-m3 encoder (CUDA if available)."""
    global _ENCODER
    if _ENCODER is None:
        import torch
        from sentence_transformers import SentenceTransformer
        dev = "cuda" if torch.cuda.is_available() else "cpu"
        m = SentenceTransformer(MODEL_NAME, device=dev)
        if dev == "cuda":
            m.half()
        _ENCODER = m
    return _ENCODER


_RERANKER = None
_RERANK_FAILED = False


def get_reranker():
    """Lazy bge-reranker-v2-m3 cross-encoder; None if disabled (MAJLIS_RERANK=0) or unavailable."""
    global _RERANKER, _RERANK_FAILED
    if _RERANKER is None and not _RERANK_FAILED:
        if os.environ.get("MAJLIS_RERANK", "1") == "0":
            _RERANK_FAILED = True
            return None
        try:
            import torch
            from sentence_transformers import CrossEncoder
            dev = "cuda" if torch.cuda.is_available() else "cpu"
            m = CrossEncoder(RERANK_MODEL, device=dev, max_length=512)
            if dev == "cuda":
                m.model.half()
            _RERANKER = m
        except Exception as e:  # pragma: no cover
            warnings.warn(f"reranker unavailable ({e}); falling back to hybrid")
            _RERANK_FAILED = True
    return _RERANKER


def embed(texts: list[str], batch_size: int = 32) -> np.ndarray:
    v = get_encoder().encode(texts, batch_size=batch_size, normalize_embeddings=True,
                             convert_to_numpy=True, show_progress_bar=len(texts) > 256)
    return np.asarray(v, dtype=np.float32)


def _passes(c: Clause, f: Optional[RetrievalFilters]) -> bool:
    if f is None:
        return True
    if f.jurisdiction is not None and c.jurisdiction not in f.jurisdiction:
        return False
    if f.sectors is not None and not set(c.sectors) & set(f.sectors):
        return False
    if f.binding is not None and c.binding not in f.binding:
        return False
    if f.language is not None and c.language not in f.language:
        return False
    return True


class KB:
    def __init__(self, clauses: dict[str, Clause], version: str,
                 dense: Optional[np.ndarray] = None, dense_ids: Optional[list[str]] = None):
        self.clauses = clauses
        self.version = version
        self.ids = list(clauses)
        self._idx = {cid: i for i, cid in enumerate(self.ids)}
        docs = [tokenise(f"{c.heading or ''} {c.text}") for c in clauses.values()]
        self._bm25 = BM25Okapi([d or ["_"] for d in docs]) if docs else None
        self._dense = None
        if dense is not None and dense_ids is not None:
            pos = {cid: i for i, cid in enumerate(dense_ids)}
            if set(pos) >= set(self.ids):
                self._dense = np.asarray(dense[[pos[c] for c in self.ids]], dtype=np.float32)
            else:
                warnings.warn("dense index missing some clause ids; dense disabled")
        self.dense_available = self._dense is not None

    @classmethod
    def load(cls, kb_dir: Path = Path("kb")) -> "KB":
        kb_dir = Path(kb_dir)
        path = kb_dir / "clauses" / "clauses.jsonl"
        raw = path.read_bytes()
        version = hashlib.sha256(raw).hexdigest()
        clauses: dict[str, Clause] = {}
        for line in raw.decode("utf-8").splitlines():
            if line.strip():
                c = Clause.model_validate_json(line)
                clauses[c.clause_id] = c
        dense = ids = None
        idx = kb_dir / "index"
        if (idx / "dense.npy").exists() and (idx / "ids.json").exists():
            meta = json.loads((idx / "meta.json").read_text()) if (idx / "meta.json").exists() else {}
            if meta.get("kb_version") != version:
                warnings.warn(f"stale dense index in {idx} (kb_version mismatch); ignoring it. "
                              "Re-run scripts/build_index.py")
            else:
                try:
                    import sentence_transformers  # noqa: F401
                    dense = np.load(idx / "dense.npy")
                    ids = json.loads((idx / "ids.json").read_text())
                except Exception as e:  # pragma: no cover
                    warnings.warn(f"dense index unavailable: {e}")
        return cls(clauses, version, dense, ids)

    def get(self, clause_id: str) -> Optional[Clause]:
        return self.clauses.get(clause_id)

    def parallel(self, clause_id: str) -> Optional[Clause]:
        c = self.get(clause_id)
        return self.get(c.parallel_clause_id) if c and c.parallel_clause_id else None

    def stats(self) -> dict:
        cs = list(self.clauses.values())
        return {
            "docs": len({c.doc_id for c in cs}),
            "clauses": len(cs),
            "by_language": dict(Counter(c.language for c in cs)),
            "by_jurisdiction": dict(Counter(c.jurisdiction for c in cs)),
            "by_binding": dict(Counter(c.binding for c in cs)),
            "by_tier": dict(Counter(c.tier for c in cs)),
            "dense_available": self.dense_available,
            "version": self.version,
        }

    @staticmethod
    def _rerank_text(c: Clause) -> str:
        return f"{c.doc_title}\n{c.heading or ''}\n{c.text}"

    # -- ranking ---------------------------------------------------------
    def _bm25_rank(self, query: str, cand: np.ndarray) -> list[int]:
        q = tokenise(query)
        if not q or self._bm25 is None or not len(cand):
            return []
        sc = self._bm25.get_scores(q)[cand]
        order = np.argsort(-sc, kind="stable")[:TOP_N]
        return [int(cand[i]) for i in order if sc[i] > 0]

    def _dense_rank(self, query: str, cand: np.ndarray) -> list[int]:
        if not self.dense_available or not len(cand):
            return []
        qv = embed([normalise_for_search(query)])[0]
        sc = self._dense[cand] @ qv
        order = np.argsort(-sc, kind="stable")[:TOP_N]
        return [int(cand[i]) for i in order]

    def default_mode(self) -> str:
        if self.dense_available and get_reranker() is not None:
            return "rerank"
        return "hybrid"

    def search(self, query: str, filters: Optional[RetrievalFilters] = None, k: int = 8,
               mode: str = "auto") -> list[EvidenceItem]:
        if mode == "auto":
            mode = self.default_mode()
        if mode not in ("rerank", "hybrid", "dense", "bm25"):
            raise ValueError(f"unknown mode {mode}")
        if mode == "rerank" and (not self.dense_available or get_reranker() is None):
            mode = "hybrid"
        cand = np.array([i for i, cid in enumerate(self.ids) if _passes(self.clauses[cid], filters)], dtype=int)
        bm = self._bm25_rank(query, cand) if mode in ("rerank", "hybrid", "bm25") else []
        de = self._dense_rank(query, cand) if mode in ("rerank", "hybrid", "dense") else []
        rb = {i: r for r, i in enumerate(bm, 1)}
        rd = {i: r for r, i in enumerate(de, 1)}
        scores: dict[int, float] = {}
        for ranks in (rb, rd):
            for i, r in ranks.items():
                scores[i] = scores.get(i, 0.0) + 1.0 / (RRF_K + r)
        fused = sorted(scores, key=lambda i: (-scores[i], min(rb.get(i, 10**9), rd.get(i, 10**9))))
        if mode == "rerank":
            pool = fused[:max(RERANK_POOL, k)]
            pairs = [(query, self._rerank_text(self.clauses[self.ids[i]])) for i in pool]
            ce = np.asarray(get_reranker().predict(pairs, batch_size=32, show_progress_bar=False), dtype=float)
            order = np.argsort(-ce, kind="stable")
            scores = {pool[j]: float(ce[j]) for j in range(len(pool))}
            top = [pool[j] for j in order[:k]]
        else:
            top = fused[:k]
        out = []
        for i in top:
            c = self.clauses[self.ids[i]]
            out.append(EvidenceItem(
                clause_id=c.clause_id, doc_id=c.doc_id, doc_title=c.doc_title, issuer=c.issuer,
                jurisdiction=c.jurisdiction, instrument_type=c.instrument_type, binding=c.binding,
                article=c.article, paragraph=c.paragraph, heading=c.heading, language=c.language,
                url=c.url, text=c.text, score=scores[i], rank_dense=rd.get(i), rank_bm25=rb.get(i)))
        return out
