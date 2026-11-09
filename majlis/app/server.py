"""MAJLIS exercise console: FastAPI server for the static console and its JSON API.

Run from the project root:
    .venv/bin/python -m uvicorn app.server:app --port 8765

Read-only endpoints import majlis.* modules lazily. If a module is not there yet the endpoint
returns HTTP 503 {"pending": "<module>"} and the console shows a calm "not available yet" state.
Config endpoints read configs/*; when a file is absent they fall back to the synthetic fixture
configs in tests/fixtures/console_configs/ (response header X-Majlis-Source: fixture).
"""
from __future__ import annotations

import hashlib
import importlib
import json
import re
import secrets
import subprocess
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402
from fastapi import Body, FastAPI, HTTPException, Query  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

STATIC = ROOT / "app" / "static"
RUNS_DIRS = [ROOT / "runs", ROOT / "tests" / "fixtures" / "runs"]
CONFIGS = ROOT / "configs"
FIXTURE_CONFIGS = ROOT / "tests" / "fixtures" / "console_configs"
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,127}$")
ACTION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,127}$")
GENESIS = "0" * 64
LITE_STRIP = ("system", "user", "raw_output")

Y3172_NODE_FALLBACK = {
    "run_start": "MLFO", "inject": "SRC", "retrieval": "PP", "llm_call": "M", "agent_turn": "M",
    "citation_check": "P", "gate_decision": "P", "human_decision": "SINK", "message": "D",
    "stage_end": "MLFO", "gap_candidate": "SINK", "agent_error": "M", "metrics": "MLFO", "run_end": "MLFO",
}

app = FastAPI(title="MAJLIS Exercise Console", docs_url="/api/docs", redoc_url=None)
_procs: dict[str, subprocess.Popen] = {}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
class Pending(Exception):
    def __init__(self, module: str):
        self.module = module


@app.exception_handler(Pending)
async def _pending_handler(_req, exc: Pending):
    return JSONResponse({"pending": exc.module}, status_code=503)


def _mod(name: str):
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as e:
        if e.name and (e.name == name or name.startswith(e.name)):
            raise Pending(name)
        raise


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _run_dir(run_id: str) -> Path:
    if not RUN_ID_RE.match(run_id or "") or ".." in run_id:
        raise HTTPException(400, "invalid run id")
    for base in RUNS_DIRS:
        d = (base / run_id).resolve()
        if d.parent == base.resolve() and d.is_dir():
            return d
    raise HTTPException(404, "run not found")


def _read_entries(run_dir: Path) -> list[dict]:
    p = run_dir / "ledger.jsonl"
    if not p.exists():
        return []
    out = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                break  # partially written last line during a live run
    return out


def _y3172_map() -> dict:
    try:
        m = importlib.import_module("majlis.ledger")
        node = getattr(m, "Y3172_NODE", None)
        if isinstance(node, dict) and node:
            return node
    except Exception:
        pass
    return Y3172_NODE_FALLBACK


def _node_of(event_type: str) -> str:
    v = _y3172_map().get(event_type, "")
    # labels like "SRC→C" or "SINK (HA)" -> primary node token
    return re.split(r"[^A-Z]", v.strip())[0] if v else ""


def _lite(entry: dict) -> dict:
    if entry.get("event_type") == "llm_call":
        e = dict(entry)
        e["payload"] = {k: v for k, v in entry["payload"].items() if k not in LITE_STRIP}
        return e
    return entry


def _verify(entries: list[dict]) -> dict:
    try:
        m = importlib.import_module("majlis.ledger")
        fn = getattr(m, "verify_chain", None)
    except Exception:
        fn = None
    if fn is not None:
        try:
            ok, n, broken = fn(entries)
            return {"ok": bool(ok), "n_entries": n, "first_broken_seq": broken, "verifier": "majlis.ledger"}
        except Exception:
            pass
    prev = GENESIS
    for e in entries:
        body = {k: v for k, v in e.items() if k != "hash"}
        h = hashlib.sha256((prev + _canonical(body)).encode("utf-8")).hexdigest()
        if e.get("prev_hash") != prev or e.get("hash") != h:
            return {"ok": False, "n_entries": len(entries), "first_broken_seq": e.get("seq"),
                    "verifier": "console"}
        prev = h
    return {"ok": True, "n_entries": len(entries), "first_broken_seq": None, "verifier": "console",
            "head_hash": prev}


