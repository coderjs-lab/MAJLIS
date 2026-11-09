// Gap register: Tier 1 machine-detected candidates, Tier 2 team-verified.
import { html, useContext, Ctx, cx, useApi } from "../lib.js";
import { Empty, Loading, Label, DimChip, Quote } from "../ui.js";
import { RunHeader } from "./exercise.js";

export const PATTERNS = {
  G1_POLICY_VOID: ["G1", "Policy void"], G2_CONFLICT: ["G2", "Conflict"], G3_RESPONSIBILITY: ["G3", "Responsibility"],
  G4_CLOCK: ["G4", "Clock"], G5_STANDARDS: ["G5", "Standards"],
};

function GapRow({ g, seq, verified }) {
  const { nav } = useContext(Ctx);
  const [code, name] = PATTERNS[g.pattern] || [g.pattern || "—", ""];
  const ev = (g.evidence && g.evidence.ledger_seqs) || [];
  const cids = (g.evidence && g.evidence.clause_ids) || [];
  return html`<article class="gap">
    <div class="gap-code">
      <span class="pcode mono">${code}</span>
      <span class="pname">${name}</span>
      <span class="mono small ink3">${g.gap_id}</span>
    </div>
    <div class="gap-body">
      <div class="gap-head">
        <h3 class="gap-title">${g.title}</h3>
        <span class="chip chip-neutral">${g.type}</span>
        ${g.confidence ? html`<span class="chip chip-neutral">confidence ${g.confidence}</span>` : null}
      </div>
      <p class="gap-desc">${g.description}</p>
      <div class="gap-grid">
        <div>
          <${Label}>Evidence<//>
          <div class="chips">
            ${ev.map((s) => html`<button type="button" class="chip chip-neutral chip-btn mono" title="Open in the audit trail" onClick=${() => nav("audit", { seq: s })}>#${s}</button>`)}
            ${cids.map((c) => html`<${ClauseChip} id=${c} />`)}
            ${!ev.length && !cids.length ? html`<span class="ink3 small">none recorded</span>` : null}
          </div>
        </div>
        <div>
          <${Label}>Readiness dimensions<//>
          <div class="chips">${(g.readiness_dimensions || []).map((n) => html`<${DimChip} n=${n} />`)}</div>
        </div>
      </div>
      <div class="gap-ex">
        <${Label}>Global example<//>
        ${(g.global_examples || []).length ? g.global_examples.map((x) => html`<div class="global-ex">
            <div class="global-ex-head"><span class="chip chip-neutral mono">${x.jurisdiction}</span><span class="ink2 small">${x.instrument}</span></div>
            ${x.quote ? html`<${Quote} small text=${x.quote} clauseId=${x.clause_id} />` : null}
            <p class="small">${x.how_it_handles}</p></div>`)
          : html`<span class="box-label">Insufficient evidence</span><span class="small ink3"> No verified comparator clause was found.</span>`}
      </div>
      ${g.implication || g.next_step ? html`<div class="gap-grid">
        ${g.implication ? html`<div><${Label}>Implication<//><p>${g.implication}</p></div>` : null}
        ${g.next_step ? html`<div><${Label}>Next step<//><p>${g.next_step}</p></div>` : null}
      </div>` : null}
      ${verified && g.verified_by ? html`<div class="small ink2">Verified by ${g.verified_by}${g.verified_against ? ` against ${g.verified_against}` : ""}</div>` : null}
    </div>
  </article>`;
}

const STATUS = {
  verified: ["Verified", "chip-ok"], rejected: ["Rejected · provision found", "chip-neutral"],
  needs_more_evidence: ["Needs more evidence", "chip-warn"],
};

// Tier 2 rows come from configs/gaps_verified.yaml (team analysis against the primary text).
function VerifiedRow({ g }) {
  const [code, name] = PATTERNS[g.pattern] || [g.type === "technical" ? "TG" : "—", g.type === "technical" ? "Technical" : ""];
  const [stLabel, stTone] = STATUS[g.status] || [g.status, "chip-neutral"];
  const ev = [...(g.uae_evidence || []), ...(g.standard_evidence || [])];
  const x = g.global_example;
  return html`<article class="gap">
    <div class="gap-code">
      <span class="pcode mono">${code}</span>
      <span class="pname">${name}</span>
      <span class="mono small ink3">${g.id}${g.candidate ? ` · ${g.candidate}` : ""}</span>
    </div>
    <div class="gap-body">
      <div class="gap-head">
        <h3 class="gap-title">${g.title}</h3>
        <span class=${cx("chip", stTone)}>${stLabel}</span>
        <span class="chip chip-neutral">${g.type}</span>
      </div>
      <p class="gap-desc">${g.statement}</p>
      ${g.scope_note ? html`<p class="small ink3">${g.scope_note}</p>` : null}
      <div class="gap-grid">
        <div>
          <${Label}>Primary-text evidence<//>
          ${ev.length ? ev.map((e) => html`<${Quote} small text=${e.quote} clauseId=${e.clause_id} />`)
            : html`<span class="ink3 small">See statement (evidence is the build's access log and extraction log)</span>`}
        </div>
        <div>
          <${Label}>Readiness dimensions<//>
          <div class="chips">${(g.readiness_dimensions || []).map((n) => html`<${DimChip} n=${n} />`)}</div>
        </div>
      </div>
      <div class="gap-ex">
        <${Label}>Global example<//>
        ${x ? html`<div class="global-ex">
            <div class="global-ex-head"><span class="chip chip-neutral mono">${x.jurisdiction}</span><span class="ink2 small">${x.instrument}</span></div>
            ${x.quote ? html`<${Quote} small text=${x.quote} clauseId=${x.clause_id} />` : null}
            <p class="small">${x.how_it_handles}</p></div>`
          : html`<span class="box-label">No global example needed</span><span class="small ink3"> ${g.status === "rejected" ? "The UAE text already covers it." : "Standards gap; see the proposed extension."}</span>`}
      </div>
      ${g.implication || g.next_step ? html`<div class="gap-grid">
        ${g.implication ? html`<div><${Label}>Implication<//><p>${g.implication}</p></div>` : null}
        ${g.next_step ? html`<div><${Label}>Next step<//><p>${g.next_step}</p></div>` : null}
      </div>` : null}
    </div>
  </article>`;
}

function ClauseChip({ id }) {
  const { openClause } = useContext(Ctx);
  return html`<button type="button" class="chip chip-neutral chip-btn mono" onClick=${() => openClause(id)}>${id}</button>`;
}

export function GapsView() {
  const { model, entries } = useContext(Ctx);
  const ver = useApi("/api/gaps/verified");
  if (!entries.length) return html`<${Loading} what="Loading run" />`;
  const byPat = {};
  model.gaps.forEach(({ g }) => (byPat[g.pattern] = (byPat[g.pattern] || 0) + 1));
  const vgaps = (ver.data && ver.data.gaps) || [];
  return html`<div class="view">
    <${RunHeader} title="Gap register" />
    <div class="pattern-strip">
      ${Object.entries(PATTERNS).map(([k, [c, n]]) => html`<div class="pattern-cell"><span class="pcode mono">${c}</span><span>${n}</span><span class="tnum big-num">${byPat[k] || 0}</span></div>`)}
    </div>
    <section class="tier">
      <div class="tier-head">
        <div><span class="tier-n mono">Tier 1</span><h2 class="h2">Agent-found candidates <span class="ink3">(machine-detected)</span></h2></div>
        <p class="small ink2">Detected by code from the ledger (G1–G5). Each is a hypothesis until checked against the primary text.</p>
      </div>
      ${model.gaps.length ? model.gaps.map(({ g, seq }) => html`<${GapRow} g=${g} seq=${seq} />`)
        : html`<${Empty} title=${model.runEnd ? "No gap candidates in this run" : "Gap candidates appear when the run ends"} />`}
    </section>
    <section class="tier tier-2">
      <div class="tier-head">
        <div><span class="tier-n mono">Tier 2</span><h2 class="h2">Team-verified</h2></div>
        <p class="small ink2">Candidates the team has checked against the primary legal text.</p>
      </div>
      ${ver.data && ver.data.checked_by ? html`<p class="small ink3">Checked by ${ver.data.checked_by} · team sign-off: ${ver.data.team_signoff || "pending"} · every quote re-checked verbatim by scripts/check_gaps_verified.py</p>` : null}
      ${ver.loading ? html`<${Loading} />` : vgaps.length ? vgaps.map((g) => g.statement ? html`<${VerifiedRow} g=${g} />` : html`<${GapRow} g=${g} verified />`)
        : html`<${Empty} title="Team verification pending">Candidates are hypotheses until checked against the primary text.<//>`}
    </section>
  </div>`;
}
