// Exercise view: stage rail, inject briefing, information asymmetry, agent cards, blackboard.
import { html, useContext, useState, Ctx, cx, human, hasArabic } from "../lib.js";
import { agentShort, agentName, actualLine, outcome, n as count, msgText } from "../derive.js";
import { Label, Empty, Loading, CiteChip, Chip, AgentTag, Stamp, GateCard, Quote, Collapsible } from "../ui.js";

export function splitTitle(t) {
  if (!t) return { fixture: false, title: "" };
  const m = t.match(/^FIXTURE\s*[—-][^·]*·\s*(.*)$/);
  return m ? { fixture: true, title: m[1] } : { fixture: false, title: t };
}

export function RunHeader({ children, title: override }) {
  const { model, run, entries } = useContext(Ctx);
  const rs = model.runStart;
  const t = splitTitle(rs ? rs.title : run && run.title);
  return html`<header class="page-head">
    <div>
      <h1 class="page-title">${override || t.title || "Exercise"}${t.fixture ? html` <span class="badge badge-fixture">Fixture</span>` : null}</h1>
      ${rs ? html`<div class="page-meta">
        <span class="mono">${rs.scenario_id}</span>
        <span>approver <b>${human(rs.approver)}</b></span>
        <span>language <b>${(rs.lang || "").toUpperCase()}</b></span>
        <span>backend <b class="mono">${rs.backend}</b></span>
        <span><span class="tnum">${entries.length}</span> ledger entries</span>
        ${model.runEnd ? html`<span>${model.runEnd.status} in <span class="tnum">${model.runEnd.duration_s}</span> s</span>` : html`<span class="ink-warn">in progress</span>`}
      </div>` : null}
    </div>
    <div class="page-actions">${children}</div>
  </header>`;
}

function defaultStage(model) {
  if (!model.runEnd) return model.currentStage;
  const deny = model.gates.find((g) => g.d.decision === "DENY");
  return (deny && deny.stage) || (model.stages[0] && model.stages[0].id);
}

function StageRail({ sel, onSel }) {
  const { model, live } = useContext(Ctx);
  return html`<ol class="rail" style=${`grid-template-columns: repeat(${model.stages.length}, minmax(0, 1fr))`}>
    ${model.stages.map((s, i) => {
      const st = model.byStage[s.id];
      const reached = st && st.inject;
      const running = live && reached && !st.stageEnd;
      const deny = st ? st.gates.filter((g) => g.d.decision === "DENY").length : 0;
      const esc = st ? st.gates.filter((g) => g.d.decision === "ESCALATE").length : 0;
      return html`<li class=${cx("rail-step", sel === s.id && "selected", !reached && "pending", running && "running")}>
        <button type="button" onClick=${() => reached && onSel(s.id)} disabled=${!reached} aria-pressed=${sel === s.id}>
          <div class="rail-top mono"><span class="rail-id">${s.id}</span><span class="rail-time">${s.sim_time}</span></div>
          <div class="rail-title">${s.title}</div>
          <div class="rail-foot">
            <span class="rail-recips">${(s.recipients || []).map((r) => html`<span class="initials" title=${agentName(model, r)}>${agentShort(model, r)}</span>`)}</span>
            <span class="rail-marks mono">
              ${deny ? html`<span class="mark mark-bad" title=${`${deny} denied`}>${deny}×403</span>` : null}
              ${esc ? html`<span class="mark mark-warn" title=${`${esc} escalated`}>${esc}×202</span>` : null}
            </span>
          </div>
          ${running ? html`<span class="rail-progress" aria-label="Stage in progress"></span>` : null}
        </button>
      </li>`;
    })}
  </ol>`;
}

function fmtVal(v) {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number" && v > 0 && v < 1) return `${Math.round(v * 1000) / 10}%`;
  return String(v);
}

