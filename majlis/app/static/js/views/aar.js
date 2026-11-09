// After-Action Report: printable page rendered from Markdown with a tiny local renderer.
import { html, useContext, Ctx, useApi } from "../lib.js";
import { Loading, ApiState } from "../ui.js";

const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
function inline(s) {
  s = esc(s);
  const codes = [];
  s = s.replace(/`([^`]+)`/g, (_, c) => `\u0000${codes.push(c) - 1}\u0000`);
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>").replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>")
    .replace(/(^|\W)_([^_]+)_(?=\W|$)/g, "$1<em>$2</em>")
    .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  return s.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${codes[i]}</code>`);
}

// Headings, paragraphs, lists (ul/ol), tables, fenced code, blockquotes, hr.
export function renderMarkdown(md) {
  const lines = md.replace(/\r/g, "").split("\n");
  const out = [];
  let i = 0;
  while (i < lines.length) {
    const l = lines[i];
    if (/^```/.test(l)) {
      const buf = []; i++;
      while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]);
      i++; out.push(`<pre class="code">${esc(buf.join("\n"))}</pre>`); continue;
    }
    let m;
    if ((m = l.match(/^(#{1,6})\s+(.*)$/))) { out.push(`<h${m[1].length} dir="auto">${inline(m[2])}</h${m[1].length}>`); i++; continue; }
    if (/^\s*(-{3,}|\*{3,})\s*$/.test(l)) { out.push("<hr>"); i++; continue; }
    if (/^\|/.test(l) && i + 1 < lines.length && /^\|?\s*:?-{2,}/.test(lines[i + 1])) {
      const cells = (r) => r.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      const head = cells(l); i += 2;
      const body = [];
      while (i < lines.length && /^\|/.test(lines[i])) body.push(cells(lines[i++]));
      out.push(`<table><thead><tr>${head.map((c) => `<th>${inline(c)}</th>`).join("")}</tr></thead><tbody>${body.map((r) => `<tr>${r.map((c) => `<td dir="auto">${inline(c)}</td>`).join("")}</tr>`).join("")}</tbody></table>`);
      continue;
    }
    if (/^>\s?/.test(l)) {
      const buf = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) buf.push(lines[i++].replace(/^>\s?/, ""));
      out.push(`<blockquote dir="auto">${inline(buf.join(" "))}</blockquote>`); continue;
    }
    if (/^\s*([-*]|\d+\.)\s+/.test(l)) {
      const ordered = /^\s*\d+\./.test(l);
      const buf = [];
      while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i])) buf.push(lines[i++].replace(/^\s*([-*]|\d+\.)\s+/, ""));
      out.push(`<${ordered ? "ol" : "ul"}>${buf.map((b) => `<li dir="auto">${inline(b)}</li>`).join("")}</${ordered ? "ol" : "ul"}>`); continue;
    }
    if (!l.trim()) { i++; continue; }
    const buf = [];
    while (i < lines.length && lines[i].trim() && !/^(#|\||>|```|\s*([-*]|\d+\.)\s)/.test(lines[i])) buf.push(lines[i++]);
    out.push(`<p dir="auto">${inline(buf.join(" "))}</p>`);
  }
  return out.join("\n");
}

export function AARView() {
  const { runId } = useContext(Ctx);
  const aar = useApi(runId ? `/api/runs/${encodeURIComponent(runId)}/aar` : null, [runId]);
  return html`<div class="aar-page">
    <div class="aar-bar no-print">
      <a class="btn btn-ghost" href=${`#/exercise?run=${encodeURIComponent(runId || "")}`}>← Back to the exercise</a>
      <span class="small ink3">After-Action Report · generated from the ledger only, no model involved</span>
      <button type="button" class="btn btn-primary" onClick=${() => window.print()}>Print</button>
    </div>
    <div class="fiction-strip aar-strip"><span>Fictional exercise · Agents simulate institutions — not official positions, not legal advice</span></div>
    <article class="aar">
      <div class="aar-mark"><span class="wm-latin">MAJLIS</span><span class="wm-ar" lang="ar">مجلس</span><span class="mono small ink3">${runId}</span></div>
      ${aar.loading ? html`<${Loading} what="Loading report" />` : aar.error ? html`<${ApiState} error=${aar.error} what="The After-Action Report" />`
        : html`<div class="md" dangerouslySetInnerHTML=${{ __html: renderMarkdown(aar.data || "") }}></div>`}
    </article>
  </div>`;
}
