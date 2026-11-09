// Governed vs ungoverned comparison of two runs.
import { html, useContext, useState, useEffect, useMemo, Ctx, cx, api, pct } from "../lib.js";
import { derive, agentShort } from "../derive.js";
import { Empty, Loading, Label } from "../ui.js";
import { runLabel } from "../app.js";

async function loadRun(id) {
  const [l, mm] = await Promise.all([
    api(`/api/runs/${encodeURIComponent(id)}/ledger?lite=1`),
    api(`/api/runs/${encodeURIComponent(id)}/metrics`).catch(() => null),
  ]);
  return { entries: l.entries, metrics: mm && mm.metrics };
}

function pickDefaults(runs, current) {
  const cur = runs.find((r) => r.id === current) || runs[0];
  const done = runs.filter((r) => r.status !== "failed" && r.n_entries > 0);
  const tiers = [
    done.filter((r) => r.scenario === (cur && cur.scenario) && r.fixture === (cur && cur.fixture)),
    done.filter((r) => r.scenario === (cur && cur.scenario)), done];
  for (const t of tiers) {
    const g = t.find((r) => r.mode === "governed"), u = t.find((r) => r.mode === "ungoverned");
    if (g && u) return [g.id, u.id];
  }
  return [(done.find((r) => r.mode === "governed") || {}).id, (done.find((r) => r.mode === "ungoverned") || {}).id];
}

const STAMP = (d) => !d.enforced && d.decision !== "ALLOW" ? ["Would " + d.decision.toLowerCase() + " · executed", d.decision === "DENY" ? "bad-outline" : "warn-outline"]
  : d.decision === "ALLOW" ? [`ALLOW ${d.status_code}`, "ok"] : d.decision === "DENY" ? [`DENY ${d.status_code}`, "bad"] : [`ESCALATE ${d.status_code}`, "warn"];

function Metric({ label, a, b, fmt = (x) => x, help, worse }) {
  const fa = a === undefined || a === null ? "—" : fmt(a), fb = b === undefined || b === null ? "—" : fmt(b);
  return html`<div class="metric" title=${help}>
    <div class="metric-label">${label}</div>
    <div class="metric-pair">
      <div><span class="metric-n tnum">${fa}</span><span class="metric-run">governed</span></div>
      <div class=${cx(worse && "metric-worse")}><span class="metric-n tnum">${fb}</span><span class="metric-run">ungoverned</span></div>
    </div>
  </div>`;
}