function InjectCard({ st, stage }) {
  const { model } = useContext(Ctx);
  const inj = st.inject;
  const [ar, setAr] = useState(model.runStart && model.runStart.lang === "ar");
  const text = ar && inj.text_ar ? inj.text_ar : inj.text;
  const changes = Object.entries(inj.state_changes || {});
  const idx = model.stages.findIndex((s) => s.id === stage.id);
  const prevInj = idx > 0 ? (model.byStage[model.stages[idx - 1].id] || {}).inject : null;
  const prevState = (prevInj && prevInj.state_after) || (model.runStart && model.runStart.initial_state) || {};
  return html`<article class="card brief">
    <div class="brief-head">
      <${Label}>Inject · <span class="mono">${stage.id} · ${inj.sim_time}</span><//>
      <span class="brief-tags">
        ${inj.synthetic_data ? html`<span class="badge badge-synthetic" title="Telemetry in this inject is synthetic">Synthetic data</span>` : null}
        ${inj.text_ar ? html`<span class="seg" role="group" aria-label="Inject language">
          <button type="button" class=${cx(!ar && "on")} onClick=${() => setAr(false)}>EN</button>
          <button type="button" class=${cx(ar && "on", "ar")} lang="ar" onClick=${() => setAr(true)}>عربي</button></span>` : null}
      </span>
    </div>
    <h2 class="brief-title">${inj.title}</h2>
    <p class=${cx("brief-text", ar && "ar")} dir="auto" lang=${ar ? "ar" : "en"}>${text}</p>
    <div class="brief-row"><${Label}>Delivered to<//>
      <div class="chips">${(inj.recipients || []).map((r) => html`<${AgentTag} id=${r} full />`)}</div></div>
    ${changes.length ? html`<div class="brief-row"><${Label}>State change<//>
      <table class="diff mono"><tbody>${changes.map(([k, v]) => {
        const from = v && typeof v === "object" && "from" in v ? v.from : prevState[k];
        const to = v && typeof v === "object" && "to" in v ? v.to : v;
        return html`<tr><td class="diff-k">${k}</td><td class="diff-from">${fmtVal(from)}</td><td class="diff-arrow">→</td><td class="diff-to">${fmtVal(to)}</td></tr>`;
      })}</tbody></table></div>` : null}
  </article>`;
}

function ExpectedActual({ stage }) {
  const { model } = useContext(Ctx);
  const exp = stage.expected || (model.byStage[stage.id] && model.byStage[stage.id].inject && model.byStage[stage.id].inject.expected);
  return html`<div class="card ea">
    <div class="ea-row"><${Label}>Expected<//><p>${exp || html`<span class="ink3">No expectation written for this stage.</span>`}</p></div>
    <div class="ea-row"><${Label}>Actual<//><p class="ea-actual">${actualLine(model, stage.id) || html`<span class="ink3">Not reached yet.</span>`}</p></div>
  </div>`;
}

function Matrix({ sel, onSel }) {
  const { model } = useContext(Ctx);
  const cell = (agent, s) => {
    const st = model.byStage[s.id];
    if (!st || !st.inject) return "none";
    if ((st.inject.recipients || []).includes(agent)) return "inject";
    const got = st.messages.some((x) => (Array.isArray(x.to) ? x.to : [x.to]).includes(agent) && x.from !== "gate" && x.from !== "approver");
    return got ? "msg" : "none";
  };
  return html`<div class="card matrix-card">
    <div class="card-head"><${Label}>Who knew what<//></div>
    <table class="matrix">
      <thead><tr><th></th>${model.stages.map((s) => html`<th class=${cx("mono", sel === s.id && "sel")}><button type="button" onClick=${() => onSel(s.id)}>${s.id}</button></th>`)}</tr></thead>
      <tbody>${model.agents.map((a) => html`<tr>
        <th scope="row" title=${a.display_name}>${a.short_name || a.id}</th>
        ${model.stages.map((s) => { const c = cell(a.id, s); return html`<td class=${cx(sel === s.id && "sel")}>
          <span class=${`mx mx-${c}`} title=${c === "inject" ? "Received the inject" : c === "msg" ? "Received messages only" : "Nothing received"}></span></td>`; })}
      </tr>`)}</tbody>
    </table>
    <div class="legend"><span><span class="mx mx-inject"></span>Inject</span><span><span class="mx mx-msg"></span>Messages only</span><span><span class="mx mx-none"></span>Nothing</span></div>
  </div>`;
}

