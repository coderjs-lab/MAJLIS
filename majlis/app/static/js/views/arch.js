// Architecture: ITU-T Y.3172 pipeline with MAJLIS event counts, proposed governance extension,
// and the submission template's mapping table (configs/y3172_mapping.yaml).
import { html, useContext, useState, useEffect, Ctx, cx, useApi } from "../lib.js";
import { Empty, Loading, Label, DimChip, ApiState } from "../ui.js";
import { RunHeader } from "./exercise.js";

const NODE_INFO = {
  SRC: ["Source", ["Scenario injects,", "synthetic telemetry"]],
  C: ["Collector", ["Delivers each inject", "to its recipients only"]],
  PP: ["Pre-processor", ["Clause retrieval per", "agent knowledge slice"]],
  M: ["Model", ["Agent LLM calls", "and structured turns"]],
  P: ["Policy", ["Citation check and", "policy gate decide"]],
  D: ["Distributor", ["Blackboard messages", "between agents"]],
  SINK: ["Sink", ["Executed actions,", "human decisions, gaps"]],
  MLFO: ["ML function orchestrator", ["Engine: run, stage and metrics lifecycle"]],
  LA: ["Legal applicability", ["Verbatim quote check", "against stored clause"]],
  HA: ["Human approval", ["Escalated actions", "wait for a person"]],
  AE: ["Audit evidence", ["SHA-256 hash-chained", "ledger of every event"]],
  GM: ["Gap miner", ["Policy and standards", "gaps G1–G5"]],
};
const ROW = ["SRC", "C", "PP", "M", "P", "D", "SINK"];

function Node({ id, x, y, w, h, count, ext, active, onClick, sel }) {
  const [name, cap] = NODE_INFO[id];
  return html`<g class=${cx("anode", ext && "anode-ext", active && "anode-active", sel && "anode-sel")} transform=${`translate(${x},${y})`}
      tabindex="0" role="button" aria-label=${`${id} ${name}: ${count || 0} events`} onClick=${() => onClick(id)} onKeyDown=${(e) => e.key === "Enter" && onClick(id)}>
    <rect width=${w} height=${h} rx="4" />
    <text x="12" y="22" class="an-code">${id}</text>
    <text x=${w - 12} y="22" class="an-count" text-anchor="end">${count || 0}</text>
    <text x="12" y="40" class="an-name">${name}</text>
    ${cap.map((l, i) => html`<text x="12" y=${60 + i * 15} class="an-cap">${l}</text>`)}
  </g>`;
}

function Diagram({ counts, activeNode, onPick, sel }) {
  const W = 1180, nw = 136, nh = 96, gap = 22, x0 = 40, rowY = 168;
  const xs = ROW.map((_, i) => x0 + i * (nw + gap));
  const cx_ = (id) => xs[ROW.indexOf(id)] + nw / 2;
  const extY = 330, ew = 150;
  const ext = [["LA", cx_("P") - ew - 100], ["HA", cx_("P") - ew / 2 + 30], ["AE", cx_("SINK") - ew - 20], ["GM", cx_("SINK") + 10]];
  // keep GM inside the frame
  ext[3][1] = Math.min(ext[3][1], W - 40 - ew);
  ext[2][1] = Math.min(ext[2][1], ext[3][1] - ew - 16);
  ext[1][1] = Math.min(ext[1][1], ext[2][1] - ew - 16);
  ext[0][1] = Math.min(ext[0][1], ext[1][1] - ew - 16);
  const fx = ext[0][1] - 18, fw = ext[3][1] + ew + 18 - fx;
  return html`<svg class="arch" viewBox=${`0 0 ${W} 470`} role="img" aria-label="ITU-T Y.3172 pipeline with MAJLIS mapping">
    <defs>
      <marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="arr-head" /></marker>
    </defs>
    <rect x="12" y="12" width=${W - 24} height=${446} rx="6" class="sandbox" />
    <text x="28" y="36" class="frame-label">ML Sandbox (ITU-T Y.3181)</text>
    <text x=${W - 28} y="36" class="frame-label" text-anchor="end">ITU-T Y.3172 logical pipeline</text>
    <g class=${cx("anode anode-wide", activeNode === "MLFO" && "anode-active", sel === "MLFO" && "anode-sel")} transform=${`translate(${x0},56)`} tabindex="0" role="button"
       onClick=${() => onPick("MLFO")} onKeyDown=${(e) => e.key === "Enter" && onPick("MLFO")}>
      <rect width=${xs[6] + nw - x0} height="64" rx="4" />
      <text x="12" y="24" class="an-code">MLFO</text>
      <text x="64" y="24" class="an-name">Machine learning function orchestrator</text>
      <text x="12" y="46" class="an-cap">In MAJLIS: the engine runs stages, delivers injects, records metrics and closes the run.</text>
      <text x=${xs[6] + nw - x0 - 12} y="24" class="an-count" text-anchor="end">${counts.MLFO || 0}</text>
    </g>
    ${xs.map((x) => html`<line x1=${x + nw / 2} y1="120" x2=${x + nw / 2} y2=${rowY} class="orch-line" />`)}
    ${xs.slice(0, -1).map((x) => html`<line x1=${x + nw} y1=${rowY + nh / 2} x2=${x + nw + gap - 2} y2=${rowY + nh / 2} class="flow" marker-end="url(#arr)" />`)}
    ${ROW.map((id, i) => html`<${Node} id=${id} x=${xs[i]} y=${rowY} w=${nw} h=${nh} count=${counts[id]} active=${activeNode === id} onClick=${onPick} sel=${sel === id} />`)}
    <rect x=${fx} y=${extY - 40} width=${fw} height=${nh + 58} rx="6" class="ext-frame" />
    <text x=${fx + 14} y=${extY - 20} class="frame-label ext-label">Proposed governance extension — not part of the standard</text>
    <path d=${`M${cx_("P")} ${rowY + nh} L${cx_("P")} ${extY - 40}`} class="ext-link" />
    <path d=${`M${cx_("SINK")} ${rowY + nh} L${cx_("SINK")} ${extY - 40}`} class="ext-link" />
    ${ext.map(([id, x]) => html`<${Node} id=${id} x=${x} y=${extY} w=${ew} h=${nh} count=${counts[id]} ext active=${activeNode === id} onClick=${onPick} sel=${sel === id} />`)}
  </svg>`;
}

