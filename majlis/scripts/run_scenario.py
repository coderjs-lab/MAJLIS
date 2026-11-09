"""Run a MAJLIS scenario from the command line.

Fictional training exercise. Agents simulate institutions; this is not an
official position of any real institution.

Example (offline):
  MAJLIS_BACKEND=mock .venv/bin/python scripts/run_scenario.py --scenario s1_failover \
      --mode governed --approver reject_all --kb-dir tests/fixtures/kb --rules tests/fixtures/rules_test.yaml
Judge inject:
  ... --inject "free text" --recipients doh,data_office --state key=value --after T3
Challenge card:
  ... --card C2 --after T3
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _value(v: str):
    low = v.lower()
    if low in ("true", "false"):
        return low == "true"
    if low in ("null", "none"):
        return None
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        return v


def _line(e) -> str:
    p, et = e.payload, e.event_type
    st = (e.stage or "--").ljust(4)
    head = f"{e.seq:>4} {st} {et:<15} {e.actor:<13}"
    if et == "run_start":
        return f"{head} {p.get('scenario_id')} mode={p.get('mode')} approver={p.get('approver')} " \
               f"lang={p.get('lang')} backend={p.get('backend')} model={p.get('model')}"
    if et == "inject":
        return f"{head} {p.get('sim_time')} -> {','.join(p.get('recipients') or [])} " \
               f"changes={json.dumps(p.get('state_changes'), ensure_ascii=False)}"
    if et == "retrieval":
        return f"{head} {len(p.get('results') or [])} clauses"
    if et == "llm_call":
        return f"{head} {p.get('purpose')} {p.get('backend')} {p.get('latency_ms')}ms attempts={p.get('attempts')}" + \
               (f" ERROR {str(p.get('error'))[:80]}" if p.get("error") else "")
    if et == "agent_turn":
        t = p.get("turn") or {}
        acts = ",".join(a.get("action_type", "?") for a in t.get("proposed_actions") or []) or "-"
        return f"{head} r{p.get('round')} claims={len(t.get('claims') or [])} actions={acts} " \
               f"requests={len(t.get('requests') or [])}"
    if et == "citation_check":
        return f"{head} {p.get('agent_id')} r{p.get('round')} {p.get('counts')}"
    if et == "gate_decision":
        enf = "" if p.get("enforced") else " (NOT ENFORCED)"
        return f"{head} {p.get('action_type')} -> {p.get('decision')} {p.get('status_code')}{enf} " \
               f"{','.join(p.get('rule_ids') or []) or ','.join(p.get('events') or [])}"
    if et == "human_decision":
        return f"{head} {p.get('action_id')} -> {p.get('decision')} by {p.get('approver')}"
    if et == "message":
        return f"{head} {p.get('msg_type')} {p.get('from')} -> {','.join(p.get('to') or [])}"
    if et == "stage_end":
        return f"{head} allowed={len(p.get('allowed') or [])} blocked={len(p.get('blocked') or [])} " \
               f"escalated={len(p.get('escalated') or [])} open={len(p.get('open_requests') or [])}"
    if et == "gap_candidate":
        return f"{head} {p.get('gap_id')} {p.get('pattern')} {str(p.get('title'))[:70]}"
    if et == "agent_error":
        return f"{head} {str(p.get('error'))[:100]}"
    if et == "metrics":
        c = p.get("citations") or {}
        return f"{head} verification_rate={c.get('verification_rate')} gate={p.get('gate')}"
    if et == "run_end":
        return f"{head} {p.get('status')} in {p.get('duration_s')}s"
    return head


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run a MAJLIS scenario (fictional exercise).")
    ap.add_argument("--scenario", default="s1_failover", help="scenario id or yaml path")
    ap.add_argument("--mode", choices=["governed", "ungoverned"], default="governed")
    ap.add_argument("--approver", choices=["reject_all", "approve_all", "interactive"], default="reject_all")
    ap.add_argument("--lang", choices=["en", "ar"], default="en")
    ap.add_argument("--pack", default="uae")
    ap.add_argument("--backend", choices=["mock", "glm"], help="overrides MAJLIS_BACKEND")
    ap.add_argument("--model", help="overrides MAJLIS_MODEL")
    ap.add_argument("--effort", choices=["low", "medium", "high", "max"], help="overrides MAJLIS_EFFORT")
    ap.add_argument("--inject", help="free-text judge inject added as an extra stage")
    ap.add_argument("--recipients", help="comma-separated agent ids for --inject")
    ap.add_argument("--state", action="append", default=[], metavar="KEY=VALUE",
                    help="state change for the extra stage (repeatable)")
    ap.add_argument("--card", action="append", default=[], help="challenge card id (repeatable), e.g. C2")
    ap.add_argument("--after", help="insert extra stages after this stage id (default: append at the end)")
    ap.add_argument("--kb-dir", help="KB directory (default from the country pack)")
    ap.add_argument("--rules", help="policy rules yaml (default from the country pack)")
    ap.add_argument("--runs-dir", default="runs")
    ap.add_argument("--run-id")
    ap.add_argument("--approval-timeout", type=float, help="seconds (interactive approver)")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    if a.backend:
        os.environ["MAJLIS_BACKEND"] = a.backend
    if a.model:
        os.environ["MAJLIS_MODEL"] = a.model
    if a.effort:
        os.environ["MAJLIS_EFFORT"] = a.effort

    from majlis.engine import load_challenge_cards, run_scenario
    from majlis.schemas import Stage

    extra: list[Stage] = []
    cards = load_challenge_cards() if a.card else {}
    for cid in a.card:
        if cid not in cards:
            ap.error(f"unknown challenge card {cid}; known: {', '.join(cards)}")
        extra.append(cards[cid])
    if a.inject:
        if not a.recipients:
            ap.error("--inject needs --recipients")
        changes = {}
        for kv in a.state:
            if "=" not in kv:
                ap.error(f"--state expects key=value, got {kv!r}")
            k, v = kv.split("=", 1)
            changes[k.strip()] = _value(v.strip())
        n = sum(1 for s in extra if s.id.startswith("J")) + 1
        extra.append(Stage(id=f"J{n}", sim_time="live", title="Judge inject",
                           recipients=[r.strip() for r in a.recipients.split(",") if r.strip()],
                           inject_en=a.inject, state_changes=changes,
                           expected="Live judge inject: no expected outcome written in advance."))

    hook = None if a.quiet else (lambda e: print(_line(e), flush=True))
    run_dir = run_scenario(Path(a.scenario), mode=a.mode, approver=a.approver, lang=a.lang, pack=a.pack,
                           extra_stages=extra or None, extra_after=a.after, runs_dir=Path(a.runs_dir),
                           run_id=a.run_id, kb_dir=Path(a.kb_dir) if a.kb_dir else None,
                           rules_path=Path(a.rules) if a.rules else None, on_event=hook,
                           approval_timeout=a.approval_timeout)
    print(f"RUN DIR: {run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
