// Shared presentational components.
import { html, useContext, useState, useEffect, Ctx, cx, human, api } from "./lib.js";
import { agentShort, agentName, outcome } from "./derive.js";

export const Label = ({ children, class: c }) => html`<div class=${cx("label", c)}>${children}</div>`;

export function Empty({ title, children, tone }) {
  return html`<div class=${cx("empty", tone && "empty-" + tone)}>
    <div class="empty-title">${title}</div>${children ? html`<div class="empty-body">${children}</div>` : null}
  </div>`;
}

export function Loading({ what = "Loading" }) {
  return html`<div class="loading"><span class="loading-bar"></span>${what}…</div>`;
}

// Error / pending module state
export function ApiState({ error, what }) {
  if (!error) return null;
  if (error.pending)
    return html`<${Empty} title=${`${what || "This view"} is not available yet`}>
      Waiting for <code>${error.pending}</code>. It appears here as soon as that part of the build lands.<//>`;
  return html`<${Empty} title="Could not load this data" tone="error">${String(error.message || error)}<//>`;
}

const CITE_TONE = {
  VERIFIED: "ok", NEAR_MATCH: "warn", FAILED: "bad", NOT_RETRIEVED: "bad", UNKNOWN_CLAUSE: "bad",
  UNSUPPORTED: "bad", NO_CITATION: "neutral",
};
const CITE_LABEL = {
  VERIFIED: "Verified", NEAR_MATCH: "Near match", FAILED: "Quote not found", NOT_RETRIEVED: "Not retrieved",
  UNKNOWN_CLAUSE: "Unknown clause", UNSUPPORTED: "Unsupported", NO_CITATION: "No citation",
};
const CITE_HELP = {
  VERIFIED: "The quote appears verbatim in the stored clause.",
  NEAR_MATCH: "The quote is close to the stored clause (fuzzy ≥ 90) but not exact. Not usable as a legal basis.",
  FAILED: "The quote does not appear in the cited clause.",
  NOT_RETRIEVED: "The clause exists but was not in the evidence this agent was given.",
  UNKNOWN_CLAUSE: "The cited clause id does not exist in the knowledge base.",
  UNSUPPORTED: "A legal claim with no clause or no quote.",
  NO_CITATION: "A factual or advisory statement without a citation (allowed for non-legal claims).",
};
export function CiteChip({ status }) {
  if (!status) return html`<span class="chip chip-neutral" title="Not checked">Not checked</span>`;
  return html`<span class=${`chip chip-${CITE_TONE[status] || "neutral"}`} title=${CITE_HELP[status]}>
    ${CITE_LABEL[status] || status}</span>`;
}

export function Chip({ children, tone = "neutral", title, mono, onClick }) {
  const Tag = onClick ? "button" : "span";
  return html`<${Tag} class=${cx("chip", `chip-${tone}`, mono && "mono", onClick && "chip-btn")} title=${title}
    onClick=${onClick} type=${onClick ? "button" : undefined}>${children}<//>`;
}

export function AgentTag({ id, full }) {
  const m = useContext(Ctx).model;
  const a = m && m.agentById[id];
  return html`<span class=${cx("agent-tag", full && "agent-tag-full", a && `kind-${a.kind}`)} title=${agentName(m, id)}>
    ${full ? agentName(m, id) : agentShort(m, id)}</span>`;
}

// ---- gate stamp ---------------------------------------------------------------
export function Stamp({ g, compact }) {
  const { model } = useContext(Ctx);
  const d = g.d, o = outcome(model, g);
  let label, tone;
  if (!d.enforced && d.decision !== "ALLOW") { label = `Would ${d.decision.toLowerCase()} · executed`; tone = d.decision === "DENY" ? "bad-outline" : "warn-outline"; }
  else if (d.decision === "ALLOW") { label = `ALLOW ${d.status_code}`; tone = "ok"; }
  else if (d.decision === "DENY") { label = `DENY ${d.status_code}`; tone = "bad"; }
  else { label = `ESCALATE ${d.status_code}`; tone = "warn"; }
  return html`<span class="stamp-wrap">
    <span class=${`stamp stamp-${tone}`}>${label}</span>
    ${!compact && d.decision === "ESCALATE" && d.enforced ? html`<${HumanChip} hd=${o.hd} />` : null}
  </span>`;
}

export function HumanChip({ hd }) {
  if (!hd) return html`<span class="chip chip-warn chip-pending" title="Waiting for a human decision">Awaiting human</span>`;
  const sim = (hd.approver || "").startsWith("simulated");
  const who = sim ? "simulated approver" : hd.approver === "timeout" ? "timeout" : (hd.approver || "").replace(/^human:/, "");
  return html`<span class=${`chip ${hd.decision === "approve" ? "chip-ok" : "chip-bad"}`} title=${`Approver: ${hd.approver}`}>
    Human ${hd.decision === "approve" ? "approved" : "rejected"}<span class="chip-sub">${who}</span></span>`;
}

