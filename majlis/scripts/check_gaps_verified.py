"""Checks every quote in configs/gaps_verified.yaml is verbatim in the cited clause (Tier 2 integrity)."""
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from majlis.citation_check import normalise_quote  # noqa: E402
from majlis.retrieval import KB  # noqa: E402


def main() -> int:
    kb = KB.load(ROOT / "kb")
    data = yaml.safe_load((ROOT / "configs" / "gaps_verified.yaml").read_text(encoding="utf-8"))
    bad = 0
    for g in data["gaps"]:
        cites = list(g.get("uae_evidence") or []) + list(g.get("standard_evidence") or [])
        if g.get("global_example") and g["global_example"].get("clause_id"):
            cites.append(g["global_example"])
        for c in cites:
            clause = kb.get(c["clause_id"])
            ok = clause is not None and normalise_quote(c["quote"]) in normalise_quote(clause.text)
            bad += not ok
            print(f"{'OK  ' if ok else 'FAIL'} {g['id']:4s} {c['clause_id']}")
    print(f"{'all quotes verbatim' if not bad else f'{bad} quote(s) not found'}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
