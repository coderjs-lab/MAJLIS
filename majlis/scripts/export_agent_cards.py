"""Export agent cards (JSON) from the agent YAMLs into agent_cards/<id>.json.

Fictional training exercise. Agents simulate institutions; this is not an
official position of any real institution.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from majlis.prompts import SIM_DISCLAIMER  # noqa: E402
from majlis.schemas import AgentConfig  # noqa: E402

GOVERNANCE = {"application": "P/LA/HA/AE", "institution": "P/LA/HA/AE", "adviser": "P/LA/HA/AE"}


def card(raw: dict) -> dict:
    cfg = AgentConfig.model_validate(raw)
    return {
        "id": cfg.id,
        "name": cfg.display_name,
        "name_ar": cfg.display_name_ar,
        "short_name": cfg.short_name,
        "kind": cfg.kind,
        "jurisdiction": cfg.jurisdiction,
        "mandate": cfg.mandate.strip(),
        "mandate_verified": bool(cfg.mandate_sources),
        "mandate_sources": cfg.mandate_sources,
        "knowledge": {"retrieval_filters": cfg.retrieval_filters.model_dump(exclude_none=True),
                      "retrieval_k": cfg.retrieval_k, "source": "kb/clauses/clauses.jsonl"},
        "tools": cfg.action_vocabulary,
        "can_message": cfg.can_message,
        "output_languages": ["en", "ar"],
        "default_output_language": cfg.output_language,
        "output_schema": "AdviceAnswer" if cfg.kind == "adviser" else "AgentTurn",
        "limitations": raw.get("limitations") or [],
        "disclaimer": SIM_DISCLAIMER,
        "framework_mapping": {"y3172_node": "M", "governance": GOVERNANCE.get(cfg.kind, "P/LA/HA/AE")},
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agents-dir", default=str(ROOT / "configs" / "agents"))
    ap.add_argument("--out", default=str(ROOT / "agent_cards"))
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for p in sorted(Path(a.agents_dir).glob("*.yaml")):
        c = card(yaml.safe_load(p.read_text(encoding="utf-8")) or {})
        (out / f"{c['id']}.json").write_text(json.dumps(c, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {out / (c['id'] + '.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
