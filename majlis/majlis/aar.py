"""After-Action Report (Markdown) rendered from ledger entries only.

Deterministic: the same ledger gives the same report. Nothing is written that
is not in the ledger; no LLM is called.
"""
from __future__ import annotations

from collections import defaultdict

from majlis import metrics as metrics_mod
from majlis.ledger import verify_chain

DEFAULT_DISCLAIMER = ("Simulated exercise. The scenario, the provider and all telemetry are fictional; "
                      "institutional agents are simulations and do not speak for any real body.")


def _cell(value, limit: int | None = None) -> str:
    """Make a value safe for a Markdown table cell."""
    if value is None or value == "" or value == []:
        return "-"
    if isinstance(value, (list, tuple)):
        value = ", ".join(str(v) for v in value)
    text = " ".join(str(value).split()).replace("|", "\\|")
    if limit and len(text) > limit:
        text = text[: limit].rstrip() + " …"
    return text


def _words(text: str | None, n: int) -> str:
    """First n words, marked with an ellipsis if shortened."""
    w = (text or "").split()
    return " ".join(w[:n]) + (" …" if len(w) > n else "")


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return out


def render_aar(entries: list[dict]) -> str:
    by_type: dict[str, list[dict]] = defaultdict(list)
    for e in entries:
        by_type[e.get("event_type")].append(e)

    start = (by_type["run_start"] or [{}])[0].get("payload", {})
    run_id = entries[0].get("run_id") if entries else "-"
    ok, n, broken = verify_chain(entries)
    head = entries[-1]["hash"][:12] if entries and ok else "-"
    chain = f"verified, {n} entries, head `{head}`" if ok else f"BROKEN at seq {broken} ({n} entries)"
    run_end = (by_type["run_end"] or [{}])[-1].get("payload", {})

    L: list[str] = []
    L.append(f"# After-Action Report: {start.get('title') or start.get('scenario_id') or 'MAJLIS run'}")
    L.append("")
    L.append(f"> {start.get('disclaimer') or DEFAULT_DISCLAIMER}")
    L.append("")
    L += _table(["Field", "Value"], [
        ["Scenario", _cell(start.get("scenario_id"))],
        ["Run id", _cell(run_id)],
        ["Mode", _cell(start.get("mode"))],
        ["Approver", _cell(start.get("approver"))],
        ["Model / backend", f"{_cell(start.get('model'))} / {_cell(start.get('backend'))}"],
        ["KB version", _cell((start.get("kb_version") or "")[:16] or None)],
        ["Language", _cell(start.get("lang"))],
        ["Ledger chain", chain],
        ["Run status", _cell(run_end.get("status"))],
    ])
    L.append("")

    # ---- per-stage --------------------------------------------------------
    status_idx = metrics_mod.citation_index(entries)
    stages = start.get("stages") or []
    injects = {e["payload"].get("stage_id"): e["payload"] for e in by_type["inject"]}
    stage_ends = {e["payload"].get("stage_id"): e["payload"] for e in by_type["stage_end"]}
    stage_ids = [s.get("id") for s in stages] or list(injects)
    verified_by_stage: dict[str, list[str]] = defaultdict(list)
    for e in by_type["agent_turn"]:
        p = e["payload"]
        for c in (p.get("turn") or {}).get("claims") or []:
            if status_idx.get((p.get("agent_id"), p.get("round"), c.get("claim_id"))) == "VERIFIED":
                label = f"{p.get('agent_id')}: {c.get('clause_id')}"
                if label not in verified_by_stage[e.get("stage")]:
                    verified_by_stage[e.get("stage")].append(label)
    gate_by_stage: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for e in by_type["gate_decision"]:
        p = e["payload"]
        gate_by_stage[e.get("stage")][p.get("decision")].append(p.get("action_type"))

    L.append("## Stages")
    L.append("")
    rows = []
    for sid in stage_ids:
        meta = next((s for s in stages if s.get("id") == sid), {})
        inj = injects.get(sid, {})
        g = gate_by_stage.get(sid, {})
        end = stage_ends.get(sid, {})
        happened = (f"allowed: {_cell(g.get('ALLOW'))}; blocked: {_cell(g.get('DENY'))}; "
                    f"escalated: {_cell(g.get('ESCALATE'))}")
        if end.get("open_requests"):
            happened += f"; open requests: {_cell(end.get('open_requests'))}"
        rows.append([
            _cell(sid),
            _cell(f"{inj.get('sim_time') or meta.get('sim_time') or ''} {inj.get('title') or meta.get('title') or ''}".strip()
                  + (": " + _words(inj.get("text"), 30) if inj.get("text") else ""), 260),
            _cell(inj.get("recipients") or meta.get("recipients")),
            _cell(inj.get("expected") or meta.get("expected"), 200),
            happened,
            _cell(verified_by_stage.get(sid)),
        ])
    L += _table(["Stage", "Inject", "Recipients", "Expected", "What happened", "Verified claims (clause ids)"], rows)
    L.append("")

    # ---- gate decisions ---------------------------------------------------
    human = {e["payload"].get("action_id"): e["payload"] for e in by_type["human_decision"]}
    L.append("## Gate decisions")
    L.append("")
    if by_type["gate_decision"]:
        rows = []
        for e in by_type["gate_decision"]:
            p = e["payload"]
            h = human.get(p.get("action_id"))
            rows.append([
                str(e["seq"]), _cell(e.get("stage")), _cell(p.get("agent_id")), _cell(p.get("action_type")),
                f"{p.get('decision')} {p.get('status_code')}" + ("" if p.get("enforced", True) else " (not enforced)"),
                _cell(p.get("reason")), _cell(p.get("rule_ids")), _cell(p.get("events")),
                _cell(f"{p.get('clause_id')} ({p.get('issuer')}): \"{_words(p.get('quote'), 20)}\"" if p.get("clause_id") else None),
                _cell(f"{h.get('decision')} by {h.get('approver')}" if h else None),
            ])
        L += _table(["Seq", "Stage", "Agent", "Action", "Decision", "Step", "Rules", "Events",
                     "Cited clause", "Human"], rows)
    else:
        L.append("No gate decisions recorded.")
    L.append("")

    # ---- citation integrity -----------------------------------------------
    L.append("## Citation integrity")
    L.append("")
    m = (by_type["metrics"] or [{}])[-1].get("payload") or metrics_mod.compute(entries)
    per_agent: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for e in by_type["citation_check"]:
        p = e["payload"]
        for r in p.get("results") or []:
            per_agent[p.get("agent_id")][r.get("status")] += 1
    statuses = ["VERIFIED", "NEAR_MATCH", "FAILED", "NOT_RETRIEVED", "UNKNOWN_CLAUSE", "UNSUPPORTED", "NO_CITATION"]
    rows = [[_cell(a)] + [str(counts.get(s, 0)) for s in statuses] for a, counts in sorted(per_agent.items())]
    rows.append(["**all**"] + [str(m["citations"].get(s, 0)) for s in statuses])
    L += _table(["Agent"] + statuses, rows)
    L.append("")
    L.append(f"Verification rate (cited claims): {m['citations'].get('verification_rate', 0.0)}. "
             "Only VERIFIED claims count as a legal basis.")
    L.append("")

    # ---- gaps -------------------------------------------------------------
    L.append("## Gap candidates")
    L.append("")
    if by_type["gap_candidate"]:
        rows = []
        for e in by_type["gap_candidate"]:
            p = e["payload"]
            ex = p.get("global_examples") or []
            example = "; ".join(f"{x.get('jurisdiction')}: {x.get('instrument')}"
                                + (f" ({x.get('clause_id')})" if x.get("clause_id") else "") for x in ex)
            rows.append([
                _cell(p.get("gap_id")), _cell(p.get("pattern")), _cell(p.get("title"), 120),
                _cell((p.get("evidence") or {}).get("ledger_seqs")),
                _cell(p.get("readiness_dimensions")),
                _cell(example) if example else "INSUFFICIENT EVIDENCE",
            ])
        L += _table(["Gap", "Pattern", "Title", "Evidence seqs", "Readiness dims", "Global example"], rows)
        L.append("")
        for e in by_type["gap_candidate"]:
            p = e["payload"]
            L.append(f"- **{p.get('gap_id')}**: {_cell(p.get('description'))}")
    else:
        L.append("No gap candidates recorded.")
    L.append("")

    # ---- metrics ----------------------------------------------------------
    gt, hu, ll = m["gate"], m["human"], m["llm"]
    L.append("## Metrics")
    L.append("")
    L.append(f"- Gate: {gt['allow']} allowed, {gt['deny']} denied, {gt['escalate']} escalated; "
             f"out of vocabulary {gt['out_of_vocabulary']}; would-deny let through {gt['would_deny_let_through']}; "
             f"would-escalate let through {gt['would_escalate_let_through']}")
    L.append(f"- Human decisions: {hu['approved']} approved, {hu['rejected']} rejected")
    L.append(f"- Unsupported claims passed as fact (basis of an executed action): {m['unsupported_passed_as_fact']}")
    L.append(f"- Gaps: {m['gaps']['total']} total {dict(sorted(m['gaps']['by_pattern'].items()))}; "
             f"with global example {m['gaps']['with_global_example']}; "
             f"insufficient evidence {m['gaps']['insufficient_evidence']}")
    L.append(f"- LLM: {ll['calls']} calls, {ll['errors']} errors, {ll['prompt_tokens']} prompt / "
             f"{ll['completion_tokens']} completion tokens, {ll['latency_ms_total']} ms total")
    if m.get("duties_first_identified"):
        L.append("- Duties first claimed: " + ", ".join(
            f"`{d}` at {s}" for d, s in m["duties_first_identified"].items()))
    L.append("")

    L.append("## Limitations")
    L.append("")
    L.append("Simulated exercise with fictional scenario, provider and telemetry; agents are LLM simulations, "
             "so outputs vary between runs. Gap candidates are leads for human review, not findings.")
    L.append("")
    return "\n".join(L)
