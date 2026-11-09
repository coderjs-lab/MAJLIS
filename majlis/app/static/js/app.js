// MAJLIS Exercise Console — app shell, run state and polling.
import { html, render, useState, useEffect, useMemo, useCallback, useRef, Ctx, api, parseHash, hashFor, go, fmtDate, cx } from "./lib.js";
import { derive } from "./derive.js";
import { ClauseDrawer, Empty } from "./ui.js";
import { ExerciseView } from "./views/exercise.js";
import { GateView, ApprovalTray } from "./views/gate.js";
import { GapsView } from "./views/gaps.js";
import { AuditView, EntryDrawer } from "./views/audit.js";
import { KBView } from "./views/kb.js";
import { CompareView } from "./views/compare.js";
import { ArchView } from "./views/arch.js";
import { AgentsView } from "./views/agents.js";
import { NewRunModal } from "./views/newrun.js";
import { AARView } from "./views/aar.js";

const NAV = [
  ["exercise", "Exercise"], ["compare", "Compare"], ["gate", "Policy gate"], ["gaps", "Gaps"],
  ["audit", "Audit trail"], ["kb", "Knowledge base"], ["arch", "Architecture"], ["agents", "Agents"],
];
const VIEWS = { exercise: ExerciseView, compare: CompareView, gate: GateView, gaps: GapsView, audit: AuditView,
  kb: KBView, arch: ArchView, agents: AgentsView, aar: AARView };
const RUN_FREE = new Set(["kb", "agents", "compare"]);

export const scenarioCode = (s) => (s ? (s.match(/^s(\d+)/i) ? "S" + s.match(/^s(\d+)/i)[1] : s) : "—");
export function runLabel(r) {
  if (!r) return "—";
  return `${scenarioCode(r.scenario)} · ${r.mode || "?"} · ${(r.lang || "?").toUpperCase()} · ${fmtDate(r.started)}`;
}

function useRoute() {
  const [r, setR] = useState(parseHash());
  useEffect(() => {
    const f = () => setR(parseHash());
    window.addEventListener("hashchange", f);
    return () => window.removeEventListener("hashchange", f);
  }, []);
  return r;
}

function useRuns() {
  const [runs, setRuns] = useState(null);
  const [err, setErr] = useState(null);
  const load = useCallback(() => api("/api/runs").then((d) => { setRuns(d); setErr(null); }).catch(setErr), []);
  useEffect(() => { load(); const t = setInterval(load, 6000); return () => clearInterval(t); }, [load]);
  return { runs, err, reload: load };
}

// Append-only ledger polling via ?after=<seq>
function useLedger(runId) {
  const [st, setSt] = useState({ entries: [], done: false, loading: false, error: null, runId: null });
  const ref = useRef({ id: null, last: -1, timer: null });
  useEffect(() => {
    const r = ref.current;
    clearTimeout(r.timer);
    r.id = runId; r.last = -1;
    if (!runId) { setSt({ entries: [], done: false, loading: false, error: null, runId: null }); return; }
    setSt({ entries: [], done: false, loading: true, error: null, runId });
    let alive = true;
    const tick = async () => {
      try {
        const d = await api(`/api/runs/${encodeURIComponent(runId)}/ledger?lite=1&after=${r.last}`);
        if (!alive || r.id !== runId) return;
        if (d.entries.length) r.last = d.entries[d.entries.length - 1].seq;
        setSt((s) => ({ entries: d.entries.length ? s.entries.concat(d.entries) : s.entries, done: d.done, loading: false, error: null, runId }));
        if (!d.done) r.timer = setTimeout(tick, 1500);
      } catch (e) {
        if (!alive) return;
        setSt((s) => ({ ...s, loading: false, error: e }));
        r.timer = setTimeout(tick, 4000);
      }
    };
    tick();
    return () => { alive = false; clearTimeout(r.timer); };
  }, [runId]);
  return st;
}

