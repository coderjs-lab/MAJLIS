"""Hybrid (BM25 + bge-m3 dense) retrieval over the clause-level KB. See CONTRACTS.md."""
from __future__ import annotations

import hashlib
import json
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
RRF_K = 60
TOP_N = 50

_HARAKAT = re.compile(r"[ً-ْٰ]")
_ALEF = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه", "ـ": None})
_WS = re.compile(r"\s+")


def normalise_for_search(text: str) -> str:
    s = unicodedata.normalize("NFKC", text or "").casefold()
    s = _HARAKAT.sub("", s).translate(_ALEF)
    return _WS.sub(" ", s).strip()


def tokenise(text: str) -> list[str]:
    return [t for t in re.findall(r"\w+", normalise_for_search(text)) if len(t) > 1 or t.isdigit()]


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

    def search(self, query: str, filters: Optional[RetrievalFilters] = None, k: int = 8,
               mode: str = "hybrid") -> list[EvidenceItem]:
        if mode not in ("hybrid", "dense", "bm25"):
            raise ValueError(f"unknown mode {mode}")
        cand = np.array([i for i, cid in enumerate(self.ids) if _passes(self.clauses[cid], filters)], dtype=int)
        bm = self._bm25_rank(query, cand) if mode in ("hybrid", "bm25") else []
        de = self._dense_rank(query, cand) if mode in ("hybrid", "dense") else []
        rb = {i: r for r, i in enumerate(bm, 1)}
        rd = {i: r for r, i in enumerate(de, 1)}
        scores: dict[int, float] = {}
        for ranks in (rb, rd):
            for i, r in ranks.items():
                scores[i] = scores.get(i, 0.0) + 1.0 / (RRF_K + r)
        top = sorted(scores, key=lambda i: (-scores[i], min(rb.get(i, 10**9), rd.get(i, 10**9))))[:k]
        out = []
        for i in top:
            c = self.clauses[self.ids[i]]
            out.append(EvidenceItem(
                clause_id=c.clause_id, doc_id=c.doc_id, doc_title=c.doc_title, issuer=c.issuer,
                jurisdiction=c.jurisdiction, instrument_type=c.instrument_type, binding=c.binding,
                article=c.article, paragraph=c.paragraph, heading=c.heading, language=c.language,
                url=c.url, text=c.text, score=scores[i], rank_dense=rd.get(i), rank_bm25=rb.get(i)))
        return out
