"""Writes every number and data-driven figure of the LaTeX report from committed artefacts.

Outputs into report/latex/generated/:
  numbers.tex       \\newcommand macros (one per number used in the text)
  fig_timeline.tex  TikZ: who received which inject, and what the gate did at each stage, per run
  fig_outcomes.tex  pgfplots: governance outcomes per run
  fig_citations.tex pgfplots: citation integrity per run
  tab_kb.tex        the knowledge-base composition table (from kb/clauses/clauses.jsonl)

Usage (from ITUAIReadiness/majlis):
  .venv/bin/python report/make_data.py --gov runs/<id> --ungov runs/<id> --ar runs/<id> --cards runs/<id>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
OUT = HERE / "generated"
MAJLIS = HERE.parent  # report/ lives inside the majlis project
sys.path.insert(0, str(MAJLIS))
from majlis.ledger import load_entries, verify_chain  # noqa: E402
from majlis.metrics import compute  # noqa: E402

AGENTS = [("triage", "AI triage"), ("doh", "DoH"), ("tdra", "TDRA"), ("data_office", "Data Office"),
          ("legal_adviser", "Legal Adviser")]


def facts(path: Path) -> dict:
    E = load_entries(path / "ledger.jsonl")
    m = compute(E)
    gates = [e for e in E if e["event_type"] == "gate_decision" and e["payload"]["agent_id"] == "triage"]
    humans = {e["payload"]["action_id"]: e["payload"]["decision"] for e in E if e["event_type"] == "human_decision"}
    blocked = sum(1 for e in gates if e["payload"]["decision"] == "DENY" and e["payload"]["enforced"])
    to_human = sum(1 for e in E if e["event_type"] == "human_decision")
    end = next(e for e in E if e["event_type"] == "run_end")["payload"]
    stages = {}
    for e in gates:
        p = e["payload"]
        rank = {"DENY": 3, "ESCALATE": 2, "ALLOW": 1}[p["decision"]]
        cur = stages.get(e["stage"])
        if cur is None or rank > cur["rank"]:
            stages[e["stage"]] = {"rank": rank, "decision": p["decision"], "enforced": p["enforced"],
                                  "action": p["action_type"], "human": humans.get(p["action_id"])}
    return {"E": E, "m": m, "n": len(E), "chain": verify_chain(E)[0], "blocked": blocked, "to_human": to_human,
            "stages": stages, "duration": end.get("duration_s", 0)}


def checked(m: dict) -> int:
    c = m["citations"]
    return sum(v for k, v in c.items() if k not in ("NO_CITATION", "verification_rate"))


def macro(name: str, value) -> str:
    return f"\\newcommand{{\\{name}}}{{{value}}}"


def numbers(R: dict, kb: dict, ev: dict, gaps: list, rules: list) -> str:
    out = []
    for key, tag in (("gov", "Gov"), ("ungov", "Ungov"), ("ar", "Ar"), ("cards", "Cards")):
        r, m = R[key], R[key]["m"]
        out += [
            macro(f"{tag}Entries", f"{r['n']:,}"), macro(f"{tag}Calls", m["llm"]["calls"]),
            macro(f"{tag}Errors", m["llm"]["errors"]),
            macro(f"{tag}Verif", f"{m['citations']['verification_rate'] * 100:.1f}"),
            macro(f"{tag}Verified", m["citations"]["VERIFIED"]), macro(f"{tag}Checked", checked(m)),
            macro(f"{tag}Unknown", m["citations"]["UNKNOWN_CLAUSE"]),
            macro(f"{tag}LetThrough", m["gate"]["would_deny_let_through"]),
            macro(f"{tag}Bypassed", m["gate"]["would_escalate_let_through"]),
            macro(f"{tag}Blocked", r["blocked"]), macro(f"{tag}ToHuman", r["to_human"]),
            macro(f"{tag}Approved", m["human"]["approved"]), macro(f"{tag}Rejected", m["human"]["rejected"]),
            macro(f"{tag}Gaps", m["gaps"]["total"]), macro(f"{tag}GapsGlobal", m["gaps"]["with_global_example"]),
            macro(f"{tag}GOne", m["gaps"]["by_pattern"].get("G1_POLICY_VOID", 0)),
            macro(f"{tag}GThree", m["gaps"]["by_pattern"].get("G3_RESPONSIBILITY", 0)),
            macro(f"{tag}GFive", m["gaps"]["by_pattern"].get("G5_STANDARDS", 0)),
            macro(f"{tag}PromptK", f"{m['llm']['prompt_tokens'] / 1000:.0f}"),
            macro(f"{tag}Minutes", f"{r['duration'] / 60:.0f}"),
        ]
    rates = [R[k]["m"]["citations"]["verification_rate"] * 100 for k in R]
    out += [macro("VerifMin", f"{min(rates):.1f}"), macro("VerifMax", f"{max(rates):.1f}")]
    by_status = {s: sum(1 for g in gaps if g["status"] == s) for s in ("verified", "rejected", "needs_more_evidence")}
    hy, de, bm = (ev["by_mode"][k] for k in ("hybrid", "dense", "bm25"))
    rr = ev["by_mode"]["rerank"]
    lang = ev["recall@5_by_language"]
    out += [
        macro("RecallRerank", f"{rr['recall@5']:.2f}"), macro("MRRRerank", f"{rr['mrr']:.2f}"),
        macro("MRRDense", f"{de['mrr']:.2f}"), macro("MRRHybrid", f"{hy['mrr']:.2f}"),
        macro("RecallRerankArt", f"{rr['recall@5_article']:.2f}"),
        macro("PoolRecall", f"{ev['pool_recall@30_hybrid']:.2f}"),
        macro("RecallRerankEn", f"{lang['en']['rerank']:.2f}"), macro("RecallRerankAr", f"{lang['ar']['rerank']:.2f}"),
        macro("EvalNAr", lang["ar"]["n"]),
    ]
    # how often the agents cited (and quoted exactly) the DoH disaster-recovery clause that closed TV1
    dr = "AE-DOH-RAI-2025/sec-3.1.4.5.1/en"
    for key, tag in (("gov", "Gov"), ("ungov", "Ungov"), ("ar", "Ar"), ("cards", "Cards")):
        res = [x for e in R[key]["E"] if e["event_type"] == "citation_check" for x in e["payload"]["results"]]
        out.append(macro(f"{tag}DRCites", sum(1 for x in res if x["clause_id"] == dr and x["status"] == "VERIFIED")))
    out += [
        macro("KBDocs", kb["documents_with_clauses"]), macro("KBClauses", f"{kb['clauses_total']:,}"),
        macro("EvalN", ev["n_questions"]),
        macro("RecallHybrid", f"{hy['recall@5']:.2f}"), macro("RecallDense", f"{de['recall@5']:.2f}"),
        macro("RecallBM", f"{bm['recall@5']:.2f}"),
        macro("RecallHybridArt", f"{hy['recall@5_article']:.2f}"), macro("RecallDenseArt", f"{de['recall@5_article']:.2f}"),
        macro("NRules", len(rules)), macro("NGapsTwo", len(gaps)),
        macro("NGapsVerified", by_status["verified"]), macro("NGapsRejected", by_status["rejected"]),
        macro("NGapsPending", by_status["needs_more_evidence"]),
    ]
    return "\n".join(out) + "\n"


KB_GROUPS = [  # (label, jurisdictions)
    ("UAE federal laws and strategies", {"AE"}),
    ("Abu Dhabi DoH standards", {"AE-AZ"}),
    ("Dubai DHA AI policy", {"AE-DU"}),
    ("EU AI Act, GDPR, NIS2", {"EU"}),
    ("ITU and WHO", {"INTL"}),
    ("US, Singapore, Saudi", {"US", "SG", "SA"}),
]


def kb_table() -> tuple[str, list[str]]:
    rows = [json.loads(l) for l in (MAJLIS / "kb/clauses/clauses.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    lines = ["\\begin{tabularx}{\\columnwidth}{@{}Lrrr@{}}", "\\toprule",
             "\\textbf{Source} & \\textbf{Docs} & \\textbf{Clauses} & \\textbf{Binding}\\\\", "\\midrule"]
    macros = []
    for label, jur in KB_GROUPS:
        sel = [r for r in rows if r["jurisdiction"] in jur]
        docs = len({r["doc_id"] for r in sel})
        binding = sum(1 for r in sel if r["binding"] == "binding")
        lines.append(f"{label} & {docs} & {len(sel):,} & {binding:,}\\\\")
    uae = [r for r in rows if r["jurisdiction"].startswith("AE")]
    macros += [macro("KBUaeClauses", f"{len(uae):,}"), macro("KBUaeDocs", len({r['doc_id'] for r in uae})),
               macro("KBDohRaiClauses", sum(1 for r in rows if r["doc_id"] == "AE-DOH-RAI-2025"))]
    lines.append("\\midrule")
    lines.append(f"Total & {len({r['doc_id'] for r in rows})} & {len(rows):,} & {sum(1 for r in rows if r['binding'] == 'binding'):,}\\\\")
    lines += ["\\bottomrule", "\\end{tabularx}"]
    return "\n".join(lines) + "\n", macros


def timeline(R: dict, scenario: dict) -> str:
    stages = scenario["stages"]
    short = {"T0": "Cloud outage,\\\\failover", "T1": "Arabic triage\\\\drift", "T2": "Records found\\\\abroad",
             "T3": "Possible\\\\ransomware", "T4": "Public reports\\\\of misdiagnosis", "T5": "Primary region\\\\restored"}
    W, H, X0 = 2.32, 0.42, 3.0  # column width, row height, label column width (cm)
    lines = ["\\begin{tikzpicture}[font=\\footnotesize, x=1cm, y=1cm]"]
    for i, s in enumerate(stages):
        x = X0 + i * W + W / 2
        lines.append(f"\\node[font=\\footnotesize\\bfseries\\sffamily] at ({x:.2f},1.25) {{{s['id']}\\enspace {s['sim_time']}}};")
        lines.append(f"\\node[align=center, font=\\scriptsize, text=black!70] at ({x:.2f},0.72) {{{short.get(s['id'], s['id'])}}};")
    y = -0.05
    lines.append(f"\\node[anchor=west, font=\\scriptsize\\bfseries, text=black!60] at (0,{y:.2f}) {{WHO RECEIVED EACH EVENT}};")
    for aid, label in AGENTS:
        y -= H
        lines.append(f"\\node[anchor=west] at (0.1,{y:.2f}) {{{label}}};")
        for i, s in enumerate(stages):
            x = X0 + i * W + W / 2
            if aid in s["recipients"]:
                lines.append(f"\\fill[ink] ({x - 0.13:.2f},{y - 0.13:.2f}) rectangle ({x + 0.13:.2f},{y + 0.13:.2f});")
            else:
                lines.append(f"\\draw[black!25] ({x:.2f},{y:.2f}) circle (0.05);")
    y -= 0.55
    lines.append(f"\\node[anchor=west, font=\\scriptsize\\bfseries, text=black!60] at (0,{y:.2f}) {{WHAT THE GATE DID WITH THE AI TRIAGE}};")
    rows = [("gov", "Governed"), ("ungov", "Ungoverned"), ("cards", "Governed,\\\\human approves")]
    for key, label in rows:
        y -= 0.62
        lines.append(f"\\node[anchor=west, align=left] at (0.1,{y:.2f}) {{{label}}};")
        for i, s in enumerate(stages):
            x = X0 + i * W + W / 2
            g = R[key]["stages"].get(s["id"])
            if not g or g["decision"] == "ALLOW":
                lines.append(f"\\node[text=black!40] at ({x:.2f},{y:.2f}) {{allowed}};")
                continue
            if g["decision"] == "DENY" and g["enforced"]:
                style, text = "deny", "Blocked 403"
            elif g["decision"] == "DENY":
                style, text = "denyopen", "Breach let\\\\through"
            elif g["enforced"]:
                style, text = "esc", "Human " + ("approves" if g["human"] == "approve" else "rejects")
            else:
                style, text = "escopen", "Escalation\\\\bypassed"
            lines.append(f"\\node[{style}] at ({x:.2f},{y:.2f}) {{{text}}};")
    lines.append(f"\\draw[black!20] (0,0.27) -- ({X0 + len(stages) * W:.2f},0.27);")
    lines.append("\\end{tikzpicture}")
    return "\n".join(lines) + "\n"


def outcomes(R: dict, early: dict) -> str:
    def coords(key: str) -> str:
        r = early if key == "early" else R[key]
        vals = [r["m"]["gate"]["would_deny_let_through"], r["m"]["gate"]["would_escalate_let_through"],
                r["blocked"], r["to_human"]]
        return " ".join(f"({v},{i})" for i, v in enumerate(vals))
    return (
        "\\begin{tikzpicture}\n\\begin{axis}[xbar, width=0.92\\linewidth, height=6.2cm, bar width=4.4pt,\n"
        "  ytick={0,1,2,3}, yticklabels={{Violations carried out}, {Escalations bypassed}, {Blocked with 403}, {Sent to a human}},\n"
        "  y dir=reverse, xmin=0, enlarge y limits=0.18, xlabel={count in one run}, tick label style={font=\\scriptsize},\n"
        "  label style={font=\\scriptsize}, legend style={font=\\scriptsize, at={(0.5,1.02)}, anchor=south, legend columns=2, draw=none},\n"
        "  axis lines*=left, xmajorgrids, grid style={black!10}, xtick distance=1]\n"
        f"\\addplot[fill=ink, draw=ink] coordinates {{{coords('gov')}}};\n"
        f"\\addplot[fill=denyc!70, draw=denyc] coordinates {{{coords('ungov')}}};\n"
        f"\\addplot[fill=white, draw=denyc, pattern=north east lines, pattern color=denyc] coordinates {{{coords('early')}}};\n"
        f"\\addplot[fill=escc!60, draw=escc] coordinates {{{coords('cards')}}};\n"
        "\\legend{Governed, Ungoverned, Ungoverned earlier run, Governed with approving human}\n\\end{axis}\n\\end{tikzpicture}\n")


def citations(R: dict) -> str:
    order = [("gov", "Governed"), ("ungov", "Ungoverned"), ("ar", "Governed in Arabic"), ("cards", "Approving human")]
    cats = [("VERIFIED", "Verbatim", "okc"), ("NEAR_MATCH", "Near match", "escc"),
            ("FAILED+NOT_RETRIEVED+UNSUPPORTED", "Failed or unsupported", "denyc"),
            ("UNKNOWN_CLAUSE", "Malformed clause id", "black!45")]
    plots = []
    for keys, label, color in cats:
        pts = []
        for i, (k, _) in enumerate(order):
            c = R[k]["m"]["citations"]
            tot = checked(R[k]["m"])
            v = sum(c.get(x, 0) for x in keys.split("+"))
            pts.append(f"({100 * v / tot:.1f},{i})")
        plots.append(f"\\addplot[fill={color}, draw={color}] coordinates {{{' '.join(pts)}}};\\addlegendentry{{{label}}}")
    labels = ",".join("{" + l + "}" for _, l in order)
    return (
        "\\begin{tikzpicture}\n\\begin{axis}[xbar stacked, width=\\linewidth, height=4.1cm, bar width=8pt, xmin=0, xmax=100,\n"
        f"  ytick={{0,1,2,3}}, yticklabels={{{labels}}}, y dir=reverse, enlarge y limits=0.2,\n"
        "  xlabel={share of checked citations (\\%)}, tick label style={font=\\scriptsize}, label style={font=\\scriptsize},\n"
        "  legend style={font=\\tiny, at={(0.5,1.03)}, anchor=south, legend columns=2, draw=none}, axis lines*=left]\n"
        + "\n".join(plots) + "\n\\end{axis}\n\\end{tikzpicture}\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    for k in ("gov", "ungov", "ar", "cards", "ungov_early"):
        ap.add_argument(f"--{k}", required=True)
    a = ap.parse_args()
    R = {k: facts(MAJLIS / getattr(a, k)) for k in ("gov", "ungov", "ar", "cards")}
    early = facts(MAJLIS / a.ungov_early)
    for k, r in R.items():
        assert r["chain"], f"{k}: hash chain broken"
    kb = json.loads((MAJLIS / "kb/sources/kb_stats.json").read_text())
    ev = json.loads((MAJLIS / "kb/retrieval_eval_results.json").read_text())
    gaps = yaml.safe_load((MAJLIS / "configs/gaps_verified.yaml").read_text())["gaps"]
    rules = yaml.safe_load((MAJLIS / "configs/policies/uae_rules.yaml").read_text())["rules"]
    scenario = yaml.safe_load((MAJLIS / "configs/scenarios/s1_failover.yaml").read_text())
    OUT.mkdir(exist_ok=True)
    (OUT / "numbers.tex").write_text(numbers(R, kb, ev, gaps, rules))
    (OUT / "fig_timeline.tex").write_text(timeline(R, scenario))
    (OUT / "fig_outcomes.tex").write_text(outcomes(R, early))
    with open(OUT / "numbers.tex", "a") as f:
        f.write(macro("EarlyLetThrough", early["m"]["gate"]["would_deny_let_through"]) + "\n")
        f.write(macro("EarlyBypassed", early["m"]["gate"]["would_escalate_let_through"]) + "\n")
    (OUT / "fig_citations.tex").write_text(citations(R))
    tab, kb_macros = kb_table()
    (OUT / "tab_kb.tex").write_text(tab)
    with open(OUT / "numbers.tex", "a") as f:
        f.write("\n".join(kb_macros) + "\n")
    (OUT / "runs.txt").write_text("\n".join(f"{k}: {getattr(a, k)}" for k in ("gov", "ungov", "ar", "cards")) + "\n")
    print("generated:", ", ".join(p.name for p in sorted(OUT.iterdir())))


if __name__ == "__main__":
    main()
