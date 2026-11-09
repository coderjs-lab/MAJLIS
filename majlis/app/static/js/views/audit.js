// Audit trail: dense ledger table, filters, entry drawer, chain verification.
import { html, useContext, useState, useEffect, useRef, useMemo, Ctx, cx, api, fmtTime } from "../lib.js";
import { nodeOf, agentShort, eventSummary } from "../derive.js";
import { Empty, Loading, Label, Drawer, Collapsible, AgentTag } from "../ui.js";
import { RunHeader } from "./exercise.js";

const EVENT_TYPES = ["run_start", "inject", "retrieval", "llm_call", "agent_turn", "citation_check", "gate_decision",
  "human_decision", "message", "stage_end", "gap_candidate", "agent_error", "metrics", "run_end"];
const PAGE = 150;

function VerifyBox() {
  const { runId, entries } = useContext(Ctx);
  const [v, setV] = useState(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try { setV(await api(`/api/runs/${encodeURIComponent(runId)}/verify`)); } catch (e) { setV({ error: String(e.message || e) }); }
    setBusy(false);
  };
  return html`<div class="verify">
    <button type="button" class="btn" onClick=${run} disabled=${busy}>${busy ? "Verifying…" : "Verify chain"}</button>
    ${v ? v.error ? html`<span class="ink-bad small">${v.error}</span>`
      : v.ok ? html`<span class="verify-ok">OK · <span class="tnum">${v.n_entries}</span> entries recomputed from genesis${v.head_hash ? html` · head <span class="mono">${v.head_hash.slice(0, 16)}</span>` : null}</span>`
      : html`<span class="verify-bad">Broken at seq <span class="mono">${v.first_broken_seq}</span> — entries after it cannot be trusted</span>`
    : html`<span class="small ink3">Recomputes sha256(prev_hash + canonical entry) for all ${entries.length} entries.</span>`}
  </div>`;
}

export function AuditView() {
  const { model, entries, route, openEntry } = useContext(Ctx);
  const [q, setQ] = useState("");
  const [actor, setActor] = useState("");
  const [et, setEt] = useState("");
  const [stage, setStage] = useState("");
  const [node, setNode] = useState("");
  const [limit, setLimit] = useState(PAGE);
  const target = route.params.seq !== undefined ? Number(route.params.seq) : null;
  const sentinel = useRef(null);

  const actors = useMemo(() => [...new Set(entries.map((e) => e.actor))], [entries.length]);
  const rows = useMemo(() => {
    const ql = q.trim().toLowerCase();
    return entries.filter((e) => (!actor || e.actor === actor) && (!et || e.event_type === et) && (!stage || e.stage === stage)
      && (!node || (e.node || nodeOf(e.event_type)) === node)
      && (!ql || JSON.stringify(e.payload).toLowerCase().includes(ql) || String(e.seq) === ql || e.hash.startsWith(ql)));
  }, [entries.length, q, actor, et, stage, node]);

  useEffect(() => {
    if (target === null) return;
    const idx = rows.findIndex((e) => e.seq === target);
    if (idx >= limit) setLimit(idx + 50);
    setTimeout(() => {
      const el = document.getElementById(`row-${target}`);
      if (el) el.scrollIntoView({ block: "center" });
    }, 60);
  }, [target, rows.length]);

  useEffect(() => {
    if (!sentinel.current) return;
    const io = new IntersectionObserver((xs) => xs.some((x) => x.isIntersecting) && setLimit((l) => l + PAGE), { rootMargin: "600px" });
    io.observe(sentinel.current);
    return () => io.disconnect();
  }, [rows.length, limit]);

  if (!entries.length) return html`<${Loading} what="Loading ledger" />`;
  const clear = () => { setQ(""); setActor(""); setEt(""); setStage(""); setNode(""); };
  return html`<div class="view">
    <${RunHeader} title="Audit trail"><${VerifyBox} /><//>
    <div class="toolbar filters">
      <input class="input search" type="search" placeholder="Search payloads, seq or hash prefix" value=${q} onInput=${(e) => setQ(e.target.value)} aria-label="Search the ledger" />
      <select class="input" value=${actor} onChange=${(e) => setActor(e.target.value)} aria-label="Actor"><option value="">All actors</option>${actors.map((a) => html`<option value=${a}>${agentShort(model, a)}</option>`)}</select>
      <select class="input" value=${et} onChange=${(e) => setEt(e.target.value)} aria-label="Event type"><option value="">All events</option>${EVENT_TYPES.map((a) => html`<option value=${a}>${a}</option>`)}</select>
      <select class="input" value=${stage} onChange=${(e) => setStage(e.target.value)} aria-label="Stage"><option value="">All stages</option>${model.stages.map((s) => html`<option value=${s.id}>${s.id}</option>`)}</select>
      <select class="input" value=${node} onChange=${(e) => setNode(e.target.value)} aria-label="Y.3172 node"><option value="">All Y.3172 nodes</option>${["SRC", "PP", "M", "P", "D", "SINK", "MLFO"].map((a) => html`<option value=${a}>${a}</option>`)}</select>
      <span class="small ink3 tnum">${rows.length} of ${entries.length}</span>
      ${q || actor || et || stage || node ? html`<button type="button" class="btn btn-ghost" onClick=${clear}>Clear</button>` : null}
    </div>
    ${!rows.length ? html`<${Empty} title="No entries match these filters" />` : html`
    <table class="table audit-table">
      <thead><tr><th class="num">Seq</th><th>Time (UTC)</th><th>Stage</th><th>Actor</th><th>Event</th><th>Node</th><th>Summary</th><th>Hash</th></tr></thead>
      <tbody>${rows.slice(0, limit).map((e) => html`<tr id=${`row-${e.seq}`} class=${cx("row-click", e.seq === target && "row-target", `ev-${e.event_type}`)}
          onClick=${() => openEntry(e.seq)} tabindex="0" onKeyDown=${(k) => k.key === "Enter" && openEntry(e.seq)}>
        <td class="num mono">${e.seq}</td>
        <td class="mono ink2">${fmtTime(e.ts)}</td>
        <td class="mono">${e.stage || ""}</td>
        <td>${["engine", "gate", "approver", "gap_miner"].includes(e.actor) ? html`<span class="ink2">${agentShort(model, e.actor)}</span>` : html`<${AgentTag} id=${e.actor} />`}</td>
        <td class="mono ev">${e.event_type}</td>
        <td><span class="node-chip mono">${e.node || nodeOf(e.event_type)}</span></td>
        <td class="summary" dir="auto">${eventSummary(model, e)}</td>
        <td class="mono ink3 hash">${e.hash.slice(0, 10)}</td>
      </tr>`)}</tbody>
    </table>
    ${rows.length > limit ? html`<div ref=${sentinel} class="more small ink3">Loading more rows…</div>` : null}`}
  </div>`;
}