function MappingTable({ sel }) {
  const { openClause } = useContext(Ctx);
  const mp = useApi("/api/config/y3172_mapping", [], { cache: true });
  if (mp.loading) return html`<${Loading} what="Loading mapping" />`;
  if (mp.error) return html`<${ApiState} error=${mp.error} what="The Y.3172 mapping table" />`;
  const rows = (mp.data && mp.data.rows) || [];
  if (!rows.length) return html`<${Empty} title="The mapping table is empty" />`;
  return html`<table class="table map-table">
    <thead><tr><th>Node</th><th>In this use case</th><th>AI Readiness 2.0</th><th>Documents</th></tr></thead>
    <tbody>${rows.map((r) => html`<tr id=${`map-${r.node}`} class=${cx(sel === r.node && "row-target", r.extension && "row-ext")}>
      <td><span class=${cx("node-chip mono", r.extension && "node-chip-ext")}>${r.node}</span>${r.extension ? html`<div class="small ink3">proposed extension</div>` : null}</td>
      <td><div>${r.use_case}</div>${r.majlis ? html`<div class="small ink3 mono">${r.majlis}</div>` : null}</td>
      <td><div class="chips col">${(r.readiness || []).map((d) => html`<${DimChip} n=${d.dim} note=${d.note} />`)}</div></td>
      <td><div class="doc-list">${(r.documents || []).map((d) => html`<div>
        ${d.clause_id ? html`<button type="button" class="chip chip-neutral chip-btn mono" onClick=${() => openClause(d.clause_id)}>${d.clause_id}</button>` : null}
        ${d.note ? html` <span class="small ink2">${d.note}</span>` : null}</div>`)}
        ${!(r.documents || []).length ? html`<span class="ink3 small">—</span>` : null}</div></td>
    </tr>`)}</tbody>
  </table>`;
}

export function ArchView() {
  const { model, entries, live } = useContext(Ctx);
  const [sel, setSel] = useState(null);
  const pick = (id) => {
    setSel(id);
    setTimeout(() => { const el = document.getElementById(`map-${id}`); if (el) el.scrollIntoView({ block: "center", behavior: "smooth" }); }, 30);
  };
  return html`<div class="view">
    <${RunHeader} title="Architecture: ITU-T Y.3172 lens" />
    <p class="lede">Every ledger event is tagged with the Y.3172 node it belongs to. Counts are for the selected run${live ? "; the node of the latest event is highlighted while the run is live" : ""}.
      Select a node to see its row in the mapping table.</p>
    <div class="card arch-card">
      ${entries.length ? html`<${Diagram} counts=${model.nodeCounts} activeNode=${live ? model.lastNode : null} onPick=${pick} sel=${sel} />` : html`<${Loading} />`}
      <div class="arch-legend small">
        <span><span class="lg lg-solid"></span>Y.3172 node</span>
        <span><span class="lg lg-dash"></span>Proposed extension (MAJLIS), not part of the standard</span>
        <span>Number in a node: ledger events mapped to it</span>
      </div>
    </div>
    <section class="section">
      <div class="section-head"><h2 class="h2">Mapping to the use case and AI Readiness 2.0</h2><span class="small ink3">Per node: the use-case element, the readiness dimension and the supporting documents</span></div>
      <${MappingTable} sel=${sel} />
    </section>
  </div>`;
}
