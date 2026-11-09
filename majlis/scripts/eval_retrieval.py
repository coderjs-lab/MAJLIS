"""Retrieval eval: recall@5 and MRR@10 for dense/bm25/hybrid, exact and article level."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import argparse
import json
import re

from majlis.retrieval import KB


def article_key(cid: str) -> str:
    cid = re.sub(r"/(en|ar)$", "", cid)
    return re.sub(r"/para-[^/]*", "", cid)


def score(ranked: list[str], gold: set[str]) -> tuple[float, float]:
    r5 = 1.0 if any(c in gold for c in ranked[:5]) else 0.0
    mrr = next((1.0 / i for i, c in enumerate(ranked[:10], 1) if c in gold), 0.0)
    return r5, mrr


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kb-dir", default="kb")
    a = ap.parse_args(argv)
    kb_dir = Path(a.kb_dir)
    ev = kb_dir / "retrieval_eval.jsonl"
    if not ev.exists() or not (kb_dir / "clauses" / "clauses.jsonl").exists():
        print(f"[eval_retrieval] missing {ev} or clauses.jsonl; nothing to evaluate.")
        return 0
    rows = [json.loads(l) for l in ev.read_text(encoding="utf-8").splitlines() if l.strip()]
    rows = [r for r in rows if r.get("gold_clause_ids")]
    kb = KB.load(kb_dir)
    modes = ["dense", "bm25", "hybrid"] if kb.dense_available else ["bm25", "hybrid"]
    agg = {m: {"recall@5": 0.0, "mrr": 0.0, "recall@5_article": 0.0, "mrr_article": 0.0} for m in modes}
    per_q = []
    for r in rows:
        gold = set(r["gold_clause_ids"])
        gold_a = {article_key(g) for g in gold}
        pq = {"qid": r.get("qid"), "lang": r.get("lang"), "topic": r.get("topic"), "gold": sorted(gold)}
        for m in modes:
            ranked = [e.clause_id for e in kb.search(r["question"], k=10, mode=m)]
            r5, mrr = score(ranked, gold)
            r5a, mrra = score([article_key(c) for c in ranked], gold_a)
            for key, v in (("recall@5", r5), ("mrr", mrr), ("recall@5_article", r5a), ("mrr_article", mrra)):
                agg[m][key] += v
            pq[m] = {"top10": ranked, "recall@5": r5, "mrr": mrr, "recall@5_article": r5a, "mrr_article": mrra}
        per_q.append(pq)
    n = max(len(rows), 1)
    for m in modes:
        agg[m] = {k: round(v / n, 4) for k, v in agg[m].items()}
    res = {"n_questions": len(rows), "by_mode": agg, "per_question": per_q,
           "kb_version": kb.version, "dense_available": kb.dense_available}
    (kb_dir / "retrieval_eval_results.json").write_text(json.dumps(res, indent=2, ensure_ascii=False))
    print(f"n_questions={len(rows)} dense_available={kb.dense_available}\n")
    print("| mode | recall@5 | MRR@10 | recall@5 (article) | MRR@10 (article) |")
    print("|---|---|---|---|---|")
    for m in modes:
        s = agg[m]
        print(f"| {m} | {s['recall@5']:.3f} | {s['mrr']:.3f} | {s['recall@5_article']:.3f} | {s['mrr_article']:.3f} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