export function EntryDrawer({ seq, onClose }) {
  const { runId, model, openClause } = useContext(Ctx);
  const [e, setE] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => {
    setE(null); setErr(null);
    api(`/api/runs/${encodeURIComponent(runId)}/entry/${seq}`).then(setE).catch(setErr);
  }, [seq, runId]);
  const p = e && e.payload;
  return html`<${Drawer} wide title=${e ? `#${e.seq} · ${e.event_type}` : `Entry #${seq}`} sub=${e ? `${e.stage || "run"} · ${agentShort(model, e.actor)} · ${e.ts}` : null} onClose=${onClose}>
    ${err ? html`<${Empty} title="Could not load this entry" tone="error">${String(err.message || err)}<//>` : !e ? html`<${Loading} />` : html`
      <div class="kv-grid">
        <div><${Label}>Y.3172 node<//><span class="node-chip mono">${e.node}</span> ${e.node_label && e.node_label !== e.node ? html`<span class="small ink3">${e.node_label}</span>` : null}</div>
        <div><${Label}>Hash<//><span class="mono small break">${e.hash}</span></div>
        <div><${Label}>Previous hash<//><span class="mono small break">${e.prev_hash}</span></div>
      </div>
      ${e.event_type === "retrieval" ? html`<div class="drawer-section"><${Label}>Ranked clauses for “${p.query}”<//>
        <ol class="ranked">${(p.results || []).map((r) => html`<li><button type="button" class="clause-link mono" onClick=${() => openClause(r.clause_id)}>${r.clause_id}</button>
          <span class="small">${r.doc_title}${r.article ? ` · art. ${r.article}` : ""}</span><span class="mono small ink3">${typeof r.score === "number" ? r.score.toFixed(4) : r.score}</span></li>`)}</ol>
        <div class="small ink3">Filters: <span class="mono">${JSON.stringify(p.filters || {})}</span></div></div>` : null}
      ${e.event_type === "llm_call" ? html`<div class="drawer-section">
        <div class="kv-inline small"><span>purpose <b>${p.purpose}</b></span><span>model <b class="mono">${p.model}</b></span><span>backend <b class="mono">${p.backend}</b></span>
          <span>tokens <b class="tnum">${p.usage ? `${p.usage.prompt_tokens} + ${p.usage.completion_tokens}` : "—"}</b></span><span>latency <b class="tnum">${p.latency_ms} ms</b></span><span>attempts <b>${p.attempts}</b></span></div>
        <div class="small ink3 mono">prompt sha256 ${p.prompt_sha256}</div>
        ${p.error ? html`<div class="error-line">${p.error}</div>` : null}
        <${Collapsible} title="System prompt" meta=${`${(p.system || "").length} chars`}><pre class="code" dir="auto">${p.system}</pre><//>
        <${Collapsible} title="User prompt" meta=${`${(p.user || "").length} chars`}><pre class="code" dir="auto">${p.user}</pre><//>
        <${Collapsible} title="Raw output" open meta=${`${(p.raw_output || "").length} chars`}><pre class="code" dir="auto">${p.raw_output}</pre><//>
      </div>` : null}
      <div class="drawer-section"><${Collapsible} title="Full entry (JSON)" open=${e.event_type !== "llm_call"}>
        <pre class="code json" dir="auto">${JSON.stringify(e.event_type === "llm_call" ? { ...e, payload: { ...p, system: "…", user: "…", raw_output: "…" } } : e, null, 2)}</pre><//></div>
    `}
  <//>`;
}