def _config_path(rel: str) -> tuple[Optional[Path], str]:
    p = CONFIGS / rel
    if p.exists():
        return p, "configs"
    f = FIXTURE_CONFIGS / rel
    if f.exists():
        return f, "fixture"
    return None, ""


def _yaml_response(rel: str, module_hint: str):
    p, src = _config_path(rel)
    if p is None:
        raise Pending(module_hint)
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    return JSONResponse(data, headers={"X-Majlis-Source": src})


def _yaml_dir(rel: str) -> tuple[list[tuple[Path, Any]], str]:
    for base, src in ((CONFIGS / rel, "configs"), (FIXTURE_CONFIGS / rel, "fixture")):
        if base.is_dir():
            files = sorted(base.glob("*.yaml")) + sorted(base.glob("*.yml"))
            if files:
                return [(f, yaml.safe_load(f.read_text(encoding="utf-8"))) for f in files], src
    return [], ""


# ---------------------------------------------------------------------------
# KB access (clauses.jsonl read directly; search via majlis.retrieval)
# ---------------------------------------------------------------------------
def _kb_dir() -> Path:
    real = ROOT / "kb" / "clauses" / "clauses.jsonl"
    if real.exists() and real.stat().st_size > 0:
        return ROOT / "kb"
    return ROOT / "tests" / "fixtures" / "kb"


_clause_cache: dict[str, Any] = {"key": None, "clauses": {}}


def _clauses() -> dict[str, dict]:
    p = _kb_dir() / "clauses" / "clauses.jsonl"
    if not p.exists():
        return {}
    key = (str(p), p.stat().st_mtime)
    if _clause_cache["key"] != key:
        out = {}
        with open(p, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        c = json.loads(line)
                        out[c["clause_id"]] = c
                    except Exception:
                        continue
        _clause_cache.update(key=key, clauses=out)
    return _clause_cache["clauses"]


_kb_obj: dict[str, Any] = {"key": None, "kb": None}


def _kb():
    retrieval = _mod("majlis.retrieval")
    kd = _kb_dir()
    p = kd / "clauses" / "clauses.jsonl"
    key = (str(kd), p.stat().st_mtime if p.exists() else 0)
    if _kb_obj["key"] != key:
        _kb_obj.update(key=key, kb=retrieval.KB.load(kd))
    return _kb_obj["kb"], retrieval


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = re.sub(r"[ً-ْـ]", "", s)
    return re.sub("[إأآا]", "ا", s)


def _dump(obj):
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, dict):
        return obj
    return dict(obj.__dict__)


