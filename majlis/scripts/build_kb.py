#!/usr/bin/env python
"""Build the MAJLIS clause-level knowledge base.

  manifest.csv -> (download missing, plain requests, logged) -> pick up manual files
  -> parse -> clause-split -> kb/clauses/clauses.jsonl (each row validated as Clause)
  -> kb/sources/kb_stats.json, kb/sources/qa_samples.md, kb/Inputs.md, InputDocs copy

Usage:
  .venv/bin/python scripts/build_kb.py                 # download what is missing, then build
  .venv/bin/python scripts/build_kb.py --no-download   # rebuild from files on disk only
  .venv/bin/python scripts/build_kb.py --retry-blocked # also re-try rows marked manual_pending that have a URL
Idempotent: same files on disk -> byte-identical clauses.jsonl.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import random
import re
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from majlis.kb_build import (PAGE_SEP, arabic_quality, clause_quality, parse_document,  # noqa: E402
                             words)
from majlis.kb_fetch import fetch, log_attempt  # noqa: E402
from majlis.schemas import Clause  # noqa: E402

KB = ROOT / "kb"
RAW = KB / "raw"
MANUAL = RAW / "manual"
SOURCES = KB / "sources"
MANIFEST = SOURCES / "manifest.csv"
ACCESS_LOG = SOURCES / "access_log.csv"
CLAUSES = KB / "clauses" / "clauses.jsonl"
FAILED = KB / "clauses" / "extraction_failed.jsonl"
INPUTDOCS = ROOT.parent / "simulation" / "server" / "knowledge" / "InputDocs" / "MAJLIS_UAE_Health_Telecom"
TODAY = "2026-11-09"
FIELDS = ["doc_id", "title", "issuer", "date", "url", "download_url", "lang", "jurisdiction", "tier",
          "instrument_type", "binding", "sectors", "priority", "status", "sha256", "retrieved_at",
          "licence_note", "local_path"]
CELLAR_HEADERS = {"Accept": "application/xhtml+xml", "Accept-Language": "eng"}


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def rel(p: Path) -> str:
    return str(p.relative_to(ROOT))


def read_manifest() -> list[dict]:
    with MANIFEST.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_manifest(rows: list[dict]) -> None:
    with MANIFEST.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})


def lang_suffix(row) -> str:
    return "" if row["lang"] == "en" else f".{row['lang']}"


def default_ext(row) -> str:
    d = row["download_url"]
    if d.startswith("cellar:"):
        return ".xhtml"
    if d.startswith("flipbook:"):
        return ".html"
    return ".pdf"


def manual_file(row) -> Path | None:
    for ext in (".pdf", ".html", ".htm", ".xhtml"):
        p = MANUAL / f"{row['doc_id']}{lang_suffix(row)}{ext}"
        if p.exists() and p.stat().st_size > 0:
            return p
    return None


# ---------------------------------------------------------------------------
# download
# ---------------------------------------------------------------------------
def download(row: dict) -> Path | None:
    d = row["download_url"]
    dest = RAW / f"{row['doc_id']}{lang_suffix(row)}{default_ext(row)}"
    doc = row["doc_id"]
    if d.startswith("repo:"):
        src = (ROOT / d[5:]).resolve()
        ok = src.exists()
        log_attempt(ACCESS_LOG, {"ts": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                 "doc_id": doc, "url": d, "http_status": "", "bytes": src.stat().st_size if ok else 0,
                                 "content_type": "application/pdf", "result": "ok" if ok else "missing",
                                 "note": "copied from reference repo InputDocs"})
        if ok:
            shutil.copy2(src, dest)
            return dest
        return None
    if d.startswith("cellar:"):
        ok, _ = fetch(f"http://publications.europa.eu/resource/celex/{d[7:]}", dest, doc_id=doc,
                      log_path=ACCESS_LOG, expect="xhtml", headers=CELLAR_HEADERS,
                      note="EU Publications Office Cellar content negotiation")
        return dest if ok else None
    if d.startswith("flipbook:"):
        tmpl = d[9:]
        parts = []
        for n in range(1, 400):
            ok, body = fetch(tmpl.format(n=n), None, doc_id=doc, log_path=ACCESS_LOG, expect="html",
                             note="flipbook basic-html page")
            if not ok:
                break
            parts.append(f"{PAGE_SEP} {n} {tmpl.format(n=n)} -->\n".encode() + body)
        if not parts:
            return None
        dest.write_bytes(b"\n".join(parts))
        return dest
    if d.startswith("http"):
        ok, _ = fetch(d, dest, doc_id=doc, log_path=ACCESS_LOG, expect="pdf" if dest.suffix == ".pdf" else "html")
        return dest if ok else None
    return None


def resolve_files(rows: list[dict], do_download: bool, retry_blocked: bool) -> None:
    for r in rows:
        mf = manual_file(r)
        if mf is not None:
            if r["status"] != "manual_ok" or r.get("local_path") != rel(mf):
                r["status"] = "manual_ok"
                r["local_path"] = rel(mf)
                r["retrieved_at"] = dt.date.fromtimestamp(mf.stat().st_mtime).isoformat()
            r["sha256"] = sha256(mf)
            continue
        if r["status"] == "manual_ok":          # manual file was removed
            r["status"] = "manual_pending"
        local = ROOT / r["local_path"] if r.get("local_path") else RAW / f"{r['doc_id']}{lang_suffix(r)}{default_ext(r)}"
        if local.exists() and local.stat().st_size > 0 and r["status"] in ("ok", "failed"):
            r["local_path"] = rel(local)
            r["sha256"] = sha256(local)
            r["status"] = "ok"
            if not r.get("retrieved_at"):
                r["retrieved_at"] = TODAY
            continue
        want = r["status"] in ("ok", "failed") or (retry_blocked and r["status"] == "manual_pending")
        if do_download and want and r["download_url"]:
            p = download(r)
            if p is not None:
                r["status"], r["local_path"], r["sha256"] = "ok", rel(p), sha256(p)
                if r["download_url"].startswith("repo:"):
                    r["retrieved_at"] = dt.date.fromtimestamp(p.stat().st_mtime).isoformat()
                else:
                    r["retrieved_at"] = TODAY
                continue
            if r["status"] == "ok":
                r["status"] = "failed"
        if r["status"] == "manual_pending":
            r["local_path"] = rel(MANUAL / f"{r['doc_id']}{lang_suffix(r)}.pdf")


# ---------------------------------------------------------------------------
# build clauses
# ---------------------------------------------------------------------------
def translation_status(row) -> str:
    if row["jurisdiction"].startswith("AE") and row["tier"] == "A" and row["lang"] == "en":
        return "unofficial_translation"
    return "original"


def build(rows: list[dict]) -> dict:
    clauses: list[dict] = []
    failed: list[dict] = []
    stats_docs: dict = {}
    for r in rows:
        key = f"{r['doc_id']}[{r['lang']}]"
        if r["status"] not in ("ok", "manual_ok"):
            stats_docs[key] = {"status": r["status"], "clauses": 0}
            continue
        path = ROOT / r["local_path"]
        units, info = parse_document(r, path, r["lang"])
        doc_failed_reason = None
        if r["lang"] == "ar" and units:
            ok, why = arabic_quality("\n".join(u.text for u in units))
            if not ok:
                doc_failed_reason = why
        n_ok = n_fail = 0
        fail_reasons: Counter = Counter()
        wc = []
        for u in units:
            cid = f"{r['doc_id']}/{u.id_core()}/{r['lang']}"
            ok, why = clause_quality(u.text, r["lang"])
            if doc_failed_reason:
                ok, why = False, doc_failed_reason
            rec = {
                "clause_id": cid, "doc_id": r["doc_id"], "doc_title": r["title"], "issuer": r["issuer"],
                "jurisdiction": r["jurisdiction"], "instrument_type": r["instrument_type"],
                "binding": r["binding"], "sectors": [s for s in r["sectors"].split(";") if s],
                "language": r["lang"], "translation_status": translation_status(r),
                "parallel_clause_id": None,
                "article": u.article if u.kind == "art" else u.article,
                "paragraph": u.paragraph, "heading": u.heading, "text": u.text, "url": r["url"],
                "page": u.page if path.suffix.lower() == ".pdf" else None,
                "effective_date": None, "retrieved_at": r["retrieved_at"] or TODAY,
                "source_sha256": r["sha256"], "tier": r["tier"],
                "extraction": "ok" if r["status"] == "ok" else "manual",
            }
            if not ok:
                rec["extraction"] = "extraction_failed"
                rec["failure_reason"] = why
                failed.append(rec)
                n_fail += 1
                fail_reasons[why] += 1
                continue
            Clause.model_validate(rec)
            clauses.append(rec)
            n_ok += 1
            wc.append(words(u.text))
        if not units:
            n_fail = 1
            fail_reasons["no_units:" + "; ".join(info.get("notes") or [info.get("mode", "")])] += 1
        stats_docs[key] = {
            "status": r["status"], "mode": info.get("mode"), "clauses": n_ok,
            "extraction_failed": n_fail, "failure_reasons": dict(fail_reasons),
            "avg_words": round(sum(wc) / len(wc), 1) if wc else 0,
            "min_words": min(wc) if wc else 0, "max_words": max(wc) if wc else 0,
            "glyph_repairs": info.get("glyph_repairs") or {}, "notes": info.get("notes") or [],
        }
    # uniqueness
    ids = Counter(c["clause_id"] for c in clauses)
    dup = [k for k, v in ids.items() if v > 1]
    if dup:
        raise SystemExit(f"duplicate clause_ids: {dup[:10]}")
    # Arabic/English pairing by doc + article + paragraph
    by_key = defaultdict(dict)
    for c in clauses:
        by_key[(c["doc_id"], c["article"], c["paragraph"])][c["language"]] = c
    unpaired = []
    bilingual_docs = {c["doc_id"] for c in clauses if c["language"] == "ar"} & {c["doc_id"] for c in clauses if c["language"] == "en"}
    for (doc, _, _), langs in by_key.items():
        if doc not in bilingual_docs:
            continue
        if "en" in langs and "ar" in langs:
            langs["en"]["parallel_clause_id"] = langs["ar"]["clause_id"]
            langs["ar"]["parallel_clause_id"] = langs["en"]["clause_id"]
        else:
            unpaired.extend(c["clause_id"] for c in langs.values())
    # write
    CLAUSES.parent.mkdir(parents=True, exist_ok=True)
    with CLAUSES.open("w", encoding="utf-8") as f:
        for c in clauses:
            Clause.model_validate(c)
            f.write(json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n")
    with FAILED.open("w", encoding="utf-8") as f:
        for c in failed:
            f.write(json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n")
    return {"docs": stats_docs, "clauses": clauses, "failed": failed, "unpaired": unpaired}


# ---------------------------------------------------------------------------
# reports
# ---------------------------------------------------------------------------
def write_stats(rows, res) -> dict:
    cl = res["clauses"]
    st = {
        "built_at": TODAY,
        "kb_version_sha256": sha256(CLAUSES),
        "manifest_rows": len(rows),
        "documents_total": len({r["doc_id"] for r in rows}),
        "documents_with_clauses": len({c["doc_id"] for c in cl}),
        "files_by_status": dict(Counter(r["status"] for r in rows)),
        "clauses_total": len(cl),
        "clauses_per_doc": dict(sorted(Counter(f"{c['doc_id']}[{c['language']}]" for c in cl).items())),
        "languages": dict(Counter(c["language"] for c in cl)),
        "jurisdictions": dict(Counter(c["jurisdiction"] for c in cl)),
        "tiers": dict(sorted(Counter(c["tier"] for c in cl).items())),
        "binding": dict(Counter(c["binding"] for c in cl)),
        "avg_words": round(sum(words(c["text"]) for c in cl) / max(1, len(cl)), 1),
        "clauses_over_400_words": sum(1 for c in cl if words(c["text"]) > 400),
        "clauses_under_50_words": sum(1 for c in cl if words(c["text"]) < 50),
        "extraction_failures_total": sum(d.get("extraction_failed", 0) for d in res["docs"].values()),
        "extraction_failures_by_doc": {k: {"n": v["extraction_failed"], "reasons": v["failure_reasons"]}
                                       for k, v in res["docs"].items() if v.get("extraction_failed")},
        "parallel_pairs": sum(1 for c in cl if c["parallel_clause_id"] and c["language"] == "en"),
        "unpaired_bilingual_clauses": len(res["unpaired"]),
        "unpaired_sample": res["unpaired"][:20],
        "per_document": res["docs"],
    }
    (SOURCES / "kb_stats.json").write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return st


def write_qa(res) -> None:
    rnd = random.Random(1689)
    by_doc = defaultdict(list)
    for c in res["clauses"]:
        by_doc[f"{c['doc_id']} [{c['language']}]"].append(c)
    out = ["# KB QA samples", "",
           "8 random clauses per document (seeded, first 300 characters) for a human eyeball check.",
           "Regenerated by `scripts/build_kb.py`.", ""]
    for doc in sorted(by_doc):
        cs = by_doc[doc]
        out.append(f"## {doc} ({len(cs)} clauses)")
        out.append("")
        for c in sorted(rnd.sample(cs, min(8, len(cs))), key=lambda x: x["clause_id"]):
            snippet = c["text"][:300].replace("\n", " / ")
            out.append(f"- `{c['clause_id']}` ({words(c['text'])} w, heading: {c['heading'] or '-'})")
            out.append(f"  > {snippet}")
        out.append("")
    (SOURCES / "qa_samples.md").write_text("\n".join(out), encoding="utf-8")


TYPE_MAP = {"law": "national_law", "regulation": "regulation", "decree": "national_law", "standard": "sector_standard",
            "strategy": "national_strategy", "charter": "policy_document", "guidance": "guidance",
            "framework": "policy_document", "itu_recommendation": "itu_standard", "policy": "policy_document"}


def inputdocs_name(r) -> str:
    p = ROOT / r["local_path"]
    ext = ".html" if p.suffix.lower() in (".xhtml", ".htm") else p.suffix.lower()
    return f"{r['doc_id']}{lang_suffix(r)}{ext}"


def write_inputs_and_copy(rows, st) -> None:
    INPUTDOCS.mkdir(parents=True, exist_ok=True)
    lines = ["# MAJLIS knowledge-base inputs", "",
             "Official source documents behind `kb/clauses/clauses.jsonl`. Same table style as the reference repo's",
             "`simulation/server/knowledge/InputDocs/Inputs.md`, plus issuer, date and official URL.",
             "Files obtained here (not already in the reference repo) are copied to",
             "`simulation/server/knowledge/InputDocs/MAJLIS_UAE_Health_Telecom/` so the reference repo's own",
             "`python -m server.knowledge.ingest` picks them up unchanged. EU XHTML is copied with an `.html` extension.",
             "Files that came from the reference repo are not copied again (avoids double ingestion).", "",
             "| # | Filename | Type | Description | Issuer | Date | Official URL | Status | Clauses |",
             "|---|----------|------|-------------|--------|------|--------------|--------|---------|"]
    per = st["clauses_per_doc"]
    for i, r in enumerate(rows, 1):
        have = r["status"] in ("ok", "manual_ok")
        fname = inputdocs_name(r) if have else f"(manual) {Path(r['local_path']).name}"
        n = per.get(f"{r['doc_id']}[{r['lang']}]", 0)
        desc = f"**{r['title']}**. Tier {r['tier']}, {r['binding'].replace('_', '-')}, {r['jurisdiction']}, lang {r['lang']}; sectors {r['sectors'].replace(';', ', ')}."
        lines.append(f"| {i} | `{fname}` | `{TYPE_MAP.get(r['instrument_type'], r['instrument_type'])}` | {desc} | "
                     f"{r['issuer']} | {r['date'] or 'n/a'} | {r['url']} | {r['status']} | {n} |")
        usable = n > 0
        if have and usable and not r["download_url"].startswith("repo:"):
            src = ROOT / r["local_path"]
            dst = INPUTDOCS / inputdocs_name(r)
            if not dst.exists() or dst.stat().st_size != src.stat().st_size:
                shutil.copy2(src, dst)
        elif have and not usable:
            stale = INPUTDOCS / inputdocs_name(r)
            if stale.exists():          # no extractable text: not useful to the reference ingest
                stale.unlink()
    lines += ["", "Manual downloads still needed: see `kb/sources/MANUAL_DOWNLOADS.md`.", ""]
    (KB / "Inputs.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-download", action="store_true")
    ap.add_argument("--retry-blocked", action="store_true")
    a = ap.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    MANUAL.mkdir(parents=True, exist_ok=True)
    rows = read_manifest()
    resolve_files(rows, not a.no_download, a.retry_blocked)
    write_manifest(rows)
    res = build(rows)
    st = write_stats(rows, res)
    write_qa(res)
    write_inputs_and_copy(rows, st)
    print(f"{'doc':34} {'lang':4} {'status':15} {'mode':12} {'clauses':>7} {'failed':>6} {'avg_w':>6}")
    for r in rows:
        d = res["docs"].get(f"{r['doc_id']}[{r['lang']}]", {})
        print(f"{r['doc_id']:34} {r['lang']:4} {r['status']:15} {str(d.get('mode') or '-'):12} "
              f"{d.get('clauses', 0):>7} {d.get('extraction_failed', 0):>6} {d.get('avg_words', 0):>6}")
    print(f"\nclauses: {st['clauses_total']}  docs with clauses: {st['documents_with_clauses']}/{st['documents_total']}  "
          f"failed units: {st['extraction_failures_total']}  >400w: {st['clauses_over_400_words']}  "
          f"<50w: {st['clauses_under_50_words']}  pairs: {st['parallel_pairs']}")
    print(f"wrote {rel(CLAUSES)} (sha256 {st['kb_version_sha256'][:12]})")


if __name__ == "__main__":
    main()