// ---- verbatim quote -----------------------------------------------------------
export function Quote({ text, clauseId, issuer, url, small }) {
  const { openClause } = useContext(Ctx);
  return html`<figure class=${cx("quote", small && "quote-sm")}>
    <blockquote dir="auto">${text}</blockquote>
    ${clauseId || issuer ? html`<figcaption>
      ${issuer ? html`<span>${issuer}</span>` : null}
      ${clauseId ? html`<button type="button" class="clause-link mono" onClick=${() => openClause(clauseId, text)}>${clauseId}</button>` : null}
      ${url ? html`<a class="ext" href=${url} target="_blank" rel="noopener">Official source ↗</a>` : null}
    </figcaption>` : null}
  </figure>`;
}

// ---- HTTP-response gate card (403 / 202) --------------------------------------
const REASONS = { 200: "OK", 202: "Accepted — pending human approval", 403: "Policy Violation" };
export function GateCard({ g }) {
  const { model, rules } = useContext(Ctx);
  const d = g.d;
  const ruleObjs = (d.rule_ids || []).map((id) => rules && rules[id]).filter(Boolean);
  const draft = ruleObjs.some((r) => r.status === "draft");
  const o = outcome(model, g);
  const facts = Object.entries(d.state_facts || {});
  return html`<div class=${cx("httpcard", `httpcard-${d.status_code}`, !d.enforced && "httpcard-unenforced")}>
    <div class="httpcard-head mono">
      <span>${d.enforced ? "" : "Would return · "}HTTP/1.1 ${d.status_code} ${REASONS[d.status_code] || ""}</span>
      <span class="httpcard-badges">
        ${draft ? html`<span class="badge badge-draft" title="Rule not yet verified against the clause text by the team">DRAFT RULE</span>` : null}
        ${!d.enforced ? html`<span class="badge badge-bad">NOT ENFORCED</span>` : null}
      </span>
    </div>
    <dl class="httpcard-kv">
      <dt>Rule</dt><dd class="mono">${(d.rule_ids || []).join(", ") || "none matched"}</dd>
      <dt>Action</dt><dd><span class="mono">${d.action_type}</span> · <${AgentTag} id=${d.agent_id} full /></dd>
      <dt>Reason</dt><dd>${d.reason || "—"}${d.events && d.events.length ? html` · ${d.events.map((x) => html`<span class="chip chip-neutral mono">${x}</span> `)}` : null}</dd>
      ${facts.length ? html`<dt>State</dt><dd class="facts mono">${facts.map(([k, v]) => html`<span>${k}=<b>${String(v)}</b></span>`)}</dd>` : null}
      ${d.message ? html`<dt>Message</dt><dd>${d.message}</dd>` : null}
      ${d.decision === "ESCALATE" && d.enforced ? html`<dt>Human</dt><dd><${HumanChip} hd=${o.hd} /></dd>` : null}
    </dl>
    ${d.quote ? html`<${Quote} text=${d.quote} clauseId=${d.clause_id} issuer=${d.issuer} url=${d.url} />` : null}
  </div>`;
}

