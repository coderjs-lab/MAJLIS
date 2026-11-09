// Builds a view model from ledger entries (append-only; recomputed on each poll).

export const NODES = ["SRC", "C", "PP", "M", "P", "D", "SINK", "MLFO"];
export const EXT_NODES = ["LA", "HA", "AE", "GM"];

// event -> nodes it lights (primary first). Mirrors CONTRACTS.md Y3172_NODE, with the
// proposed governance extension (LA/HA/AE/GM) counted alongside.
export const EVENT_NODES = {
  run_start: ["MLFO"], inject: ["SRC", "C"], retrieval: ["PP"], llm_call: ["M"], agent_turn: ["M"],
  citation_check: ["P", "LA"], gate_decision: ["P"], human_decision: ["SINK", "HA"], message: ["D"],
  stage_end: ["MLFO"], gap_candidate: ["SINK", "GM"], agent_error: ["M"], metrics: ["MLFO"], run_end: ["MLFO"],
};
export const nodeOf = (et) => (EVENT_NODES[et] || [""])[0];

export function derive(entries) {
  const m = {
    runStart: null, runEnd: null, metrics: null, agents: [], agentById: {}, stages: [], byStage: {},
    gates: [], humanByAction: {}, gaps: [], errors: [], lastSeq: -1, nodeCounts: {}, lastNode: null,
    turnsAll: [], entriesBySeq: {},
  };
  const stageObj = (id) => {
    if (!id) return null;
    if (!m.byStage[id]) m.byStage[id] = { id, inject: null, turns: [], gates: [], messages: [], stageEnd: null, errors: [], advice: [], citations: [] };
    return m.byStage[id];
  };
  const lastTurnOf = {}; // `${stage}|${agent}` -> turn record
  for (const e of entries) {
    m.lastSeq = Math.max(m.lastSeq, e.seq);
    m.entriesBySeq[e.seq] = e;
    for (const n of EVENT_NODES[e.event_type] || []) m.nodeCounts[n] = (m.nodeCounts[n] || 0) + 1;
    m.nodeCounts.AE = (m.nodeCounts.AE || 0) + 1;
    m.lastNode = nodeOf(e.event_type);
    const p = e.payload || {};
    const st = stageObj(e.stage);
    switch (e.event_type) {
      case "run_start":
        m.runStart = p;
        m.agents = p.agents || [];
        m.agents.forEach((a) => (m.agentById[a.id] = a));
        m.stages = (p.stages || []).map((s) => ({ ...s }));
        break;
      case "inject": {
        st.inject = { ...p, seq: e.seq };
        if (!m.stages.find((s) => s.id === e.stage))
          m.stages.push({ id: e.stage, sim_time: p.sim_time, title: p.title, recipients: p.recipients, expected: p.expected, extra: true });
        break;
      }
      case "agent_turn": {
        const rec = { seq: e.seq, stage: e.stage, agent: p.agent_id, round: p.round, turn: p.turn || {},
          evidence: p.evidence_clause_ids || [], citations: {}, citeSeq: null };
        st.turns.push(rec); m.turnsAll.push(rec);
        lastTurnOf[`${e.stage}|${p.agent_id}`] = rec;
        break;
      }
      case "citation_check": {
        const rec = lastTurnOf[`${e.stage}|${p.agent_id}`];
        const map = {};
        (p.results || []).forEach((r) => (map[r.claim_id] = r));
        if (rec && rec.citeSeq === null) { rec.citations = map; rec.citeSeq = e.seq; }
        st && st.citations.push({ seq: e.seq, agent: p.agent_id, map, counts: p.counts || {} });
        break;
      }
      case "gate_decision": {
        const g = { seq: e.seq, stage: e.stage, d: p };
        st && st.gates.push(g); m.gates.push(g);
        break;
      }
      case "human_decision":
        m.humanByAction[p.action_id] = { ...p, seq: e.seq };
        break;
      case "message":
        if (st) st.messages.push({ seq: e.seq, ts: e.ts, ...p });
        break;
      case "stage_end":
        st.stageEnd = { ...p, seq: e.seq };
        break;
      case "gap_candidate":
        m.gaps.push({ seq: e.seq, g: p });
        break;
      case "agent_error":
        m.errors.push({ seq: e.seq, stage: e.stage, ...p });
        st && st.errors.push({ seq: e.seq, ...p });
        break;
      case "metrics": m.metrics = p; break;
      case "run_end": m.runEnd = p; break;
    }
  }
  // gate decisions keyed by action
  m.gateByAction = {};
  m.gates.forEach((g) => (m.gateByAction[g.d.action_id] = g));
  // current stage = last stage with an inject
  const injected = m.stages.filter((s) => m.byStage[s.id] && m.byStage[s.id].inject);
  m.currentStage = injected.length ? injected[injected.length - 1].id : (m.stages[0] && m.stages[0].id);
  m.mode = m.runStart && m.runStart.mode;
  return m;
}

export function agentShort(m, id) {
  if (id === "gate") return "Gate";
  if (id === "engine") return "Engine";
  if (id === "approver") return "Approver";
  if (id === "gap_miner") return "Gap miner";
  const a = m && m.agentById[id];
  return (a && (a.short_name || a.display_name)) || id;
}
export function agentName(m, id) {
  const a = m && m.agentById[id];
  return (a && a.display_name) || agentShort(m, id);
}