# ---------------------------------------------------------------------------
# runs
# ---------------------------------------------------------------------------
def _run_summary(d: Path) -> dict:
    entries_path = d / "ledger.jsonl"
    manifest = {}
    if (d / "manifest.json").exists():
        try:
            manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        except Exception:
            manifest = {}
    first, last, n = None, None, 0
    if entries_path.exists():
        with open(entries_path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                n += 1
                if first is None:
                    try:
                        first = json.loads(line)
                    except Exception:
                        pass
                last = line
    try:
        last_e = json.loads(last) if last else None
    except Exception:
        last_e = None
    rs = (first or {}).get("payload", {}) if first and first.get("event_type") == "run_start" else {}
    if last_e and last_e.get("event_type") == "run_end":
        status = last_e["payload"].get("status", "completed")
    elif d.name in _procs and _procs[d.name].poll() is None:
        status = "running"
    elif d.name in _procs:
        status = "failed" if _procs[d.name].returncode else "incomplete"
    elif entries_path.exists() and time.time() - entries_path.stat().st_mtime < 120:
        status = "running"
    elif n == 0 and (d / "spawn.json").exists() and time.time() - (d / "spawn.json").stat().st_mtime < 60:
        status = "starting"
    else:
        status = "incomplete"
    return {
        "id": d.name,
        "scenario": rs.get("scenario_id") or manifest.get("scenario"),
        "title": rs.get("title"),
        "mode": rs.get("mode") or manifest.get("mode"),
        "lang": rs.get("lang") or manifest.get("lang"),
        "approver": rs.get("approver") or manifest.get("approver"),
        "model": rs.get("model") or manifest.get("model"),
        "backend": rs.get("backend") or manifest.get("backend"),
        "started": (first or {}).get("ts") or manifest.get("started_at"),
        "status": status,
        "n_entries": n,
        "fixture": d.parent == (ROOT / "tests" / "fixtures" / "runs") or bool(manifest.get("fixture")),
    }


@app.get("/api/runs")
def list_runs():
    out = []
    for base in RUNS_DIRS:
        if not base.is_dir():
            continue
        for d in base.iterdir():
            if d.is_dir() and RUN_ID_RE.match(d.name) and ((d / "ledger.jsonl").exists() or (d / "spawn.json").exists()):
                out.append(_run_summary(d))
    out.sort(key=lambda r: (r["fixture"], -(datetime.fromisoformat(r["started"].replace("Z", "+00:00")).timestamp()
                                              if r.get("started") else 0)))
    return out


@app.get("/api/runs/{run_id}")
def run_summary(run_id: str):
    return _run_summary(_run_dir(run_id))


@app.get("/api/runs/{run_id}/ledger")
def run_ledger(run_id: str, after: int = Query(-1), lite: int = Query(0)):
    entries = _read_entries(_run_dir(run_id))
    out = [e for e in entries if e.get("seq", -1) > after]
    if lite:
        out = [_lite(e) for e in out]
    for e in out:
        e["node"] = _node_of(e.get("event_type", ""))
    return {"run_id": run_id, "entries": out, "n_total": len(entries),
            "done": bool(entries) and entries[-1].get("event_type") == "run_end"}


@app.get("/api/runs/{run_id}/entry/{seq}")
def run_entry(run_id: str, seq: int):
    for e in _read_entries(_run_dir(run_id)):
        if e.get("seq") == seq:
            e["node"] = _node_of(e.get("event_type", ""))
            e["node_label"] = _y3172_map().get(e.get("event_type", ""), "")
            return e
    raise HTTPException(404, "entry not found")


@app.get("/api/runs/{run_id}/verify")
def run_verify(run_id: str):
    return _verify(_read_entries(_run_dir(run_id)))


@app.get("/api/runs/{run_id}/metrics")
def run_metrics(run_id: str):
    entries = _read_entries(_run_dir(run_id))
    for e in reversed(entries):
        if e.get("event_type") == "metrics":
            return {"source": "ledger", "seq": e["seq"], "metrics": e["payload"]}
    metrics = _mod("majlis.metrics")
    return {"source": "computed", "seq": None, "metrics": metrics.compute(entries)}


@app.get("/api/runs/{run_id}/aar")
def run_aar(run_id: str):
    d = _run_dir(run_id)
    if (d / "aar.md").exists():
        return PlainTextResponse((d / "aar.md").read_text(encoding="utf-8"), media_type="text/markdown; charset=utf-8")
    aar = _mod("majlis.aar")
    return PlainTextResponse(aar.render_aar(_read_entries(d)), media_type="text/markdown; charset=utf-8")


@app.post("/api/runs")
def start_run(body: dict = Body(...)):
    scenario = str(body.get("scenario") or "s1_failover")
    mode = body.get("mode", "governed")
    approver = body.get("approver", "interactive")
    lang = body.get("lang", "en")
    backend = body.get("backend")
    if not re.match(r"^[A-Za-z0-9_\-]{1,64}$", scenario):
        raise HTTPException(400, "invalid scenario")
    if mode not in ("governed", "ungoverned") or approver not in ("interactive", "reject_all", "approve_all") \
            or lang not in ("en", "ar") or (backend and backend not in ("mock", "glm")):
        raise HTTPException(400, "invalid option")
    script = ROOT / "scripts" / "run_scenario.py"
    if not script.exists():
        raise Pending("scripts/run_scenario.py")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    run_id = f"{scenario}_{mode}_{lang}_{stamp}_{secrets.token_hex(2)}"
    run_dir = ROOT / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(script), "--scenario", scenario, "--mode", mode, "--approver", approver,
           "--lang", lang, "--run-id", run_id, "--runs-dir", str(ROOT / "runs"), "--quiet"]
    if backend:
        cmd += ["--backend", backend]
    inj = body.get("inject") or {}
    cards = [c for c in (body.get("cards") or ([inj["card"]] if inj.get("card") else []))
             if re.match(r"^[A-Za-z0-9_\-]{1,32}$", str(c))]
    for c in cards:
        cmd += ["--card", str(c)]
    text = (inj.get("text") or "").strip()
    if text:
        recips = [r for r in inj.get("recipients", []) if re.match(r"^[a-z_]{1,40}$", str(r))]
        if not recips:
            raise HTTPException(400, "a judge inject needs at least one recipient")
        cmd += ["--inject", text[:4000], "--recipients", ",".join(recips)]
        for k, v in (inj.get("state_changes") or {}).items():
            if re.match(r"^[A-Za-z0-9_]{1,64}$", str(k)):
                cmd += ["--state", f"{k}={json.dumps(v) if not isinstance(v, str) else v}"]
    if (text or cards) and inj.get("after"):
        if re.match(r"^[A-Za-z0-9_\-]{1,16}$", str(inj["after"])):
            cmd += ["--after", str(inj["after"])]
    (run_dir / "spawn.json").write_text(json.dumps({"cmd": cmd[1:], "at": stamp}, indent=2), encoding="utf-8")
    log = open(run_dir / "console_spawn.log", "w", encoding="utf-8")
    _procs[run_id] = subprocess.Popen(cmd, cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)
    return {"id": run_id}


