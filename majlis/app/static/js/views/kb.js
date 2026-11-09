// Knowledge base: hybrid search, filters, parallel-language clauses, stats, retrieval evaluation.
import { html, useContext, useState, useEffect, Ctx, cx, api, useApi, human, pct } from "../lib.js";
import { Empty, Loading, Label, ApiState, BindingBadge, ClauseBody } from "../ui.js";

const MODES = [["hybrid", "Hybrid"], ["dense", "Dense"], ["bm25", "BM25"]];
const EXAMPLES = ["breach notification", "data stored outside the territory", "suspend AI system patient safety", "network outage reporting", "إخطار"];

function Stats({ s }) {
  if (!s) return null;
  const langs = Object.entries(s.languages || {});
  const jur = Object.entries(s.jurisdictions || {});
  return html`<div class="stats">
    <div class="stat"><span class="stat-n tnum">${s.documents}</span><span class="stat-l">documents</span></div>
    <div class="stat"><span class="stat-n tnum">${s.clauses}</span><span class="stat-l">clauses</span></div>
    <div class="stat"><span class="stat-n tnum">${langs.length}</span><span class="stat-l">languages <span class="mono ink3">${langs.map(([k, v]) => `${k} ${v}`).join(" · ")}</span></span></div>
    <div class="stat"><span class="stat-n tnum">${jur.length}</span><span class="stat-l">jurisdictions <span class="mono ink3">${jur.map(([k]) => k).join(" ")}</span></span></div>
    <div class="stat"><span class="stat-n tnum">${s.parallel_pairs}</span><span class="stat-l">AR/EN pairs</span></div>
    ${s.is_fixture ? html`<div class="stat stat-note"><span class="badge badge-fixture">Fixture KB</span><span class="small ink2">Fictional test clauses until the real KB is built.</span></div>` : null}
  </div>`;
}

function EvalTable() {
  const ev = useApi("/api/kb/eval", [], { cache: true });
  if (ev.loading) return null;
  if (ev.error) return html`<${Empty} title="Retrieval evaluation not run yet">Results appear here once <code>kb/retrieval_eval_results.json</code> exists.<//>`;
  const d = ev.data || {};
  const src = d.by_mode || d.modes;
  const rows = Array.isArray(d) ? d : src ? ["hybrid", "dense", "bm25"].filter((k) => src[k]).map((mode) => ({ mode, ...src[mode] })) : d.results || [];
  const art = rows.some((r) => r["recall@5_article"] !== undefined);
  const f3 = (x) => (x === undefined || x === null ? "—" : Number(x).toFixed(3));
  const flagged = d.needs_team_review || rows.some((r) => r.needs_team_review);
  return html`<div>
    <table class="table eval-table">
      <thead><tr><th>Mode</th><th class="num">Recall@5</th><th class="num">MRR</th>${art ? html`<th class="num">Recall@5 (article)</th><th class="num">MRR (article)</th>` : null}</tr></thead>
      <tbody>${rows.map((r) => html`<tr><td class="mono">${r.mode}${r.mode === "dense" && d.dense_available === false ? " (unavailable)" : ""}</td>
        <td class="num tnum">${pct(r["recall@5"] ?? r.recall_at_5)}</td><td class="num tnum">${f3(r.mrr)}</td>
        ${art ? html`<td class="num tnum">${pct(r["recall@5_article"])}</td><td class="num tnum">${f3(r.mrr_article)}</td>` : null}</tr>`)}</tbody>
    </table>
    <p class="small ink2">${d.n_questions || "—"} questions${d.languages ? ` (${Object.entries(d.languages).map(([k, v]) => `${v} ${k.toUpperCase()}`).join(", ")})` : ""}.
      ${flagged ? " Questions drafted from clause text; team review pending." : ""}</p>
  </div>`;
}

