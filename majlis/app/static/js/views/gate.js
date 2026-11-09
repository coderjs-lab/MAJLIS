// Policy gate view + pending-approval tray.
import { html, useContext, useState, Ctx, cx, api } from "../lib.js";
import { outcome } from "../derive.js";
import { Empty, Loading, Stamp, GateCard, AgentTag, HumanChip } from "../ui.js";
import { RunHeader } from "./exercise.js";

const FILTERS = [["all", "All"], ["DENY", "Denied"], ["ESCALATE", "Escalated"], ["ALLOW", "Allowed"], ["unenforced", "Not enforced"]];

function factCells(sf) {
  const f = Object.entries(sf || {}).filter(([, v]) => v !== false && v !== null).slice(0, 3);
  return f.length ? f.map(([k, v]) => html`<span>${k}=${String(v)}</span>`) : html`<span class="ink3">—</span>`;
}

export function GateView() {
  const { model, entries, rules } = useContext(Ctx);
  const [f, setF] = useState("all");
  const [open, setOpen] = useState(() => new Set(model.gates.filter((g) => g.d.decision === "DENY").slice(0, 1).map((g) => g.seq)));
  if (!entries.length) return html`<${Loading} what="Loading run" />`;
  const rows = model.gates.filter((g) => f === "all" ? true : f === "unenforced" ? !g.d.enforced && g.d.decision !== "ALLOW" : g.d.decision === f);
  const count = (k) => model.gates.filter((g) => k === "all" ? true : k === "unenforced" ? !g.d.enforced && g.d.decision !== "ALLOW" : g.d.decision === k).length;
  const toggle = (seq) => { const s = new Set(open); s.has(seq) ? s.delete(seq) : s.add(seq); setOpen(s); };
  return html`<div class="view">
    <${RunHeader} title="Policy gate" />
    <p class="lede">Every action an agent proposes passes the gate. The gate reads scenario state, not model claims, and
      decides <span class="stamp stamp-ok sm">ALLOW 200</span> <span class="stamp stamp-bad sm">DENY 403</span> or
      <span class="stamp stamp-warn sm">ESCALATE 202</span> to a human. In an ungoverned run the same decision is computed and logged, then ignored.</p>
    <div class="toolbar">
      <div class="seg" role="group" aria-label="Filter by decision">
        ${FILTERS.map(([k, l]) => html`<button type="button" class=${cx(f === k && "on")} onClick=${() => setF(k)}>${l} <span class="tnum ink3">${count(k)}</span></button>`)}
      </div>
    </div>
    ${!rows.length ? html`<${Empty} title="No gate decisions match this filter" />` : html`
    <table class="table gate-table">
      <thead><tr><th class="w-stage">Stage</th><th>Action</th><th>Agent</th><th>State facts</th><th>Rule</th><th>Decision</th><th>Enforced</th></tr></thead>
      <tbody>${rows.map((g) => {
        const d = g.d, o = outcome(model, g), isOpen = open.has(g.seq);
        const draft = (d.rule_ids || []).some((r) => rules && rules[r] && rules[r].status === "draft");
        return html`
        <tr class=${cx("row-click", isOpen && "row-open")} onClick=${() => toggle(g.seq)} tabindex="0" onKeyDown=${(e) => e.key === "Enter" && toggle(g.seq)}>
          <td class="mono">${g.stage}</td>
          <td><span class="mono">${d.action_type}</span></td>
          <td><${AgentTag} id=${d.agent_id} /></td>
          <td class="facts-cell mono">${factCells(d.state_facts)}</td>
          <td class="mono">${(d.rule_ids || []).join(", ") || html`<span class="ink3">${(d.events || []).join(", ") || "—"}</span>`}${draft ? html` <span class="badge badge-draft sm">draft</span>` : null}</td>
          <td><${Stamp} g=${g} /></td>
          <td>${d.enforced ? "Enforced" : html`<span class="ink-bad">Would have · let through</span>`}</td>
        </tr>
        ${isOpen ? html`<tr class="row-detail"><td></td><td colspan="6"><${GateCard} g=${g} /></td></tr>` : null}`;
      })}</tbody>
    </table>`}
  </div>`;
}

// Sticky tray for interactive runs: escalations awaiting a human.
export function ApprovalTray() {
  const { model, runId, run } = useContext(Ctx);
  const [sent, setSent] = useState({});
  const [err, setErr] = useState(null);
  if (!model.runStart || model.runStart.approver !== "interactive") return null;
  const pending = model.gates.filter((g) => g.d.enforced && g.d.decision === "ESCALATE" && !model.humanByAction[g.d.action_id]);
  if (!pending.length) return null;
  const decide = async (g, decision) => {
    setSent((s) => ({ ...s, [g.d.action_id]: "sending" }));
    try {
      await api(`/api/runs/${encodeURIComponent(runId)}/approvals/${encodeURIComponent(g.d.action_id)}`, {
        method: "POST", body: JSON.stringify({ decision, by: "exercise-controller" }) });
      setSent((s) => ({ ...s, [g.d.action_id]: decision }));
    } catch (e) { setErr(String(e.message || e)); setSent((s) => ({ ...s, [g.d.action_id]: null })); }
  };
  return html`<aside class="tray" aria-label="Pending approvals">
    <div class="tray-head"><span class="label">Awaiting human approval</span><span class="tnum mono">${pending.length}</span></div>
    ${pending.map((g) => html`<div class="tray-item">
      <div><span class="mono">${g.stage}</span> · <${AgentTag} id=${g.d.agent_id} /> <span class="mono">${g.d.action_type}</span></div>
      <div class="small ink2">${g.d.message || g.d.reason}</div>
      <div class="tray-actions">
        ${sent[g.d.action_id] && sent[g.d.action_id] !== "sending"
          ? html`<span class="small ink2">Sent: ${sent[g.d.action_id]}. Waiting for the engine to record it.</span>`
          : html`<button type="button" class="btn btn-ok" disabled=${sent[g.d.action_id] === "sending"} onClick=${() => decide(g, "approve")}>Approve</button>
                 <button type="button" class="btn btn-bad" disabled=${sent[g.d.action_id] === "sending"} onClick=${() => decide(g, "reject")}>Reject</button>`}
      </div>
    </div>`)}
    ${err ? html`<div class="small ink-bad">${err}</div>` : null}
  </aside>`;
}