// ---- drawer ----------------------------------------------------------------------
export function Drawer({ title, sub, onClose, children, wide }) {
  useEffect(() => {
    const k = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  return html`<div class="drawer-scrim" onClick=${onClose}>
    <aside class=${cx("drawer", wide && "drawer-wide")} role="dialog" aria-label=${title} onClick=${(e) => e.stopPropagation()}>
      <header class="drawer-head">
        <div><div class="drawer-title">${title}</div>${sub ? html`<div class="drawer-sub">${sub}</div>` : null}</div>
        <button type="button" class="btn btn-ghost" onClick=${onClose} aria-label="Close">Close</button>
      </header>
      <div class="drawer-body">${children}</div>
    </aside>
  </div>`;
}

// Highlight the quoted span inside the stored clause text (case-insensitive exact match)
function highlight(text, quote) {
  if (!quote || !text) return text;
  const norm = (s) => s.replace(/\s+/g, " ").toLowerCase();
  const i = norm(text).indexOf(norm(quote).replace(/^["“]|["”]$/g, ""));
  if (i < 0) return text;
  const q = quote.replace(/^["“]|["”]$/g, "");
  return [text.slice(0, i), html`<mark>${text.slice(i, i + q.length)}</mark>`, text.slice(i + q.length)];
}

export function ClauseBody({ c, quote }) {
  const rtl = c.language === "ar";
  return html`<div class="clause-col" lang=${c.language} dir=${rtl ? "rtl" : "ltr"}>
    <div class="clause-col-head">
      <span class="chip chip-neutral mono">${c.language.toUpperCase()}</span>
      <span class="mono small ink3">${c.clause_id}</span>
      ${c.translation_status && c.translation_status !== "original" ? html`<span class="chip chip-warn">${human(c.translation_status)}</span>` : null}
    </div>
    ${c.heading ? html`<div class="clause-heading">${c.heading}</div>` : null}
    <p class=${cx("clause-text", rtl && "ar")}>${highlight(c.text, quote)}</p>
  </div>`;
}

export function ClauseDrawer({ id, quote, onClose }) {
  const [st, setSt] = useState({ loading: true });
  useEffect(() => {
    setSt({ loading: true });
    api(`/api/kb/clause/${id.split("/").map(encodeURIComponent).join("/")}`)
      .then((d) => setSt({ data: d })).catch((e) => setSt({ error: e }));
  }, [id]);
  const c = st.data && st.data.clause;
  return html`<${Drawer} title=${c ? c.doc_title : id} sub=${c ? [c.article && `Article ${c.article}`, c.paragraph && `para ${c.paragraph}`, c.heading].filter(Boolean).join(" · ") : null} onClose=${onClose} wide=${st.data && st.data.parallel}>
    ${st.loading ? html`<${Loading} what="Loading clause" />` : null}
    ${st.error ? (st.error.status === 404 ? html`<${Empty} title="Clause not in the knowledge base" tone="error">
        <span class="mono">${id}</span> does not exist in the stored clauses. A citation to it is reported as UNKNOWN_CLAUSE.<//>`
      : html`<${ApiState} error=${st.error} what="The clause" />`) : null}
    ${c ? html`
      <div class="clause-meta">
        <div><${Label}>Issuer<//>${c.issuer}</div>
        <div><${Label}>Jurisdiction<//><span class="mono">${c.jurisdiction}</span></div>
        <div><${Label}>Status<//><${BindingBadge} b=${c.binding} /></div>
        <div><${Label}>Instrument<//>${human(c.instrument_type)}</div>
        <div><${Label}>Retrieved<//><span class="mono">${c.retrieved_at}</span></div>
        <div><${Label}>Source hash<//><span class="mono" title=${c.source_sha256}>${(c.source_sha256 || "").slice(0, 12)}…</span></div>
      </div>
      ${c.tier === "TEST" ? html`<div class="notice">Test fixture clause — fictional text used for development, not law.</div>` : null}
      <div class=${cx("clause-parallel", st.data.parallel && "two")}>
        <${ClauseBody} c=${c} quote=${quote} />
        ${st.data.parallel ? html`<${ClauseBody} c=${st.data.parallel} />` : null}
      </div>
      ${quote ? html`<div class="drawer-section"><${Label}>Quoted by the agent<//><p class="serif quoted" dir="auto">${quote}</p>
        <p class="small ink3">Highlighted above where the quote appears verbatim in the stored text.</p></div>` : null}
      <div class="drawer-section"><a class="ext" href=${c.url} target="_blank" rel="noopener">Official source ↗</a>
        <span class="small ink3 mono"> ${c.url}</span></div>
    ` : null}
  <//>`;
}

export const BindingBadge = ({ b }) =>
  html`<span class=${cx("badge", b === "binding" ? "badge-binding" : "badge-nonbinding")}>${b === "binding" ? "Binding" : b === "non_binding" ? "Non-binding" : "Unknown"}</span>`;

// Readiness dimension chip with tooltip
export function DimChip({ n, note }) {
  const { dims } = useContext(Ctx);
  const d = dims && dims.find((x) => x.id === n);
  return html`<span class="chip chip-neutral dim" title=${d ? `${d.name}${d.description ? " — " + d.description : ""}` : `Dimension ${n}`}>
    <span class="mono">D${n}</span>${d ? html`<span class="dim-name">${d.name}</span>` : null}${note ? html`<span class="chip-sub">${note}</span>` : null}</span>`;
}

export function Collapsible({ title, children, open: o0 = false, meta }) {
  const [o, setO] = useState(o0);
  return html`<div class=${cx("collapsible", o && "open")}>
    <button type="button" class="collapsible-head" aria-expanded=${o} onClick=${() => setO(!o)}>
      <span class="caret">${o ? "▾" : "▸"}</span><span>${title}</span>${meta ? html`<span class="ink3 small mono">${meta}</span>` : null}
    </button>
    ${o ? html`<div class="collapsible-body">${children}</div>` : null}
  </div>`;
}
