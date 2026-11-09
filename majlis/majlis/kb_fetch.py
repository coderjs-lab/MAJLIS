"""Plain, logged downloads for the KB build.

Rules: default httpx headers (no User-Agent spoofing), no challenge solving.
Every attempt is appended to kb/sources/access_log.csv. A 403, a 202 with an
empty body, or an HTML page where a PDF was expected is recorded as blocked and
left for the manual-download list (evidence for technical gap TG1).
"""
from __future__ import annotations

import csv
import datetime as _dt
from pathlib import Path

import ssl

import certifi
import httpx

# Some official servers (e.g. doh.gov.ae) omit their intermediate certificate.
# Browsers fetch it via the certificate's AIA "CA Issuers" URL; we do the same
# by shipping that intermediate (downloaded from the CA, GlobalSign) in
# kb/sources/extra_ca/. Verification stays fully on; nothing is disabled.
EXTRA_CA_DIR = Path(__file__).resolve().parent.parent / "kb" / "sources" / "extra_ca"


def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context(cafile=certifi.where())
    if EXTRA_CA_DIR.is_dir():
        for pem in sorted(EXTRA_CA_DIR.glob("*.pem")):
            ctx.load_verify_locations(cafile=str(pem))
    return ctx

ACCESS_LOG_FIELDS = ["ts", "doc_id", "url", "http_status", "bytes", "content_type", "result", "note"]


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log_attempt(log_path: Path, row: dict) -> None:
    new = not log_path.exists()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=ACCESS_LOG_FIELDS)
        if new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in ACCESS_LOG_FIELDS})


def fetch(url: str, dest: Path | None, *, doc_id: str, log_path: Path,
          expect: str | None = None, headers: dict | None = None,
          timeout: float = 60.0, note: str = "") -> tuple[bool, bytes | None]:
    """GET url with default client headers (plus optional content-negotiation
    headers such as Accept / Accept-Language). Returns (ok, body).

    expect: "pdf" | "html" | "xhtml" | None -- a sanity check on the body.
    """
    row = {"ts": _now(), "doc_id": doc_id, "url": url, "note": note}
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout, verify=_ssl_context()) as c:
            r = c.get(url, headers=headers or {})
    except Exception as e:  # network failure is a logged result, not a crash
        row.update(http_status="", bytes=0, content_type="", result="error",
                   note=(note + " " if note else "") + f"{type(e).__name__}: {e}"[:300])
        log_attempt(log_path, row)
        return False, None
    body = r.content
    ctype = r.headers.get("content-type", "")
    row.update(http_status=r.status_code, bytes=len(body), content_type=ctype)
    result = "ok"
    if r.status_code == 403:
        result = "blocked_403"
    elif r.status_code == 202 and len(body) < 2048:
        result = "blocked_challenge"
    elif r.status_code >= 400:
        result = f"http_{r.status_code}"
    elif expect == "pdf" and not body.startswith(b"%PDF"):
        result = "not_pdf"
    elif expect in ("html", "xhtml") and b"<" not in body[:2000]:
        result = "not_html"
    row["result"] = result
    if str(r.url) != url:
        row["note"] = (row["note"] + " " if row["note"] else "") + f"final_url={r.url}"
    log_attempt(log_path, row)
    if result != "ok":
        return False, body
    if dest is not None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
    return True, body


if __name__ == "__main__":  # probe helper: python -m majlis.kb_fetch DOC_ID URL [out] [expect]
    import sys
    doc, url = sys.argv[1], sys.argv[2]
    out = Path(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3] != "-" else None
    exp = sys.argv[4] if len(sys.argv) > 4 else None
    ok, body = fetch(url, out, doc_id=doc, log_path=Path("kb/sources/access_log.csv"), expect=exp,
                     note="probe")
    print(ok, len(body or b""), (body or b"")[:300])
