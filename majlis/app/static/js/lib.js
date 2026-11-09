// Shared runtime: Preact + htm (vendored), fetch helpers, routing, formatting.
export { h, html, render, useState, useEffect, useMemo, useRef, useCallback, useContext, createContext }
  from "../vendor/preact-htm.module.js";
import { createContext, useState, useEffect } from "../vendor/preact-htm.module.js";

export const Ctx = createContext(null);

export class ApiError extends Error {
  constructor(status, body) {
    super(body && body.pending ? `pending: ${body.pending}` : `HTTP ${status}`);
    this.status = status; this.body = body; this.pending = body && body.pending;
  }
}

export async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  const ct = r.headers.get("content-type") || "";
  const body = ct.includes("json") ? await r.json().catch(() => null) : await r.text();
  if (!r.ok) throw new ApiError(r.status, body);
  return body;
}

const _cache = new Map();
export function cached(path) {
  if (!_cache.has(path)) _cache.set(path, api(path).catch((e) => { _cache.delete(path); throw e; }));
  return _cache.get(path);
}

// useApi: {data, error, loading}; error.pending set for 503 module-not-ready
export function useApi(path, deps = [], { cache = false } = {}) {
  const [st, setSt] = useState({ data: null, error: null, loading: !!path });
  useEffect(() => {
    if (!path) { setSt({ data: null, error: null, loading: false }); return; }
    let alive = true;
    setSt((s) => ({ ...s, loading: true }));
    (cache ? cached(path) : api(path))
      .then((d) => alive && setSt({ data: d, error: null, loading: false }))
      .catch((e) => alive && setSt({ data: null, error: e, loading: false }));
    return () => { alive = false; };
  }, [path, ...deps]);
  return st;
}

// ---- routing: #/<view>?k=v&k2=v2 ---------------------------------------
export function parseHash() {
  const raw = (location.hash || "#/exercise").slice(1);
  const [p, q] = raw.split("?");
  const view = (p || "/exercise").replace(/^\//, "") || "exercise";
  const params = Object.fromEntries(new URLSearchParams(q || ""));
  return { view, params };
}
export function hashFor(view, params = {}) {
  const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ""));
  const s = q.toString();
  return `#/${view}${s ? "?" + s : ""}`;
}
export function go(view, params) { location.hash = hashFor(view, params); }

// ---- formatting ------------------------------------------------------------
export const fmtTime = (ts) => {
  if (!ts) return "—";
  const d = new Date(ts);
  if (isNaN(d)) return ts;
  return d.toISOString().slice(11, 19);
};
export const fmtDate = (ts) => {
  if (!ts) return "—";
  const d = new Date(ts);
  if (isNaN(d)) return ts;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" }) + " " +
    d.toISOString().slice(11, 16) + " UTC";
};
export const pct = (x) => (x === null || x === undefined || isNaN(x) ? "—" : `${Math.round(x * 100)}%`);
export const human = (s) => (s || "").replace(/_/g, " ");
export const cx = (...a) => a.filter(Boolean).join(" ");
export const short = (s, n = 120) => (!s ? "" : s.length > n ? s.slice(0, n - 1) + "…" : s);
export const hasArabic = (s) => /[؀-ۿ]/.test(s || "");