@app.post("/api/runs/{run_id}/approvals/{action_id}")
def approve(run_id: str, action_id: str, body: dict = Body(...)):
    d = _run_dir(run_id)
    if not ACTION_ID_RE.match(action_id):
        raise HTTPException(400, "invalid action id")
    decision = body.get("decision")
    if decision not in ("approve", "reject"):
        raise HTTPException(400, "decision must be approve or reject")
    by = re.sub(r"[^\w .\-@]", "", str(body.get("by") or "exercise-controller"))[:64]
    (d / "approvals").mkdir(exist_ok=True)
    rec = {"decision": decision, "by": by, "at": datetime.now(timezone.utc).isoformat()}
    (d / "approvals" / f"{action_id}.json").write_text(json.dumps(rec), encoding="utf-8")
    return {"ok": True, **rec}


@app.get("/api/runs/{run_id}/approvals")
def approvals(run_id: str):
    d = _run_dir(run_id) / "approvals"
    out = {}
    if d.is_dir():
        for f in d.glob("*.json"):
            try:
                out[f.stem] = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                pass
    return out


# ---------------------------------------------------------------------------
# KB
# ---------------------------------------------------------------------------
def _split(v: Optional[str]) -> Optional[list[str]]:
    if not v:
        return None
    return [x for x in v.split(",") if x]