export function CompareView() {
  const { runs, runId, route } = useContext(Ctx);
  const [ids, setIds] = useState([route.params.a, route.params.b]);
  const [data, setData] = useState({});
  useEffect(() => {
    if (!runs || (ids[0] && ids[1])) return;
    const [g, u] = pickDefaults(runs, runId);
    setIds([ids[0] || g, ids[1] || u]);
  }, [runs]);
  useEffect(() => {
    ids.filter(Boolean).forEach((id) => { if (!data[id]) loadRun(id).then((d) => setData((x) => ({ ...x, [id]: d }))).catch(() => setData((x) => ({ ...x, [id]: { error: true } }))); });
  }, [ids[0], ids[1]]);
  const A = data[ids[0]], B = data[ids[1]];
  const mA = useMemo(() => A && A.entries ? derive(A.entries) : null, [A]);
  const mB = useMemo(() => B && B.entries ? derive(B.entries) : null, [B]);
  if (!runs) return html`<${Loading} />`;
  const met = (x) => (x && (x.metrics || (x.entries && derive(x.entries).metrics))) || null;
  const ma = met(A), mb = met(B);
  const g = (m, k) => m && m.gate ? m.gate[k] : null;
  const picker = (i) => html`<select class="input" value=${ids[i] || ""} onChange=${(e) => { const n = [...ids]; n[i] = e.target.value; setIds(n); }} aria-label=${i ? "Second run" : "First run"}>
    <option value="">Choose a run</option>${runs.map((r) => html`<option value=${r.id}>${runLabel(r)}${r.fixture ? " · fixture" : ""}</option>`)}</select>`;
  const stages = mA ? mA.stages : mB ? mB.stages : [];
  const key = (d) => `${d.agent_id}|${d.action_type}`;
  return html`<div class="view">
    <header class="page-head"><div><h1 class="page-title">Governed vs ungoverned</h1>
      <div class="page-meta"><span>Same scenario, same agents. The only difference: whether the gate's decision is enforced.</span></div></div></header>
    <div class="compare-pick">
      <div><${Label}>Governed run<//>${picker(0)}</div>
      <div><${Label}>Ungoverned run<//>${picker(1)}</div>
    </div>
    ${!ids[0] || !ids[1] ? html`<${Empty} title="Choose two runs to compare">Run the same scenario once governed and once ungoverned.<//>`
      : !A || !B ? html`<${Loading} what="Loading both runs" />` : html`
    <div class="metrics-row">
      <${Metric} label="Violations let through" a=${g(ma, "would_deny_let_through") || 0} b=${g(mb, "would_deny_let_through")} worse=${(g(mb, "would_deny_let_through") || 0) > (g(ma, "would_deny_let_through") || 0)}
        help="Actions the gate would deny that were executed anyway" />
      <${Metric} label="Actions blocked" a=${g(ma, "deny")} b=${g(mb, "deny")} help="DENY 403, enforced" />
      <${Metric} label="Escalated to a human" a=${g(ma, "escalate")} b=${g(mb, "escalate")} help="ESCALATE 202, enforced" />
      <${Metric} label="Unsupported claims passed as fact" a=${ma && ma.unsupported_passed_as_fact} b=${mb && mb.unsupported_passed_as_fact} worse=${mb && ma && mb.unsupported_passed_as_fact > ma.unsupported_passed_as_fact}
        help="Legal claims that were not VERIFIED but served as the legal basis of an executed action" />
      <${Metric} label="Citation verification rate" a=${ma && ma.citations && ma.citations.verification_rate} b=${mb && mb.citations && mb.citations.verification_rate} fmt=${pct}
        help="VERIFIED / all cited or legal claims" />
    </div>
    <table class="table compare-table">
      <thead><tr><th class="w-stage">Stage</th><th>Agent · action</th><th>Governed</th><th>Ungoverned</th></tr></thead>
      ${stages.map((s) => {
        const ga = mA ? (mA.byStage[s.id] || { gates: [] }).gates : [], gb = mB ? (mB.byStage[s.id] || { gates: [] }).gates : [];
        const keys = [...new Set([...ga, ...gb].map((x) => key(x.d)))];
        const cell = (list, k, m) => {
          const x = list.find((y) => key(y.d) === k);
          if (!x) return html`<span class="ink3 small">—</span>`;
          const [l, t] = STAMP(x.d); const hd = m.humanByAction[x.d.action_id];
          return html`<span class=${`stamp stamp-${t}`}>${l}</span>${hd ? html` <span class="small ink2">human ${hd.decision === "approve" ? "approved" : "rejected"}</span>` : null}`;
        };
        const stageCell = html`<td class="mono stage-cell" rowspan=${Math.max(keys.length, 1)}>${s.id}<div class="small ink2 serif">${s.title}</div></td>`;
        return html`<tbody class="compare-stage">${keys.length ? keys.map((k, i) => { const [ag, at] = k.split("|"); return html`<tr>
            ${i === 0 ? stageCell : null}
            <td><span class="small ink2">${agentShort(mA || mB, ag)}</span> <span class="mono">${at}</span></td>
            <td>${cell(ga, k, mA)}</td><td>${cell(gb, k, mB)}</td></tr>`; })
          : html`<tr>${stageCell}<td colspan="3" class="small ink3">No gate decisions</td></tr>`}</tbody>`;
      })}
    </table>`}
  </div>`;
}
