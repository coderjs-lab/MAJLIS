"""Prints the report's evaluation tables (Markdown) computed from committed run ledgers only.

Usage: .venv/bin/python scripts/report_tables.py runs/<id> [runs/<id> ...]
Every number in the technical report's evaluation section comes from this script (no hand edits).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from majlis.ledger import load_entries, verify_chain  # noqa: E402
from majlis.metrics import compute  # noqa: E402


def label(entries: list[dict]) -> str:
    rs = next(e for e in entries if e["event_type"] == "run_start")["payload"]
    import re
    extra = [e["payload"]["stage_id"] for e in entries if e["event_type"] == "inject"
             and not re.fullmatch(r"T\d+", e["payload"]["stage_id"])]
    appr = rs.get("approver", "")
    tail = (f" · +{','.join(extra)}" if extra else "") + (" · approve_all" if appr == "approve_all" else "")
    return f"{rs['mode']} · {rs['lang'].upper()}" + tail


def metrics_table(runs: list[tuple[str, list[dict]]]) -> str:
    rows = [
        ("Ledger entries (hash chain)", lambda E, m: f"{len(E)} ({'OK' if verify_chain(E)[0] else 'BROKEN'})"),
        ("LLM calls / errors", lambda E, m: f"{m['llm']['calls']} / {m['llm']['errors']}"),
        ("Citation verification rate", lambda E, m: f"{m['citations']['verification_rate']:.1%}"),
        ("Gate: ALLOW / DENY 403 / ESCALATE", lambda E, m: f"{m['gate']['allow']} / {m['gate']['deny']} / {m['gate']['escalate']}"),
        ("Violations let through (would DENY, executed)", lambda E, m: str(m['gate']['would_deny_let_through'])),
        ("Escalations bypassed (would ESCALATE, executed)", lambda E, m: str(m['gate']['would_escalate_let_through'])),
        ("Human decisions: approved / rejected", lambda E, m: f"{m['human']['approved']} / {m['human']['rejected']}"),
        ("Conflicts recorded (G2)", lambda E, m: str(sum('conflict' in (e['payload'].get('events') or [])
                                                         for e in E if e['event_type'] == 'gate_decision'))),
        ("Unsupported legal claims acted on", lambda E, m: str(m['unsupported_passed_as_fact'])),
        ("Gap candidates G1/G2/G3/G4/G5", lambda E, m: "/".join(str(m['gaps']['by_pattern'].get(p, 0)) for p in
                                                                ("G1_POLICY_VOID", "G2_CONFLICT", "G3_RESPONSIBILITY",
                                                                 "G4_CLOCK", "G5_STANDARDS"))),
        ("Gaps with a verified global example", lambda E, m: f"{m['gaps']['with_global_example']} of {m['gaps']['total']}"),
    ]
    head = "| Metric | " + " | ".join(label(E) for _, E in runs) + " |"
    sep = "|---|" + "---|" * len(runs)
    ms = [(E, compute(E)) for _, E in runs]
    body = ["| " + name + " | " + " | ".join(f(E, m) for E, m in ms) + " |" for name, f in rows]
    return "\n".join([head, sep, *body])


def citation_table(runs: list[tuple[str, list[dict]]]) -> str:
    st = ["VERIFIED", "NEAR_MATCH", "FAILED", "NOT_RETRIEVED", "UNKNOWN_CLAUSE", "UNSUPPORTED", "NO_CITATION"]
    head = "| Run | " + " | ".join(st) + " |"
    sep = "|---|" + "---|" * len(st)
    body = []
    for _, E in runs:
        c = compute(E)["citations"]
        body.append(f"| {label(E)} | " + " | ".join(str(c.get(s, 0)) for s in st) + " |")
    return "\n".join([head, sep, *body])


def stage_table(E: list[dict]) -> str:
    """Expected (written before the run) vs what the ledger shows, per stage."""
    out = ["| Stage | Expected (pre-written) | Actual (from ledger) |", "|---|---|---|"]
    for inj in [e for e in E if e["event_type"] == "inject"]:
        sid = inj["payload"]["stage_id"]
        gates = [e["payload"] for e in E if e["event_type"] == "gate_decision" and e["stage"] == sid
                 and e["payload"]["agent_id"] == "triage"]
        humans = {e["payload"]["action_id"]: e["payload"]["decision"] for e in E
                  if e["event_type"] == "human_decision" and e["stage"] == sid}
        acts = []
        for g in gates:
            tag = f"{g['action_type']} → {g['decision']} {g['status_code']}"
            if not g["enforced"] and g["decision"] != "ALLOW":
                tag += " (not enforced)"
            if g["action_id"] in humans:
                tag += f", human {humans[g['action_id']]}"
            if g["decision"] != "ALLOW" or "conflict" in g["events"]:
                acts.append(tag + (f" [{', '.join(g['rule_ids'] or g['events'])}]"))
        short = {"doh": "DoH", "tdra": "TDRA", "data_office": "Data Office"}
        per: dict[str, list[str]] = {}
        for e in E:
            p = e["payload"]
            if (e["event_type"] == "agent_turn" and e["stage"] == sid and p.get("round") == 1
                    and p["agent_id"] in short):
                for a in p["turn"]["proposed_actions"]:
                    per.setdefault(short[p["agent_id"]], [])
                    if a["action_type"] not in per[short[p["agent_id"]]]:
                        per[short[p["agent_id"]]].append(a["action_type"])
        for who, lst in per.items():
            acts.append(f"{who}: {', '.join(lst)}")
        exp = (inj["payload"].get("expected") or "").replace("\n", " ")
        out.append(f"| {sid} | {exp} | {'; '.join(acts) or 'no gate-relevant actions'} |")
    return "\n".join(out)


def main() -> None:
    paths = [Path(p) for p in sys.argv[1:]]
    runs = [(p.name, load_entries(p / "ledger.jsonl")) for p in paths]
    print("## Governed vs ungoverned and other runs\n")
    print(metrics_table(runs), "\n")
    print("## Citation integrity (E3)\n")
    print(citation_table(runs), "\n")
    for name, E in runs:
        print(f"## Expected vs actual: {name} ({label(E)})\n")
        print(stage_table(E), "\n")


if __name__ == "__main__":
    main()