@app.get("/api/kb/search")
def kb_search(q: str = "", k: int = 8, jurisdiction: str = "", binding: str = "", language: str = "",
              mode: str = "rerank"):
    q = q.strip()[:500]
    k = max(1, min(int(k), 50))
    if mode not in ("rerank", "hybrid", "dense", "bm25"):
        mode = "rerank"
    cl = _clauses()
    if not q:
        return {"query": q, "mode": mode, "engine": None, "results": []}
    try:
        kb, retrieval = _kb()
        from majlis.schemas import RetrievalFilters
        filters = RetrievalFilters(jurisdiction=_split(jurisdiction), binding=_split(binding),
                                   language=_split(language))
        items = [_dump(x) for x in kb.search(q, filters=filters, k=k, mode=mode)]
        engine = "majlis.retrieval" + ("" if getattr(kb, "dense_available", True) or mode == "bm25"
                                       else " (dense unavailable: BM25 only)")
    except Pending:
        # keyword fallback so the console stays usable before retrieval.py lands
        terms = [t for t in re.split(r"\W+", _norm(q)) if len(t) > 1]
        scored = []
        for c in cl.values():
            if jurisdiction and c.get("jurisdiction") not in _split(jurisdiction):
                continue
            if binding and c.get("binding") not in _split(binding):
                continue
            if language and c.get("language") not in _split(language):
                continue
            hay = _norm(" ".join([c.get("text", ""), c.get("heading") or "", c.get("doc_title", "")]))
            s = sum(hay.count(t) for t in terms)
            if s:
                scored.append((s, c))
        scored.sort(key=lambda x: -x[0])
        items = [dict({k2: c.get(k2) for k2 in ("clause_id", "doc_id", "doc_title", "issuer", "jurisdiction",
                                                 "instrument_type", "binding", "article", "paragraph", "heading",
                                                 "language", "url", "text")}, score=float(s))
                 for s, c in scored[:k]]
        engine = "keyword fallback (majlis.retrieval pending)"
    for it in items:
        c = cl.get(it["clause_id"]) or {}
        par = c.get("parallel_clause_id")
        it["parallel"] = cl.get(par) if par else None
        it["sectors"] = c.get("sectors", [])
        it["translation_status"] = c.get("translation_status")
    return {"query": q, "mode": mode, "engine": engine, "results": items}


@app.get("/api/kb/stats")
def kb_stats():
    cl = list(_clauses().values())
    docs = {}
    for c in cl:
        docs.setdefault(c["doc_id"], c)
    by = lambda key: {v: sum(1 for c in cl if c.get(key) == v) for v in sorted({c.get(key) for c in cl if c.get(key)})}  # noqa: E731
    return {
        "kb_dir": str(_kb_dir().relative_to(ROOT)),
        "is_fixture": _kb_dir() != ROOT / "kb",
        "documents": len(docs), "clauses": len(cl),
        "languages": by("language"), "jurisdictions": by("jurisdiction"), "binding": by("binding"),
        "instrument_types": by("instrument_type"),
        "parallel_pairs": sum(1 for c in cl if c.get("parallel_clause_id")) // 2,
        "version": hashlib.sha256((_kb_dir() / "clauses" / "clauses.jsonl").read_bytes()).hexdigest()
        if (_kb_dir() / "clauses" / "clauses.jsonl").exists() else None,
    }


_fixture_clause_cache: dict[str, dict] = {}


def _fixture_clauses() -> dict[str, dict]:
    """The fictional TEST-DOC clauses, so fixture runs stay inspectable once the real KB exists."""
    if not _fixture_clause_cache:
        p = ROOT / "tests" / "fixtures" / "kb" / "clauses" / "clauses.jsonl"
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    c = json.loads(line)
                    _fixture_clause_cache[c["clause_id"]] = c
    return _fixture_clause_cache


@app.get("/api/kb/clause/{clause_id:path}")
def kb_clause(clause_id: str):
    cl = _clauses()
    c = cl.get(clause_id)
    if not c and clause_id.startswith("TEST-"):
        cl = _fixture_clauses()
        c = cl.get(clause_id)
    if not c:
        raise HTTPException(404, "clause not found")
    par = c.get("parallel_clause_id")
    return {"clause": c, "parallel": cl.get(par) if par else None}


@app.get("/api/kb/eval")
def kb_eval():
    p = ROOT / "kb" / "retrieval_eval_results.json"
    if not p.exists():
        raise Pending("kb/retrieval_eval_results.json")
    d = json.loads(p.read_text(encoding="utf-8"))
    q = ROOT / "kb" / "retrieval_eval.jsonl"
    if isinstance(d, dict) and q.exists():
        rows = [json.loads(x) for x in q.read_text(encoding="utf-8").splitlines() if x.strip()]
        d["needs_team_review"] = sum(1 for r in rows if r.get("status") == "needs_team_review")
        d["languages"] = {lang: sum(1 for r in rows if r.get("lang") == lang) for lang in sorted({r.get("lang") for r in rows if r.get("lang")})}
    if isinstance(d, dict):
        d.pop("per_question", None)  # large; not used by the console
    return d


