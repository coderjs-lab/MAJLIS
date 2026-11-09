// Agents: one card per agent config, with downloadable agent card JSON.
import { html, useContext, Ctx, useApi, human } from "../lib.js";
import { Empty, Loading, Label, ApiState } from "../ui.js";

const KIND_ORDER = ["application", "institution", "adviser"];

function agentCard(a) {
  return {
    schema: "majlis-agent-card/1",
    note: "Simulated institutional role in a fictional exercise. Not an official position.",
    id: a.id, name: a.display_name, name_ar: a.display_name_ar, kind: a.kind, jurisdiction: a.jurisdiction,
    mandate: a.mandate, mandate_sources: a.mandate_sources || [], mandate_verified: !!(a.mandate_sources && a.mandate_sources.length),
    knowledge_slice: a.retrieval_filters || {}, retrieval_k: a.retrieval_k, can_message: a.can_message || [],
    action_vocabulary: a.action_vocabulary || [], output_language: a.output_language,
  };
}

function download(a) {
  const blob = new Blob([JSON.stringify(agentCard(a), null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const el = document.createElement("a");
  el.href = url; el.download = `${a.id}.agent-card.json`; el.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function AgentsView() {
  const { openClause } = useContext(Ctx);
  const ag = useApi("/api/config/agents", [], { cache: true });
  return html`<div class="view">
    <header class="page-head"><div><h1 class="page-title">Agents</h1>
      <div class="page-meta"><span>Each agent simulates one institutional role. It sees only its own injects and its own slice of the knowledge base, and may only propose actions from its vocabulary.</span></div></div></header>
    ${ag.loading ? html`<${Loading} />` : ag.error ? html`<${ApiState} error=${ag.error} what="Agent configuration" />` : html`
    <div class="agent-grid">${[...ag.data].sort((x, y) => KIND_ORDER.indexOf(x.kind) - KIND_ORDER.indexOf(y.kind)).map((a) => {
      const verified = a.mandate_sources && a.mandate_sources.length;
      const f = a.retrieval_filters || {};
      return html`<article class="card acfg">
        <header class="acfg-head">
          <span class="initials big">${a.short_name || a.id}</span>
          <div><div class="agent-name">${a.display_name}</div>
            ${a.display_name_ar ? html`<div class="ar" lang="ar" dir="rtl">${a.display_name_ar}</div>` : null}
            <div class="agent-sub"><span>${human(a.kind)}</span><span class="mono">${a.jurisdiction}</span><span class="mono">${a.id}</span></div></div>
        </header>
        <section><div class="acfg-row"><${Label}>Mandate<//>${verified ? html`<span class="badge badge-binding">Verified</span>` : html`<span class="badge badge-unverified">Unverified summary</span>`}</div>
          <p>${a.mandate}</p>
          ${verified ? html`<div class="chips">${a.mandate_sources.map((c) => html`<button type="button" class="chip chip-neutral chip-btn mono" onClick=${() => openClause(c)}>${c}</button>`)}</div>` : null}</section>
        <section><${Label}>Knowledge slice<//>
          <div class="chips">${Object.entries(f).filter(([, v]) => v && v.length).map(([k, v]) => html`<span class="chip chip-neutral"><span class="chip-pre">${k}</span><span class="mono">${v.join(", ")}</span></span>`)}
            ${!Object.values(f).some((v) => v && v.length) ? html`<span class="small ink3">Whole knowledge base</span>` : null}
            <span class="chip chip-neutral"><span class="chip-pre">k</span><span class="mono">${a.retrieval_k}</span></span></div></section>
        <section><${Label}>Can message<//><div class="chips">${(a.can_message || []).map((x) => html`<span class="chip chip-neutral mono">${x}</span>`)}${!(a.can_message || []).length ? html`<span class="small ink3">nobody</span>` : null}</div></section>
        <section><${Label}>Action vocabulary<//><div class="chips">${(a.action_vocabulary || []).map((x) => html`<span class="chip chip-neutral mono">${x}</span>`)}${!(a.action_vocabulary || []).length ? html`<span class="small ink3">Advises only; proposes no actions</span>` : null}</div></section>
        <footer class="acfg-foot"><button type="button" class="btn" onClick=${() => download(a)}>Download agent card (JSON)</button>
          <span class="small ink3">output ${a.output_language} · effort ${a.effort}</span></footer>
      </article>`;
    })}</div>`}
  </div>`;
}