function ChainPill({ runId, n, done }) {
  const [v, setV] = useState(null);
  useEffect(() => {
    setV(null);
    if (!runId) return;
    api(`/api/runs/${encodeURIComponent(runId)}/verify`).then(setV).catch(() => setV({ error: true }));
  }, [runId, done, done ? 0 : Math.floor(n / 25)]);
  if (!runId) return null;
  if (!v) return html`<span class="pill pill-neutral mono">Verifying chain…</span>`;
  if (v.error) return html`<span class="pill pill-neutral">Chain status unavailable</span>`;
  return v.ok
    ? html`<button type="button" class="pill pill-ok" title=${`SHA-256 hash chain verified from genesis${v.head_hash ? " · head " + v.head_hash.slice(0, 12) : ""}`} onClick=${() => go("audit", { run: runId })}>
        <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="M2 6.5l2.5 2.5L10 3.5" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>
        Chain verified · <span class="tnum">${v.n_entries}</span> entries</button>`
    : html`<button type="button" class="pill pill-bad" onClick=${() => go("audit", { run: runId })}>Chain broken at seq ${v.first_broken_seq}</button>`;
}

function Wordmark() {
  return html`<a class="wordmark" href="#/exercise">
    <span class="wm-latin">MAJLIS</span><span class="wm-ar" lang="ar">مجلس</span><span class="wm-sub">Exercise Console</span></a>`;
}