// Outcome for one gate decision, incl. human step
export function outcome(m, g) {
  const d = g.d;
  const hd = m.humanByAction[d.action_id];
  if (!d.enforced) {
    return { kind: d.decision === "ALLOW" ? "allow" : "would", executed: true, hd };
  }
  if (d.decision === "ALLOW") return { kind: "allow", executed: true, hd };
  if (d.decision === "DENY") return { kind: "deny", executed: false, hd };
  return { kind: "escalate", executed: hd ? hd.decision === "approve" : null, hd };
}

// One-line "actual" sentence for a stage
export function actualLine(m, sid) {
  const st = m.byStage[sid];
  if (!st || !st.inject) return null;
  const parts = [];
  for (const g of st.gates) {
    const d = g.d, o = outcome(m, g);
    const who = agentShort(m, d.agent_id);
    if (!d.enforced && d.decision !== "ALLOW") parts.push(`Gate would ${d.decision === "DENY" ? "deny" : "escalate"} ${d.action_type} · executed anyway`);
    else if (d.decision === "DENY") parts.push(`Gate denied ${who}'s ${d.action_type}`);
    else if (d.decision === "ESCALATE") parts.push(`Gate escalated ${d.action_type}` + (o.hd ? ` · human ${o.hd.decision === "approve" ? "approved" : "rejected"}` : " · awaiting human"));
    else parts.push(`${who} ${d.action_type.replace(/_/g, " ")}`);
  }
  const inst = (st.stageEnd && st.stageEnd.institution_actions) || [];
  inst.slice(0, 3).forEach((a) => parts.push(`${agentShort(m, a.agent_id)} ${String(a.action_type).replace(/_/g, " ")}`));
  if (inst.length > 3) parts.push(`${inst.length - 3} more institution actions`);
  const reqs = st.messages.filter((x) => x.msg_type === "request").length;
  if (reqs) parts.push(`${reqs} request${reqs > 1 ? "s" : ""} between agents`);
  if (!parts.length) return st.turns.length ? "Agents assessed; no actions proposed" : "No agent activity yet";
  return parts.join(" · ");
}

export const n = (x) => (Array.isArray(x) ? x.length : x ?? 0);

// Plain-text gist of a blackboard message content (string or typed dict)
export function msgText(c) {
  if (c === null || c === undefined) return "";
  if (typeof c === "string") return c;
  if (c.answer && typeof c.answer === "object") return c.answer.answer_summary || c.question || "";
  if (c.answer_summary) return c.answer_summary;
  if (c.question) return c.question;
  if (c.situation_summary) return c.situation_summary;
  if (c.decision && c.action_type) return `${c.decision} ${c.status_code || ""} ${c.action_type}`.replace(/\s+/g, " ");
  if (c.decision && c.action_id) return `${c.decision} ${c.action_id}${c.approver ? " · " + c.approver : ""}`;
  return JSON.stringify(c);
}

export function eventSummary(m, e) {
  const p = e.payload || {};
  const A = (id) => agentShort(m, id);
  switch (e.event_type) {
    case "run_start": return `${p.scenario_id} · ${p.mode} · ${p.lang} · ${p.backend}/${p.model}`;
    case "inject": return `${p.title || ""} → ${(p.recipients || []).map(A).join(", ")}`;
    case "retrieval": return `“${p.query}” → ${(p.results || []).length} clauses` + (p.results && p.results[0] ? ` (top ${p.results[0].clause_id})` : "");
    case "llm_call": return `${p.purpose || "call"} · ${p.model} · ${(p.usage && (p.usage.prompt_tokens + p.usage.completion_tokens)) || 0} tok · ${p.latency_ms} ms` + (p.error ? ` · error: ${p.error}` : "");
    case "agent_turn": { const t = p.turn || {}; return `${(t.claims || []).length} claims · ${(t.proposed_actions || []).length} actions · ${(t.requests || []).length} requests`; }
    case "citation_check": return Object.entries(p.counts || {}).map(([k, v]) => `${v} ${k}`).join(" · ") || "no claims";
    case "gate_decision": return `${p.decision} ${p.status_code} ${p.action_type}` + (p.rule_ids && p.rule_ids.length ? ` · ${p.rule_ids.join(", ")}` : "") + (p.enforced ? "" : " · not enforced") + (p.events && p.events.length ? ` · ${p.events.join(", ")}` : "");
    case "human_decision": return `${p.decision} ${p.action_id} · ${p.approver}`;
    case "message": {
      const to = Array.isArray(p.to) ? p.to.map(A).join(", ") : A(p.to);
      return `${p.msg_type} ${A(p.from)} → ${to}: ${msgText(p.content)}`;
    }
    case "stage_end": return `allowed ${n(p.allowed)} · blocked ${n(p.blocked)} · escalated ${n(p.escalated)} · open requests ${n(p.open_requests)}`;
    case "gap_candidate": return `${p.gap_id} ${p.title}`;
    case "agent_error": return `${p.error} (attempts ${p.attempts})`;
    case "metrics": return `verification rate ${p.citations && p.citations.verification_rate != null ? Math.round(p.citations.verification_rate * 100) + "%" : "—"} · ${p.gaps ? p.gaps.total : 0} gaps`;
    case "run_end": return `${p.status} · ${p.duration_s}s`;
    default: return "";
  }
}