# ---------------------------------------------------------------------------
# configs
# ---------------------------------------------------------------------------
@app.get("/api/config/agents")
def cfg_agents():
    files, src = _yaml_dir("agents")
    if not files:
        raise Pending("configs/agents")
    data = [d for _, d in files if isinstance(d, dict)]
    return JSONResponse(data, headers={"X-Majlis-Source": src})


@app.get("/api/config/scenarios")
def cfg_scenarios():
    files, src = _yaml_dir("scenarios")
    out = []
    for f, d in files:
        if isinstance(d, dict) and "stages" in d:
            out.append({"id": d.get("id", f.stem), "file": f.stem, "title": d.get("title"),
                        "title_ar": d.get("title_ar"), "n_stages": len(d.get("stages", [])),
                        "country_pack": d.get("country_pack")})
    if not out:
        raise Pending("configs/scenarios")
    return JSONResponse(out, headers={"X-Majlis-Source": src})


@app.get("/api/config/scenario/{scenario_id}")
def cfg_scenario(scenario_id: str):
    if not re.match(r"^[A-Za-z0-9_\-]{1,64}$", scenario_id):
        raise HTTPException(400, "invalid scenario id")
    return _yaml_response(f"scenarios/{scenario_id}.yaml", f"configs/scenarios/{scenario_id}.yaml")


@app.get("/api/config/challenge_cards")
def cfg_cards():
    return _yaml_response("scenarios/challenge_cards.yaml", "configs/scenarios/challenge_cards.yaml")


@app.get("/api/config/rules")
def cfg_rules(pack: str = "uae"):
    if not re.match(r"^[a-z]{2,8}$", pack):
        raise HTTPException(400, "invalid pack")
    return _yaml_response(f"policies/{pack}_rules.yaml", f"configs/policies/{pack}_rules.yaml")


@app.get("/api/config/y3172_mapping")
def cfg_y3172():
    return _yaml_response("y3172_mapping.yaml", "configs/y3172_mapping.yaml")


@app.get("/api/config/y3172_nodes")
def cfg_y3172_nodes():
    return _y3172_map()


@app.get("/api/readiness/dimensions")
def readiness_dimensions():
    try:
        r = importlib.import_module("majlis.readiness")
        for name in ("load_dimensions", "dimensions", "get_dimensions"):
            fn = getattr(r, name, None)
            if callable(fn):
                data = fn()
                return [_dump(x) for x in data] if isinstance(data, list) else data
    except Exception:
        pass
    p = ROOT.parent / "simulation" / "data" / "framework" / "dimensions.json"
    if not p.exists():
        raise Pending("majlis.readiness")
    d = json.loads(p.read_text(encoding="utf-8"))
    return [{"id": x["id"], "name": x["name"], "short_name": x.get("short_name"),
             "description": x.get("description"), "mapped_factors": x.get("mapped_factors", [])}
            for x in d.get("dimensions", [])]


@app.get("/api/gaps/verified")
def gaps_verified():
    p, src = _config_path("gaps_verified.yaml")
    if p is None:
        return {"gaps": [], "source": None}
    d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    gaps = d.get("gaps", d) if isinstance(d, dict) else d
    meta = {k: d.get(k) for k in ("checked_by", "team_signoff")} if isinstance(d, dict) else {}
    return {"gaps": gaps or [], "source": src, **meta}


@app.get("/api/_hold")
async def hold(ms: int = 2500):
    """Delays the page load event; used only by headless screenshot tooling (#...&shot=1)."""
    import asyncio
    from fastapi.responses import Response
    await asyncio.sleep(max(0, min(ms, 10000)) / 1000)
    gif = bytes.fromhex("47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b")
    return Response(gif, media_type="image/gif", headers={"Cache-Control": "no-store"})


@app.get("/api/health")
def health():
    mods = {}
    for m in ("majlis.ledger", "majlis.retrieval", "majlis.metrics", "majlis.aar", "majlis.gap_miner",
              "majlis.readiness", "majlis.engine"):
        mods[m] = importlib.util.find_spec(m) is not None
    return {"ok": True, "modules": mods, "kb_dir": str(_kb_dir().relative_to(ROOT))}


# ---------------------------------------------------------------------------
# static
# ---------------------------------------------------------------------------
@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
