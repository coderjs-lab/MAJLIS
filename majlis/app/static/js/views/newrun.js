// New exercise modal: scenario, mode, approver, language, optional judge inject / challenge card.
import { html, useContext, useState, useEffect, Ctx, cx, api, useApi } from "../lib.js";
import { Label } from "../ui.js";

export function NewRunModal({ onClose }) {
  const { reloadRuns } = useContext(Ctx);
  const scen = useApi("/api/config/scenarios", [], { cache: true });
  const agents = useApi("/api/config/agents", [], { cache: true });
  const cards = useApi("/api/config/challenge_cards", [], { cache: true });
  const [f, setF] = useState({ scenario: "", mode: "governed", approver: "interactive", lang: "en" });
  const [withInj, setWithInj] = useState(false);
  const [inj, setInj] = useState({ text: "", recipients: [], kv: [["", ""]], after: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const scenarios = scen.data || [];
  const sid = f.scenario || (scenarios[0] && scenarios[0].id) || "s1_failover";
  const sc = useApi(`/api/config/scenario/${sid}`, [sid], { cache: true });
  const stages = (sc.data && sc.data.stages) || [];
  const cardList = Array.isArray(cards.data) ? cards.data : (cards.data && (cards.data.cards || cards.data.injects)) || [];

  useEffect(() => {
    const k = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, []);

  const set = (k, v) => setF({ ...f, [k]: v });
  const useCard = (id) => {
    const c = cardList.find((x) => x.id === id);
    if (!c) return;
    setWithInj(true);
    setInj({ text: c.inject_en || c.text || "", recipients: c.recipients || [],
      kv: Object.entries(c.state_changes || {}).map(([k, v]) => [k, String(v)]).concat([["", ""]]), after: c.after || "" });
  };
  const parseVal = (v) => (v === "true" ? true : v === "false" ? false : v !== "" && !isNaN(Number(v)) ? Number(v) : v);
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setErr(null);
    const body = { ...f, scenario: sid };
    if (withInj && inj.text.trim()) {
      body.inject = { text: inj.text.trim(), recipients: inj.recipients,
        state_changes: Object.fromEntries(inj.kv.filter(([k]) => k.trim()).map(([k, v]) => [k.trim(), parseVal(v.trim())])),
        after: inj.after || undefined };
    }
    try {
      const r = await api("/api/runs", { method: "POST", body: JSON.stringify(body) });
      reloadRuns && reloadRuns();
      onClose();
      location.hash = `#/exercise?run=${encodeURIComponent(r.id)}`;
    } catch (x) {
      setErr(x.pending ? `The exercise engine is not available yet (${x.pending}). Runs can be replayed from existing ledgers meanwhile.` : `Could not start the run: ${x.body && x.body.detail ? x.body.detail : x.message}`);
    }
    setBusy(false);
  };
  const Radio = ({ name, value, label, help }) => html`<label class=${cx("radio", f[name] === value && "on")}>
    <input type="radio" name=${name} value=${value} checked=${f[name] === value} onChange=${() => set(name, value)} />
    <span><b>${label}</b>${help ? html`<span class="small ink2">${help}</span>` : null}</span></label>`;
  return html`<div class="drawer-scrim modal-scrim" onClick=${onClose}>
    <form class="modal" role="dialog" aria-label="New exercise" onClick=${(e) => e.stopPropagation()} onSubmit=${submit}>
      <header class="drawer-head"><div><div class="drawer-title">New exercise</div>
        <div class="drawer-sub">Runs the scenario with the agents and the gate; the console follows it live.</div></div>
        <button type="button" class="btn btn-ghost" onClick=${onClose}>Cancel</button></header>
      <div class="modal-body">
        <div class="form-row"><${Label}>Scenario<//>
          <select class="input" value=${sid} onChange=${(e) => set("scenario", e.target.value)}>
            ${scenarios.length ? scenarios.map((s) => html`<option value=${s.id}>${s.title} (${s.n_stages} stages)</option>`) : html`<option value="s1_failover">s1_failover</option>`}
          </select></div>
        <div class="form-grid">
          <fieldset><legend class="label">Mode</legend>
            <${Radio} name="mode" value="governed" label="Governed" help="Gate decisions are enforced" />
            <${Radio} name="mode" value="ungoverned" label="Ungoverned" help="Decisions logged, not enforced" /></fieldset>
          <fieldset><legend class="label">Approver</legend>
            <${Radio} name="approver" value="interactive" label="Interactive" help="You approve or reject escalations" />
            <${Radio} name="approver" value="reject_all" label="Reject all" help="Simulated approver" />
            <${Radio} name="approver" value="approve_all" label="Approve all" help="Simulated approver" /></fieldset>
          <fieldset><legend class="label">Language</legend>
            <${Radio} name="lang" value="en" label="English" />
            <label class=${cx("radio", f.lang === "ar" && "on")}><input type="radio" name="lang" value="ar" checked=${f.lang === "ar"} onChange=${() => set("lang", "ar")} /><span><b class="ar" lang="ar">العربية</b><span class="small ink2">Arabic</span></span></label></fieldset>
        </div>
        <div class="form-row inj-toggle">
          <label class="check"><input type="checkbox" checked=${withInj} onChange=${(e) => setWithInj(e.target.checked)} /> Add a judge inject</label>
          ${cardList.length ? html`<select class="input" value="" onChange=${(e) => useCard(e.target.value)} aria-label="Challenge card">
            <option value="">Pre-fill from a challenge card…</option>${cardList.map((c) => html`<option value=${c.id}>${c.id} · ${c.title}</option>`)}</select>` : null}
        </div>
        ${withInj ? html`<div class="inj-box">
          <div class="form-row"><${Label}>Inject text<//>
            <textarea class="input serif" rows="4" dir="auto" value=${inj.text} onInput=${(e) => setInj({ ...inj, text: e.target.value })} placeholder="What happens? Write it as a briefing line, e.g. The vendor offers an untested emergency patch."></textarea></div>
          <div class="form-row"><${Label}>Delivered to<//>
            <div class="chips">${(agents.data || []).map((a) => html`<label class=${cx("check chip", inj.recipients.includes(a.id) ? "chip-on" : "chip-neutral")}>
              <input type="checkbox" checked=${inj.recipients.includes(a.id)} onChange=${(e) => setInj({ ...inj, recipients: e.target.checked ? [...inj.recipients, a.id] : inj.recipients.filter((x) => x !== a.id) })} />${a.short_name || a.id}</label>`)}</div></div>
          <div class="form-row"><${Label}>State changes<//>
            ${inj.kv.map(([k, v], i) => html`<div class="kv-row">
              <input class="input mono" placeholder="key" value=${k} onInput=${(e) => { const kv = inj.kv.map((r) => [...r]); kv[i][0] = e.target.value; if (i === kv.length - 1 && e.target.value) kv.push(["", ""]); setInj({ ...inj, kv }); }} />
              <span class="mono ink3">=</span>
              <input class="input mono" placeholder="value" value=${v} onInput=${(e) => { const kv = inj.kv.map((r) => [...r]); kv[i][1] = e.target.value; setInj({ ...inj, kv }); }} />
            </div>`)}</div>
          <div class="form-row"><${Label}>Insert after stage<//>
            <select class="input" value=${inj.after} onChange=${(e) => setInj({ ...inj, after: e.target.value })}>
              <option value="">At the end</option>${stages.map((s) => html`<option value=${s.id}>${s.id} · ${s.title || ""}</option>`)}</select></div>
        </div>` : null}
        ${err ? html`<div class="notice notice-bad">${err}</div>` : null}
      </div>
      <footer class="modal-foot"><span class="small ink3">Agents simulate institutions. Nothing produced is an official position or legal advice.</span>
        <button class="btn btn-primary" type="submit" disabled=${busy}>${busy ? "Starting…" : "Start exercise"}</button></footer>
    </form>
  </div>`;
}
