"""Embed every clause's search field with bge-m3 -> kb/index/{dense.npy,ids.json,meta.json}."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import argparse
import json
import time
from datetime import datetime, timezone

import numpy as np


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kb-dir", default="kb")
    ap.add_argument("--batch-size", type=int, default=32)
    a = ap.parse_args(argv)
    kb_dir = Path(a.kb_dir)
    if not (kb_dir / "clauses" / "clauses.jsonl").exists():
        print(f"[build_index] {kb_dir}/clauses/clauses.jsonl not found; build the KB first. Skipping.")
        return 0
    from majlis.retrieval import KB, MODEL_NAME, embed, search_field
    t0 = time.time()
    kb = KB.load(kb_dir)
    ids = list(kb.clauses)
    texts = [search_field(kb.clauses[c]) for c in ids]
    t1 = time.time()
    vecs = embed(texts, batch_size=a.batch_size)
    t2 = time.time()
    out = kb_dir / "index"
    out.mkdir(parents=True, exist_ok=True)
    np.save(out / "dense.npy", vecs.astype(np.float32))
    (out / "ids.json").write_text(json.dumps(ids, ensure_ascii=False))
    (out / "meta.json").write_text(json.dumps({
        "model": MODEL_NAME, "dim": int(vecs.shape[1]), "n": len(ids), "kb_version": kb.version,
        "created_at": datetime.now(timezone.utc).isoformat()}, indent=2))
    print(f"[build_index] {len(ids)} clauses, dim {vecs.shape[1]}, embed {t2 - t1:.1f}s, total {time.time() - t0:.1f}s -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