function ClaimRow({ c, res }) {
  return html`<li class="claim">
    <div class="claim-line">
      <${CiteChip} status=${res && res.status} />
      <span class="claim-stmt" dir="auto">${c.statement}</span>
      <span class="claim-type mono">${human(c.claim_type)}</span>
    </div>
    ${c.quote || c.clause_id ? html`<${Quote} small text=${c.quote || "(no quote given)"} clauseId=${c.clause_id} />` : null}
    ${res && res.note && res.status !== "VERIFIED" ? html`<div class="claim-note">${res.note}${res.score ? html` · <span class="mono">score ${res.score}</span>` : null}</div>` : null}
  </li>`;
}

function ActionRow({ a, agent, stage }) {
  const { model } = useContext(Ctx);
  const g = model.gateByAction[a.action_id];
  const se = model.byStage[stage] && model.byStage[stage].stageEnd;
  const inst = se && (se.institution_actions || []).some((x) => x.action_id === a.action_id);
  const showCard = g && (g.d.decision !== "ALLOW");
  return html`<li class="action">
    <div class="action-line">
      <span class="mono action-type">${a.action_type}</span>
      ${g ? html`<${Stamp} g=${g} />` : inst ? html`<span class="chip chip-neutral" title="Institutions record actions; only the system under test passes the gate">Recorded · institution action</span>`
        : html`<span class="chip chip-neutral">${se ? "Not gated" : "No gate decision yet"}</span>`}
    </div>
    <div class="action-desc" dir="auto">${a.description}
      ${a.target ? html` <span class="ink3">· target <span class="mono">${a.target}</span></span>` : null}
      ${a.urgency && a.urgency !== "unspecified" ? html` <span class="ink3">· ${a.urgency}</span>` : null}
      ${a.legal_basis_claim_ids && a.legal_basis_claim_ids.length ? html` <span class="ink3">· basis <span class="mono">${a.legal_basis_claim_ids.join(", ")}</span></span>` : null}
    </div>
    ${showCard ? (g.d.decision === "DENY" ? html`<${GateCard} g=${g} />`
      : html`<${Collapsible} title=${g.d.enforced ? "Gate response" : "What the gate would have returned"} meta=${(g.d.rule_ids || []).join(", ")}><${GateCard} g=${g} /><//>`) : null}
  </li>`;
}

function AgentCard({ t }) {
  const { model, openEntry } = useContext(Ctx);
  const a = model.agentById[t.agent] || { id: t.agent, display_name: t.agent };
  const turn = t.turn;
  const claims = turn.claims || [];
  const acts = turn.proposed_actions || [];
  return html`<article class=${cx("card agent-card", `kind-${a.kind}`)}>
    <header class="agent-head">
      <div class="agent-id">
        <span class="initials big">${a.short_name || a.id}</span>
        <div>
          <div class="agent-name">${a.display_name}</div>
          <div class="agent-sub">
            <span>${human(a.kind)}</span>
            ${a.display_name_ar ? html`<span class="ar" lang="ar" dir="rtl">${a.display_name_ar}</span>` : null}
            ${t.round > 1 ? html`<span class="mono">round ${t.round}</span>` : null}
          </div>
        </div>
      </div>
      <div class="agent-badges">
        ${a.mandate_verified === false ? html`<span class="badge badge-unverified" title=${`Mandate: ${a.mandate || ""} — written as a summary, not yet linked to a verified clause`}>Mandate: unverified summary</span>` : null}
        ${turn.confidence ? html`<span class="chip chip-neutral">confidence ${turn.confidence}</span>` : null}
        <button type="button" class="seq-link mono" onClick=${() => openEntry(t.seq)} title="Open ledger entry">#${t.seq}</button>
      </div>
    </header>
    <p class="agent-summary" dir="auto">${turn.situation_summary}</p>

    ${claims.length ? html`<section class="agent-sec"><${Label}>Claims <span class="count">${claims.length}</span><//>
      <ul class="claims">${claims.map((c) => html`<${ClaimRow} c=${c} res=${t.citations[c.claim_id]} />`)}</ul></section>` : null}

    ${acts.length ? html`<section class="agent-sec"><${Label}>Proposed actions <span class="count">${acts.length}</span><//>
      <ul class="actions">${acts.map((x) => html`<${ActionRow} a=${x} agent=${t.agent} stage=${t.stage} />`)}</ul></section>` : null}

    ${(turn.requests || []).length ? html`<section class="agent-sec"><${Label}>Requests sent<//>
      <ul class="reqs">${turn.requests.map((r) => html`<li><span class="arrow">→</span><${AgentTag} id=${r.to_agent} /><span dir="auto">${r.question}</span></li>`)}</ul></section>` : null}

    ${(turn.responsibilities_claimed || []).length || (turn.responsibilities_disclaimed || []).length ? html`<section class="agent-sec"><${Label}>Responsibilities<//>
      <div class="chips">
        ${(turn.responsibilities_claimed || []).map((d) => html`<span class="chip chip-duty" title="Claimed by this agent"><span class="chip-pre">claims</span>${human(d)}</span>`)}
        ${(turn.responsibilities_disclaimed || []).map((d) => html`<span class="chip chip-duty-no" title="Disclaimed by this agent"><span class="chip-pre">disclaims</span>${human(d)}</span>`)}
      </div></section>` : null}

    ${(turn.insufficient_evidence || []).length ? html`<section class="agent-sec"><${Label}>Insufficient evidence<//>
      ${turn.insufficient_evidence.map((x) => html`<div class="insufficient" dir="auto">${x}</div>`)}</section>` : null}

    ${(turn.uncertainties || []).length ? html`<section class="agent-sec"><${Label}>Uncertainties<//>
      <ul class="plain">${turn.uncertainties.map((x) => html`<li dir="auto">${x}</li>`)}</ul></section>` : null}
  </article>`;
}

export function AdviceBody({ c }) {
  return html`<div class="advice">
    ${c.question ? html`<div class="advice-q" dir="auto"><span class="label-inline">Q</span>${c.question}</div>` : null}
    <p class="advice-a" dir="auto">${c.answer_summary}</p>
    ${(c.claims || []).filter((x) => x.quote).map((x) => html`<${Quote} small text=${x.quote} clauseId=${x.clause_id} />`)}
    ${(c.global_examples || []).map((g) => html`<div class="global-ex">
      <div class="global-ex-head"><${Label}>Global example<//><span class="chip chip-neutral mono">${g.jurisdiction}</span><span class="ink2 small">${g.instrument}</span></div>
      ${g.quote ? html`<${Quote} small text=${g.quote} clauseId=${g.clause_id} />` : null}
      <p class="small" dir="auto">${g.how_it_handles}</p></div>`)}
    ${c.insufficient_evidence ? html`<span class="box-label">Insufficient evidence</span>` : null}
    ${(c.suspected_gaps || []).length ? html`<div class="small ink2">Suspected gaps: ${c.suspected_gaps.join("; ")}</div>` : null}
  </div>`;
}

function MessageBody({ c }) {
  if (c && typeof c === "object") {
    if (c.answer && typeof c.answer === "object") return html`<${AdviceBody} c=${{ question: c.question, ...c.answer }} />`;
    if (c.answer_summary !== undefined) return html`<${AdviceBody} c=${c} />`;
    if (c.situation_summary) return html`<div>
      <span dir="auto">${c.situation_summary}</span>
      ${(c.verified_claims || []).filter((v) => v.quote).slice(0, 2).map((v) => html`<${Quote} small text=${v.quote} clauseId=${v.clause_id} />`)}
      ${(c.proposed_actions || []).length ? html`<div class="chips t-acts">${c.proposed_actions.map((a) => html`<span class="chip chip-neutral mono">${typeof a === "string" ? a : a.action_type}</span>`)}</div>` : null}
    </div>`;
  }
  return html`<span dir="auto">${msgText(c)}</span>`;
}

function Thread({ st }) {
  const { model, openEntry } = useContext(Ctx);
  const items = st.messages;
  if (!items.length) return html`<${Empty} title="No messages in this stage" />`;
  return html`<ol class="thread">${items.map((x) => {
    const to = Array.isArray(x.to) ? x.to : [x.to];
    const sys = x.msg_type === "gate_decision" || x.msg_type === "human_decision";
    return html`<li class=${cx("thread-item", `t-${x.msg_type}`, sys && "t-sys")}>
      <button type="button" class="seq-link mono" onClick=${() => openEntry(x.seq)}>#${x.seq}</button>
      <span class=${cx("t-type", "mono")}>${human(x.msg_type)}</span>
      <span class="t-route">${sys ? html`<span class="ink3">${x.from === "gate" ? "Gate" : "Approver"}</span>` : html`<${AgentTag} id=${x.from} />`}<span class="arrow">→</span>${to.map((r) => html`<${AgentTag} id=${r} />`)}</span>
      <div class="t-body"><${MessageBody} c=${x.content} /></div>
    </li>`;
  })}</ol>`;
}

export function ExerciseView() {
  const { model, entries, route, nav, run } = useContext(Ctx);
  if (!entries.length && run && ["failed", "incomplete"].includes(run.status))
    return html`<${Empty} title="This run produced no ledger entries" tone="error">
      The engine stopped before writing anything. Its output is in <code>runs/${run.id}/console_spawn.log</code>.<//>`;
  if (!entries.length) return html`<${Loading} what=${run && ["starting", "running"].includes(run.status) ? "Starting the exercise" : "Loading run"} />`;
  const sel = route.params.stage && model.byStage[route.params.stage] ? route.params.stage : defaultStage(model);
  const stage = model.stages.find((s) => s.id === sel);
  const st = model.byStage[sel];
  const onSel = (id) => nav("exercise", { stage: id });
  const recipients = (st && st.inject && st.inject.recipients) || [];
  const silent = recipients.filter((r) => !st.turns.some((t) => t.agent === r));
  return html`<div class="view view-exercise">
    <${RunHeader}><a class="btn" href=${`#/aar?run=${encodeURIComponent(model.runStart ? entries[0].run_id : "")}`}>After-Action Report</a><//>
    <${StageRail} sel=${sel} onSel=${onSel} />
    ${!st || !st.inject ? html`<${Empty} title="This stage has not started" />` : html`
    <div class="stage-grid">
      <div class="stage-side">
        <${InjectCard} st=${st} stage=${stage} />
        <${ExpectedActual} stage=${stage} />
        <${Matrix} sel=${sel} onSel=${onSel} />
      </div>
      <div class="stage-main">
        <div class="section-head"><h2 class="h2">Agent responses</h2><span class="ink3 small">${st.turns.length} turn${st.turns.length === 1 ? "" : "s"} · ${st.gates.length} gate decision${st.gates.length === 1 ? "" : "s"}</span></div>
        ${st.turns.length ? st.turns.map((t) => html`<${AgentCard} t=${t} key=${t.seq} />`) : html`<${Empty} title="No agent has responded yet" />`}
        ${silent.length && st.stageEnd ? html`<div class="note-line">Received the inject but recorded no turn: ${silent.map((r) => html`<${AgentTag} id=${r} /> `)}</div>` : null}
        ${st.errors.map((e) => html`<div class="error-line"><span class="mono">#${e.seq}</span> <${AgentTag} id=${e.agent_id} /> agent error after ${e.attempts} attempts: <span class="mono">${e.error}</span></div>`)}
        <div class="section-head"><h2 class="h2">Blackboard</h2><span class="ink3 small">requests, advice and assessments in ${sel}</span></div>
        <${Thread} st=${st} />
        ${st.stageEnd ? html`<div class="stage-end mono">
          <span>end of ${sel}</span><span>allowed ${count(st.stageEnd.allowed)}</span><span>blocked ${count(st.stageEnd.blocked)}</span><span>escalated ${count(st.stageEnd.escalated)}</span><span>open requests ${count(st.stageEnd.open_requests)}</span>
        </div>` : null}
      </div>
    </div>`}
  </div>`;
}