function App() {
  const route = useRoute();
  const { runs, err: runsErr, reload } = useRuns();
  const [clause, setClause] = useState(null);
  const [entrySeq, setEntrySeq] = useState(null);
  const [newOpen, setNewOpen] = useState(false);
  const [rules, setRules] = useState(null);
  const [dims, setDims] = useState(null);

  useEffect(() => {
    api("/api/config/rules").then((d) => {
      const m = {}; ((d && d.rules) || []).forEach((r) => (m[r.rule_id] = r)); setRules(m);
    }).catch(() => setRules({}));
    api("/api/readiness/dimensions").then(setDims).catch(() => setDims([]));
  }, []);

  // deep links: &clause=<id> opens the clause drawer, &entry=<seq> the ledger entry drawer
  useEffect(() => {
    if (route.params.clause) setClause({ id: route.params.clause, quote: route.params.quote });
    if (route.params.entry !== undefined) setEntrySeq(Number(route.params.entry));
    if (route.params.new) setNewOpen(true);
  }, [route.params.clause, route.params.entry, route.params.new]);

  // resolve run id: hash > last used > newest
  let runId = route.params.run;
  if (!runId && runs && runs.length) {
    let saved = null; try { saved = localStorage.getItem("majlis.run"); } catch (e) { /* ignore */ }
    runId = (saved && runs.find((r) => r.id === saved)) ? saved : runs[0].id;
  }
  useEffect(() => { if (runId) try { localStorage.setItem("majlis.run", runId); } catch (e) { /* ignore */ } }, [runId]);

  const ledger = useLedger(runId);
  const model = useMemo(() => derive(ledger.entries), [ledger.entries]);
  const run = runs && runs.find((r) => r.id === runId);
  const live = !!runId && !ledger.done && !ledger.loading && (run ? ["running", "starting"].includes(run.status) : true);

  const ctx = {
    runs, runId, run, model, entries: ledger.entries, done: ledger.done, live, rules, dims, route,
    reloadRuns: reload,
    openClause: (id, quote) => setClause({ id, quote }),
    openEntry: (seq) => setEntrySeq(seq),
    setRun: (id) => go(route.view === "aar" ? "aar" : route.view, { run: id }),
    nav: (view, params = {}) => go(view, { run: runId, ...params }),
  };

  const View = VIEWS[route.view] || ExerciseView;
  if (route.view === "aar") {
    return html`<${Ctx.Provider} value=${ctx}><${AARView} />
      ${clause ? html`<${ClauseDrawer} id=${clause.id} quote=${clause.quote} onClose=${() => setClause(null)} />` : null}<//>`;
  }
  const mode = model.mode || (run && run.mode);
  return html`<${Ctx.Provider} value=${ctx}>
    <div class="shell">
      <header class="topbar">
        <${Wordmark} />
        <div class="topbar-run">
          <label class="label" for="run-picker">Run</label>
          <select id="run-picker" class="run-picker mono-num" value=${runId || ""} onChange=${(e) => ctx.setRun(e.target.value)} disabled=${!runs || !runs.length}>
            ${!runs ? html`<option>Loading runs…</option>` : runs.length === 0 ? html`<option>No runs yet</option>` : null}
            ${(runs || []).map((r) => html`<option value=${r.id}>${runLabel(r)}${r.fixture ? " · fixture" : ""}${r.status === "running" ? " · live" : ""}</option>`)}
          </select>
          ${mode ? html`<span class=${cx("mode-chip", mode === "governed" ? "mode-gov" : "mode-ungov")}
            title=${mode === "governed" ? "Gate decisions are enforced" : "Gate decisions are computed and logged but not enforced"}>${mode.toUpperCase()}</span>` : null}
          ${live ? html`<span class="live-chip"><span class="live-dot"></span>Live</span>` : null}
          <${ChainPill} runId=${runId} n=${ledger.entries.length} done=${ledger.done} />
        </div>
        <button type="button" class="btn btn-primary" onClick=${() => setNewOpen(true)}>New exercise</button>
      </header>
      <div class="fiction-strip">
        <span>Fictional exercise · Agents simulate institutions — not official positions, not legal advice</span>
        <span class="sep" aria-hidden="true"></span>
        <span lang="ar" dir="rtl" class="ar">تمرين افتراضي · الوكلاء يحاكون أدواراً مؤسسية — ليست مواقف رسمية ولا استشارة قانونية</span>
      </div>
      <div class="body">
        <nav class="sidenav" aria-label="Views">
          ${NAV.map(([id, label]) => html`<a href=${hashFor(id, RUN_FREE.has(id) ? {} : { run: runId })}
            class=${cx("nav-item", route.view === id && "active")} aria-current=${route.view === id ? "page" : undefined}>${label}</a>`)}
          <div class="nav-foot">
            ${run && run.fixture ? html`<div class="nav-note">Viewing a fixture run: synthetic data for UI development.</div>` : null}
            <div class="nav-note mono">${model.runStart ? `${model.runStart.backend} · ${model.runStart.model}` : ""}</div>
            <div class="nav-note">ITU AI for Good Lab Hackathon · UAE 2026<br />Abhra Dubey (lead) · Harmanjot Singh · Aya Elsayed</div>
          </div>
        </nav>
        <main class="main" id="main">
          ${runsErr ? html`<${Empty} title="The console server is not responding" tone="error">Check that the server is running, then reload.<//>` : null}
          ${!RUN_FREE.has(route.view) && runs && runs.length === 0 ? html`<${Empty} title="No runs yet">
              Start an exercise with <b>New exercise</b>, or generate the fixtures with
              <code>.venv/bin/python tests/fixtures/make_console_fixture.py</code>.<//>`
            : html`<${View} key=${route.view} />`}
        </main>
      </div>
      ${live ? html`<${ApprovalTray} />` : null}
      ${clause ? html`<${ClauseDrawer} id=${clause.id} quote=${clause.quote} onClose=${() => setClause(null)} />` : null}
      ${entrySeq !== null ? html`<${EntryDrawer} seq=${entrySeq} onClose=${() => setEntrySeq(null)} />` : null}
      ${newOpen ? html`<${NewRunModal} onClose=${() => setNewOpen(false)} />` : null}
    </div>
  <//>`;
}

render(html`<${App} />`, document.getElementById("app"));