export function KBView() {
  const { route } = useContext(Ctx);
  const stats = useApi("/api/kb/stats", [], { cache: true });
  const [q, setQ] = useState(route.params.q || "");
  const [mode, setMode] = useState("hybrid");
  const [jur, setJur] = useState("");
  const [bind, setBind] = useState("");
  const [lang, setLang] = useState("");
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const search = async (qq = q) => {
    if (!qq.trim()) { setRes(null); return; }
    setBusy(true); setErr(null);
    const p = new URLSearchParams({ q: qq, k: 10, mode, jurisdiction: jur, binding: bind, language: lang });
    try { setRes(await api(`/api/kb/search?${p}`)); } catch (e) { setErr(e); }
    setBusy(false);
  };
  useEffect(() => { if (q.trim()) search(); }, [mode, jur, bind, lang]);
  useEffect(() => { if (route.params.q) search(route.params.q); }, []);
  const s = stats.data;
  return html`<div class="view">
    <header class="page-head"><div><h1 class="page-title">Knowledge base</h1>
      <div class="page-meta"><span>Clause-level legal texts. Agents may cite only what is stored here; every quote is checked against it.</span></div></div></header>
    ${stats.error ? html`<${ApiState} error=${stats.error} what="The knowledge base" />` : html`<${Stats} s=${s} />`}
    <form class="kb-search" onSubmit=${(e) => { e.preventDefault(); search(); }}>
      <input class="input big" type="search" dir="auto" placeholder="Search clauses — e.g. breach notification, data localisation, إخطار" value=${q} onInput=${(e) => setQ(e.target.value)} aria-label="Search clauses" />
      <div class="seg" role="group" aria-label="Retrieval mode">${MODES.map(([k, l]) => html`<button type="button" class=${cx(mode === k && "on")} onClick=${() => setMode(k)}>${l}</button>`)}</div>
      <button class="btn btn-primary" type="submit" disabled=${busy}>${busy ? "Searching…" : "Search"}</button>
    </form>
    <div class="toolbar filters">
      <select class="input" value=${jur} onChange=${(e) => setJur(e.target.value)} aria-label="Jurisdiction"><option value="">All jurisdictions</option>${Object.keys((s && s.jurisdictions) || {}).map((j) => html`<option value=${j}>${j}</option>`)}</select>
      <select class="input" value=${bind} onChange=${(e) => setBind(e.target.value)} aria-label="Binding"><option value="">Binding and non-binding</option><option value="binding">Binding</option><option value="non_binding">Non-binding</option></select>
      <select class="input" value=${lang} onChange=${(e) => setLang(e.target.value)} aria-label="Language"><option value="">All languages</option><option value="en">English</option><option value="ar">Arabic</option></select>
      ${!res ? html`<span class="small ink3">Try: ${EXAMPLES.map((x) => html`<button type="button" class="linkish" onClick=${() => { setQ(x); search(x); }}>${x}</button> `)}</span>` : null}
    </div>
    ${err ? html`<${ApiState} error=${err} what="Search" />` : null}
    ${res ? html`<div class="kb-results">
      <div class="small ink3 results-meta">${res.results.length} results · mode <span class="mono">${res.mode}</span> · engine <span class="mono">${res.engine}</span></div>
      ${!res.results.length ? html`<${Empty} title="No clauses match">Try fewer words, the other language, or remove a filter.<//>` : null}
      ${res.results.map((r, i) => html`<article class="card kb-hit">
        <header class="kb-hit-head">
          <span class="rank mono">${i + 1}</span>
          <div class="kb-hit-title"><div class="doc">${r.doc_title}</div>
            <div class="small ink2">${[r.article && `Article ${r.article}`, r.paragraph && `para ${r.paragraph}`, r.heading].filter(Boolean).join(" · ")}</div></div>
          <div class="kb-hit-meta"><${BindingBadge} b=${r.binding} /><span class="chip chip-neutral mono">${r.jurisdiction}</span>
            <span class="chip chip-neutral">${human(r.instrument_type)}</span><span class="mono small ink3">score ${Number(r.score).toFixed(4)}</span></div>
        </header>
        <div class=${cx("clause-parallel", r.parallel && "two")}>
          <${ClauseBody} c=${r} />
          ${r.parallel ? html`<${ClauseBody} c=${r.parallel} />` : null}
        </div>
        <footer class="kb-hit-foot small"><span class="ink3">${r.issuer}</span><a class="ext" href=${r.url} target="_blank" rel="noopener">Official source ↗</a></footer>
      </article>`)}
    </div>` : null}
    <section class="section">
      <div class="section-head"><h2 class="h2">Retrieval evaluation</h2><span class="small ink3">How often the right clause is in the top 5</span></div>
      <${EvalTable} />
    </section>
  </div>`;
}
