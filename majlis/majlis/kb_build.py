"""Parsers and clause splitter for the MAJLIS knowledge base.

Input: official files under kb/raw (EU Cellar XHTML, PDFs, official HTML pages).
Output: `Clause` records. Clause `text` is the extracted text with only
whitespace normalisation of line wraps (and a small, logged table of PDF
font-encoding repairs such as the "fi" ligature). Nothing is reworded.

Units:
  * laws  -> article markers (EN "Article n" / "Article (n)", AR "المادة" + number
             or ordinal word), then numbered paragraphs ("1.", "(a)", Arabic letters)
  * EU XHTML -> <div id="art_N"> containers, paragraphs <div id="NNN.MMM">
  * standards / frameworks / guidance PDFs -> numbered headings (sequence-checked)
             and font-size headings; section number kept as `article`.
Target 50-400 words; chunks break only at paragraph or sentence boundaries.
"""
from __future__ import annotations

import collections
import re
import statistics
import unicodedata
import warnings
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------
MIN_WORDS = 50
MAX_WORDS = 400
HARD_MAX = 520           # a merged unit may exceed MAX_WORDS a little rather than split mid-thought

# PDF font-encoding repairs (glyph -> printed characters). Logged in stats.
LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl"}
# Some PDFs map the "Th" ligature glyph to U+0407 (Cyrillic YI). Only applied per doc.
TH_LIGATURE = {"Ї": "Th"}

ARABIC_RE = re.compile(r"[؀-ۿ]")
HEAD_END = re.compile(r"[.;!?\u061f]\s*$")
SENT_END = re.compile(r"[.;:!?)\]\"”؟،]\s*$")


def words(s: str) -> int:
    return len(s.split())


def norm_ws(s: str) -> str:
    """Whitespace normalisation only (line wraps, NBSP, runs of spaces)."""
    s = s.replace(" ", " ").replace("\t", " ")
    s = re.sub(r"[  -  ]+", " ", s)
    s = re.sub(r" *\n *", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def join_lines(lines: list[str]) -> str:
    """Join PDF line-wraps of one paragraph into a single line."""
    out = ""
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        if not out:
            out = ln
        elif out.endswith("-") and not out.endswith(" -") and ln[:1].islower():
            out = out + ln          # hyphenated line wrap: keep the hyphen, drop the break
        else:
            out = out + " " + ln
    return out


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?;؟])\s+(?=[A-Z0-9(\"“؀-ۿ])", text)
    return [p for p in parts if p.strip()]


def chunk_paragraphs(paras: list[str], max_words: int = MAX_WORDS) -> list[str]:
    """Group paragraphs into chunks <= max_words; split an oversize paragraph at
    sentence boundaries only."""
    pieces: list[str] = []
    for p in paras:
        if words(p) > max_words:
            pieces.extend(split_sentences(p))
        else:
            pieces.append(p)
    chunks: list[list[str]] = []
    cur: list[str] = []
    n = 0
    for p in pieces:
        w = words(p)
        if cur and n + w > max_words:
            chunks.append(cur)
            cur, n = [], 0
        cur.append(p)
        n += w
    if cur:
        chunks.append(cur)
    # avoid a tiny trailing chunk: fold it back if that stays under HARD_MAX
    if len(chunks) > 1 and sum(words(x) for x in chunks[-1]) < MIN_WORDS:
        tail = chunks.pop()
        if sum(words(x) for x in chunks[-1]) + sum(words(x) for x in tail) <= HARD_MAX:
            chunks[-1].extend(tail)
        else:
            chunks.append(tail)
    return ["\n".join(c) for c in chunks]


# ---------------------------------------------------------------------------
# Arabic quality checks
# ---------------------------------------------------------------------------
_AR_WORD = re.compile(r"[ء-ي٠-٩ﭐ-﻿]+")
_BROKEN_LAMALEF = re.compile(r"^ا[إأآا]ل")      # "اإل" for "الإ" etc. (lam-alef ligature emitted in wrong order)


def arabic_quality(text: str) -> tuple[bool, str]:
    """Return (ok, reason). Detects reversed text, broken lam-alef joins and
    presentation-form output from PDF extraction."""
    ws = _AR_WORD.findall(text)
    if len(ws) < 5:
        return False, "no_arabic_text"
    pres = sum(1 for c in text if "ﭐ" <= c <= "﻿")
    letters = sum(1 for c in text if ARABIC_RE.match(c)) + pres
    if letters and pres / letters > 0.2:
        return False, "presentation_forms"
    starts_al = sum(1 for w in ws if w.startswith("ال"))
    ends_la = sum(1 for w in ws if w.endswith("لا") and len(w) > 3)
    if ends_la > max(3, starts_al):
        return False, "reversed_text"
    broken = sum(1 for w in ws if _BROKEN_LAMALEF.match(w))
    if broken >= 3 and broken / max(1, starts_al + broken) > 0.03:
        return False, "broken_lam_alef"
    return True, "ok"


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------
@dataclass
class Unit:
    kind: str                    # "art" | "sec"
    article: str                 # "33", "3.1.2", "annex-III", "s12"
    paragraph: str | None
    heading: str | None
    text: str
    page: int | None = None
    id_suffix: str = ""          # chunk/disambiguation suffix

    def id_core(self) -> str:
        if self.kind == "art":
            core = f"art-{self.article}"
            if self.paragraph:
                core += f"/para-{self.paragraph}"
        else:
            core = f"sec-{self.article}"
            if self.paragraph:
                core += f"-{self.paragraph}"
        return core + self.id_suffix


def _safe(s: str) -> str:
    s = re.sub(r"[\s/]+", "-", s.strip())
    return re.sub(r"[^0-9A-Za-z.\-؀-ۿ]", "", s)


# ---------------------------------------------------------------------------
# EU XHTML (Cellar)
# ---------------------------------------------------------------------------
def _el_text(el) -> str:
    """Text of an XHTML element: table rows -> one line, cells space-joined."""
    from bs4 import NavigableString, Tag
    if isinstance(el, NavigableString):
        return norm_ws(str(el))
    if el.name == "table":
        rows = []
        for tr in el.find_all("tr"):
            cells = [norm_ws(td.get_text(" ", strip=True)) for td in tr.find_all("td", recursive=False)]
            rows.append(" ".join(c for c in cells if c))
        return "\n".join(r for r in rows if r)
    if el.name in ("p", "span"):
        return norm_ws(el.get_text(" ", strip=True))
    parts = []
    for c in el.children:
        if isinstance(c, Tag) or (isinstance(c, NavigableString) and str(c).strip()):
            t = _el_text(c)
            if t:
                parts.append(t)
    return "\n".join(parts)


def _block_texts(container, skip_ids=()) -> list[tuple[str | None, str]]:
    """Return [(para_id_or_None, text)] for direct children."""
    from bs4 import Tag
    out = []
    for c in container.children:
        if not isinstance(c, Tag):
            continue
        cls = c.get("class") or []
        if "oj-ti-art" in cls or "eli-title" in cls or c.get("id") in skip_ids:
            continue
        if "oj-doc-ti" in cls:
            continue
        t = _el_text(c)
        if not t:
            continue
        cid = c.get("id") or ""
        m = re.fullmatch(r"\d{3}\.(\d{3})", cid)
        out.append((str(int(m.group(1))) if m else None, t))
    return out


def parse_eu_xhtml(path: Path) -> list[Unit]:
    from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "lxml")
    units: list[Unit] = []
    for art in soup.find_all("div", id=re.compile(r"^art_\d+[a-z]?$")):
        n = art["id"][4:]
        sti = art.find("p", class_="oj-sti-art")
        heading = norm_ws(sti.get_text(" ", strip=True)) if sti else None
        title = art.find("p", class_="oj-ti-art")
        title_t = norm_ws(title.get_text(" ", strip=True)) if title else f"Article {n}"
        blocks = _block_texts(art)
        numbered = [b for b in blocks if b[0]]
        if numbered:
            # intro fragments before the first numbered paragraph join the first paragraph
            cur_pid, cur_txt, pre = None, [], []
            groups: list[tuple[str, list[str]]] = []
            for pid, t in blocks:
                if pid:
                    groups.append((pid, [t]))
                elif groups:
                    groups[-1][1].append(t)
                else:
                    pre.append(t)
            if pre:
                groups[0] = (groups[0][0], pre + groups[0][1])
            for pid, ts in groups:
                units.extend(_eu_para_units(n, pid, heading, ts))
        else:
            # unnumbered article: intro + points (tables). Points become paragraphs if long.
            texts = [t for _, t in blocks]
            total = sum(words(t) for t in texts)
            if total <= MAX_WORDS + 50:
                units.append(Unit("art", n, None, heading, "\n".join(texts)))
            else:
                pts = _eu_points(texts)
                units.extend(_group_points(n, heading, pts))
    # Annexes
    for anx in soup.find_all("div", id=re.compile(r"^anx_[IVXLC]+$")):
        label = anx["id"][4:]
        tis = [norm_ws(p.get_text(" ", strip=True)) for p in anx.find_all("p", class_="oj-doc-ti", recursive=False)]
        heading = " ".join(tis[1:]) if len(tis) > 1 else (tis[0] if tis else f"ANNEX {label}")
        texts = [t for _, t in _block_texts(anx)]
        for i, ch in enumerate(chunk_paragraphs(texts), 1):
            units.append(Unit("sec", f"annex-{label}", str(i), heading, ch))
    return units


def _eu_points(texts: list[str]) -> list[tuple[str | None, str]]:
    out = []
    for t in texts:
        m = re.match(r"^\(?(\d+[a-z]?|[a-z]{1,4})\)\s", t)
        out.append((m.group(1) if m else None, t))
    return out


def _group_points(art: str, heading, pts) -> list[Unit]:
    """Long unnumbered article (e.g. definitions): one unit per point, intro
    fragments attached to the following point; tiny points grouped."""
    units: list[Unit] = []
    pending: list[str] = []
    for label, t in pts:
        if label is None and not units:
            pending.append(t)
            continue
        if label is None:
            units[-1].text += "\n" + t
            continue
        txt = "\n".join(pending + [t])
        pending = []
        units.append(Unit("art", art, label, heading, txt))
    if pending:
        units.append(Unit("art", art, None, heading, "\n".join(pending)))
    return units


def _eu_para_units(art: str, pid: str, heading, texts: list[str]) -> list[Unit]:
    full = "\n".join(texts)
    if words(full) <= MAX_WORDS + 50:
        return [Unit("art", art, pid, heading, full)]
    # long paragraph: split at its points, intro stays with the first chunk
    chunks = chunk_paragraphs(texts)
    out = []
    for i, ch in enumerate(chunks):
        u = Unit("art", art, pid, heading, ch)
        if i:
            m = re.match(r"^\(?([a-z]{1,4}|\d+)\)", ch)
            u.id_suffix = f"-{m.group(1)}" if m else f"-c{i + 1}"
        out.append(u)
    return out


# ---------------------------------------------------------------------------
# PDF lines
# ---------------------------------------------------------------------------
@dataclass
class Line:
    text: str
    page: int
    size: float
    bold: bool
    block: int
    yrel: float = 0.5            # vertical position of the line on the page (0 top .. 1 bottom)


def _fix_glyphs(s: str, extra: dict | None, counter: collections.Counter) -> str:
    for table in (LIGATURES, extra or {}):
        for k, v in table.items():
            if k in s:
                counter[f"{k!r}->{v!r}"] += s.count(k)
                s = s.replace(k, v)
    return s


def pdf_lines(path: Path, glyph_fixes: dict | None = None,
              counter: collections.Counter | None = None,
              pages: tuple[int, int] | None = None,
              keep_rx: "re.Pattern | None" = None) -> tuple[list[Line], int]:
    import pymupdf
    counter = counter if counter is not None else collections.Counter()
    doc = pymupdf.open(path)
    lines: list[Line] = []
    bno = 0
    toc_pages = set()
    for pno, page in enumerate(doc, 1):
        if pages and not (pages[0] <= pno <= pages[1]):
            continue                    # e.g. bilingual file: only this language's page range
        d = page.get_text("dict", sort=True)
        h = page.rect.height
        ptxt = page.get_text()
        if len(re.findall(r"\.{5,}|…{3,}|(\. ){4,}", ptxt)) >= 5:
            toc_pages.add(pno)
        for b in d["blocks"]:
            if b.get("type") != 0:
                continue
            bno += 1
            for ln in b["lines"]:
                spans = [s for s in ln["spans"] if s["text"].strip()]
                if not spans:
                    continue
                t = "".join(s["text"] for s in ln["spans"])
                t = _fix_glyphs(t, glyph_fixes, counter)
                t = norm_ws(t)
                if not t:
                    continue
                y0 = ln["bbox"][1]
                if pno in toc_pages:
                    continue
                size = max(s["size"] for s in spans)
                bold = any((s["flags"] & 16) or "bold" in s["font"].lower() for s in spans)
                lines.append(Line(t, pno, round(size, 1), bold, bno, round(y0 / h, 3) if h else 0.5))
    npages = doc.page_count
    # drop running headers/footers and bare page numbers
    key = lambda t: re.sub(r"\d+", "#", t.lower())
    pages_with = collections.defaultdict(set)
    for l in lines:
        if len(l.text) < 140:
            pages_with[key(l.text)].add(l.page)
    thresh = max(3, int(0.25 * npages))
    rep = {k for k, ps in pages_with.items() if len(ps) >= thresh and len(re.findall(r"[^\W\d_]", k)) >= 3}
    out = []
    for l in lines:
        if key(l.text) in rep and not (keep_rx is not None and keep_rx.match(l.text)):
            continue
        if re.fullmatch(r"[-–—\s]*(page\s*)?[0-9ivxlc]{1,4}[-–—\s]*", l.text, re.I) \
                and (l.yrel < 0.1 or l.yrel > 0.88):
            continue
        if re.search(r"\.{5,}\s*\d*$", l.text):
            continue
        out.append(l)
    return out, npages


def body_size(lines: list[Line]) -> float:
    c = collections.Counter()
    for l in lines:
        c[l.size] += len(l.text)
    return c.most_common(1)[0][0] if c else 10.0


# ---------------------------------------------------------------------------
# Section splitter (standards / frameworks / guidance)
# ---------------------------------------------------------------------------
NUM_MARK = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,5})\.?(?:\s+(.*))?$")


def _plausible_next(prev: tuple | None, cand: tuple) -> bool:
    if prev is None:
        return cand in ((1,), (1, 1)) or (len(cand) == 1 and cand[0] <= 3)
    if cand == prev + (1,):
        return True
    for k in range(len(prev), 0, -1):
        if cand == prev[: k - 1] + (prev[k - 1] + 1,):
            return True
    # a parent heading may be unnumbered in the text layer (e.g. "2." drawn separately):
    # accept (n+1, 1) after (n, x)
    if len(cand) > 1 and cand[-1] == 1 and _plausible_next(prev, cand[:-1]):
        return True
    return False


@dataclass
class _Sec:
    label: str
    heading: str | None
    page: int
    paras: list[str] = field(default_factory=list)


def split_sections(lines: list[Line], *, numbered=True, font_headings=True,
                   extra_markers: list[str] | None = None) -> list[_Sec]:
    bsize = body_size(lines)
    extra = [re.compile(p) for p in (extra_markers or [])]
    annex = re.compile(r"^(Annex|Appendix|ANNEX|APPENDIX)\s+([A-Z]|[IVX]+|\d+)(?:\s*[:.\u2013\u2014-].*)?$")
    secs: list[_Sec] = [_Sec("0", None, lines[0].page if lines else 1)]
    prev_num: tuple | None = None
    ordinal = 0
    cur_para: list[str] = []
    cur_block = None
    i = 0

    def flush_para():
        nonlocal cur_para
        if cur_para:
            secs[-1].paras.append(join_lines(cur_para))
            cur_para = []

    def heading_after(idx: int, rest: str | None) -> str | None:
        if rest and words(rest) <= 14 and not HEAD_END.search(rest):
            return rest.rstrip(":").strip()
        if not rest and idx + 1 < len(lines):
            nxt = lines[idx + 1].text
            if words(nxt) <= 14 and not HEAD_END.search(nxt):
                return nxt.rstrip(":").strip()
        return None

    while i < len(lines):
        l = lines[i]
        t = l.text
        started = False
        big = l.size >= bsize - 0.6
        if True:
            for rx in extra:
                m = rx.match(t)
                if m:
                    flush_para()
                    head = (heading_after(i, None) or t) if t.strip() == m.group(1) else (t if words(t) <= 20 else None)
                    secs.append(_Sec(_safe(m.group(1)), head, l.page))
                    started = True
                    break
            if not started:
                m = annex.match(t)
                if m and big and (l.bold or l.size > bsize + 0.5) and words(t) <= 14:
                    flush_para()
                    secs.append(_Sec(f"{m.group(1).lower()}-{m.group(2)}", t, l.page))
                    prev_num = None
                    started = True
            if not started and numbered and big:
                m = NUM_MARK.match(t)
                if m:
                    cand = tuple(int(x) for x in m.group(1).split("."))
                    rest = m.group(2)
                    looks_heading = (rest is None) or (rest[:1].isupper() or rest[:1].isdigit() is False)
                    if looks_heading and _plausible_next(prev_num, cand) and not re.fullmatch(r"\d{3,}", m.group(1)):
                        flush_para()
                        secs.append(_Sec(m.group(1), heading_after(i, rest), l.page))
                        prev_num = cand
                        started = True
            if not started and font_headings and l.bold and abs(l.size - bsize) <= 0.6 and words(t) <= 8 \
                    and t[:1].isupper() and not HEAD_END.search(t) and not NUM_MARK.match(t) \
                    and (i + 1 >= len(lines) or lines[i + 1].block != l.block) \
                    and (i == 0 or lines[i - 1].block != l.block):
                # bold run-alone line at body size: a sub-heading
                flush_para()
                ordinal += 1
                secs.append(_Sec(f"s{ordinal}", t.rstrip(":").strip(), l.page))
                secs[-1].paras.append(t)
                cur_block = l.block
                i += 1
                continue
            if not started and font_headings and l.size >= bsize * 1.25 and words(t) <= 14 \
                    and re.search(r"[A-Za-z؀-ۿ]{3}", t):
                # consecutive large lines form one heading
                flush_para()
                hl = [t]
                while i + 1 < len(lines) and lines[i + 1].size >= bsize * 1.25 and words(" ".join(hl)) <= 20 \
                        and lines[i + 1].page == l.page:
                    i += 1
                    hl.append(lines[i].text)
                ordinal += 1
                head = join_lines(hl)
                secs.append(_Sec(f"s{ordinal}", head, l.page))
                secs[-1].paras.append(head)
                cur_block = lines[i].block
                i += 1
                continue
        if l.block != cur_block:
            flush_para()
            cur_block = l.block
        if started:
            cur_block = l.block
        cur_para.append(t)
        i += 1
    flush_para()
    return [s for s in secs if s.paras]


def _atomic_units(secs: list[_Sec]) -> list[Unit]:
    """One unit per numbered provision (no size-based merging), for standards whose numbered
    provisions are short and cited individually (e.g. DoH RAI 3.1.4.5.1). Heading-only sections
    ("3.1.4.5 Infrastructure Security and Sovereignty") become the heading of their descendants."""
    heads: dict[tuple, str] = {}
    units: list[Unit] = []
    numbered = [tuple(x.label.split(".")) for x in secs if re.fullmatch(r"\d+(?:\.\d+)*", x.label)]
    parents = {p[:k] for p in numbered for k in range(1, len(p))}
    for s in secs:
        txt = "\n".join(s.paras).strip()
        parts = tuple(s.label.split(".")) if re.fullmatch(r"\d+(?:\.\d+)*", s.label) else None
        if parts in parents and words(txt) <= 15 and not HEAD_END.search(txt):
            heads[parts] = s.heading or re.sub(r"^\d+(?:\.\d+)*\.?\s*", "", txt)
            continue
        heading = s.heading
        if parts:
            anc = [heads[parts[:k]] for k in range(len(parts) - 1, 0, -1) if parts[:k] in heads]
            if anc:
                heading = anc[0]
        chunks = chunk_paragraphs(s.paras)
        for k, ch in enumerate(chunks, 1):
            u = Unit("sec", s.label, None, heading, ch, s.page)
            if len(chunks) > 1:
                u.id_suffix = f"-part{k}"
            units.append(u)
    return units


def sections_to_units(secs: list[_Sec], atomic: bool = False) -> list[Unit]:
    if atomic:
        return _atomic_units(secs)
    # 1) merge tiny sections: heading-like -> forward, otherwise -> backward
    merged: list[_Sec] = []
    carry: _Sec | None = None
    for s in secs:
        if carry is not None:
            s = _Sec(carry.label, carry.heading or s.heading, carry.page, carry.paras + s.paras)
            carry = None
        w = sum(words(p) for p in s.paras)
        if w < MIN_WORDS:
            last_txt = s.paras[-1] if s.paras else ""
            if not SENT_END.search(last_txt) or w < 15:
                carry = s
                continue
            if merged and sum(words(p) for p in merged[-1].paras) + w <= MAX_WORDS:
                merged[-1].paras.extend(s.paras)
                continue
        merged.append(s)
    if carry is not None:
        if merged and sum(words(p) for p in merged[-1].paras) + sum(words(p) for p in carry.paras) <= HARD_MAX:
            merged[-1].paras.extend(carry.paras)
        else:
            merged.append(carry)
    # 2) chunk large sections
    units: list[Unit] = []
    for s in merged:
        chunks = chunk_paragraphs(s.paras)
        for k, ch in enumerate(chunks, 1):
            u = Unit("sec", s.label, None, s.heading, ch, s.page)
            if len(chunks) > 1:
                u.id_suffix = f"-part{k}"
            units.append(u)
    return units


def _assign_pages(units: list[Unit], lines: list[Line]) -> None:
    """Page of the first line of each unit (best effort)."""
    idx = {}
    for l in lines:
        idx.setdefault(l.text[:60], l.page)
    for u in units:
        first = u.text.split("\n", 1)[0][:60]
        if first in idx:
            u.page = idx[first]


# ---------------------------------------------------------------------------
# Law splitter (article markers) -- used for HTML/PDF text of laws, EN and AR
# ---------------------------------------------------------------------------
AR_ORD = {
    "الأولى": 1, "الاولى": 1, "الثانية": 2, "الثالثة": 3, "الرابعة": 4, "الخامسة": 5,
    "السادسة": 6, "السابعة": 7, "الثامنة": 8, "التاسعة": 9, "العاشرة": 10,
}
AR_UNITS_ORD = {"الحادية": 1, "الثانية": 2, "الثالثة": 3, "الرابعة": 4, "الخامسة": 5, "السادسة": 6,
                "السابعة": 7, "الثامنة": 8, "التاسعة": 9}
AR_TENS = {"عشرة": 10, "العشرون": 20, "الثلاثون": 30, "الأربعون": 40, "الخمسون": 50, "الستون": 60,
           "السبعون": 70, "الثمانون": 80, "التسعون": 90}
AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

EN_ART = re.compile(r"^\s*(?::\s*)?Article\s*\(?\s*(\d+)\s*\)?(?:\s*[-–:.]\s*|\s+|$)(.*)$", re.I)
AR_ART = re.compile(r"^\s*(?:ال)?مادة\s*(?:رقم)?\s*[\(（]?\s*([0-9٠-٩]+)\s*[\)）]?\s*[-–:]?\s*(.*)$")
AR_ART_ORD = re.compile(r"^\s*(?:ال)?مادة\s+((?:\S+)(?:\s+(?:و?\S+)){0,2})\s*$")
EN_PARA = re.compile(r"^\s*(\d{1,2})\s*[.\-–)]\s*\S")
AR_PARA = re.compile(r"^\s*([0-9٠-٩]{1,2})\s*[.\-–)]\s*\S")


def _ar_ordinal(s: str) -> int | None:
    s = s.strip()
    if s in AR_ORD:
        return AR_ORD[s]
    toks = s.replace("و", " و ").split()
    toks = [t for t in toks if t != "و"]
    if len(toks) == 2 and toks[0] in AR_UNITS_ORD and toks[1] in AR_TENS:
        return AR_UNITS_ORD[toks[0]] + AR_TENS[toks[1]] if AR_TENS[toks[1]] > 10 else AR_UNITS_ORD[toks[0]] + 10
    if len(toks) == 1 and toks[0] in AR_TENS:
        return AR_TENS[toks[0]]
    return None


def split_law(paras: list[tuple[str, int | None]], lang: str) -> tuple[list[Unit], list[str]]:
    """paras: [(paragraph_text, page)]. Returns units and a list of notes."""
    arts: list[dict] = []
    preamble: list[tuple[str, int | None]] = []
    notes: list[str] = []
    last_n = 0
    for text, page in paras:
        first = text.split("\n", 1)[0]
        n, rest = None, None
        if lang == "en":
            m = EN_ART.match(first)
            if m:
                n, rest = int(m.group(1)), m.group(2)
        else:
            m = AR_ART.match(first)
            if m:
                n, rest = int(m.group(1).translate(AR_DIGITS)), m.group(2)
            else:
                m = AR_ART_ORD.match(first)
                if m:
                    n = _ar_ordinal(m.group(1))
                    rest = ""
        # accept only forward-moving article numbers (cross references like
        # "Article 5 of this Law" at line start are rejected unless they follow on)
        if n is not None and (n == last_n + 1 or (last_n == 0 and n <= 2) or n == last_n + 2):
            last_n = n
            heading = rest.strip() if rest and words(rest) <= 12 and not SENT_END.search(rest) else None
            body = text.split("\n", 1)[1] if "\n" in text else ""
            if heading is None and body.strip():
                b0, _, brest = body.strip().partition("\n")
                if words(b0) <= 12 and not SENT_END.search(b0):
                    heading, first, body = b0.strip(), first + "\n" + b0.strip(), brest
            arts.append({"n": str(n), "heading": heading, "page": page, "paras": []})
            if rest and not heading:
                arts[-1]["paras"].append(first)
            elif heading:
                arts[-1]["first"] = first
            else:
                arts[-1]["first"] = first
            if body.strip():
                arts[-1]["paras"].append(body)
            continue
        if not arts:
            preamble.append((text, page))
            continue
        a = arts[-1]
        if a["heading"] is None and not a["paras"] and words(text) <= 12 and not SENT_END.search(text):
            a["heading"] = text
            a["first"] = a.get("first", "") + "\n" + text
            continue
        a["paras"].append(text)
    units: list[Unit] = []
    if preamble:
        for k, ch in enumerate(chunk_paragraphs([t for t, _ in preamble]), 1):
            units.append(Unit("sec", "preamble", str(k), None, ch, preamble[0][1]))
    pmark = EN_PARA if lang == "en" else AR_PARA
    for a in arts:
        head_txt = a.get("first", "").strip()
        # group by numbered paragraphs
        groups: list[tuple[str | None, list[str]]] = []
        expect = 1
        for p in a["paras"]:
            m = pmark.match(p)
            if m and int(m.group(1).translate(AR_DIGITS)) == expect:
                groups.append((str(expect), [p]))
                expect += 1
            elif groups:
                groups[-1][1].append(p)
            else:
                groups.append((None, [p]))
        total = sum(words(p) for p in a["paras"])
        if len(groups) <= 1 or total <= MAX_WORDS // 2:
            body = [head_txt] + a["paras"] if head_txt else a["paras"]
            chunks = chunk_paragraphs(body)
            for k, ch in enumerate(chunks, 1):
                u = Unit("art", a["n"], None, a["heading"], ch, a["page"])
                if len(chunks) > 1:
                    u.paragraph = str(k)
                    u.id_suffix = ""
                units.append(u)
            continue
        # intro (unnumbered) joins the first numbered paragraph
        if groups[0][0] is None and len(groups) > 1:
            intro = groups.pop(0)[1]
            groups[0] = (groups[0][0], intro + groups[0][1])
        for k, (pid, ps) in enumerate(groups):
            body = ([head_txt] if (k == 0 and head_txt) else []) + ps
            chunks = chunk_paragraphs(body)
            for j, ch in enumerate(chunks, 1):
                u = Unit("art", a["n"], pid, a["heading"], ch, a["page"])
                if len(chunks) > 1:
                    u.id_suffix = f"-c{j}"
                units.append(u)
    if not arts:
        notes.append("no article markers found")
    return units, notes


# ---------------------------------------------------------------------------
# HTML (official flipbook "basic-html" bundles, generic HTML)
# ---------------------------------------------------------------------------
PAGE_SEP = "<!-- MAJLIS-PAGE"


def flipbook_paragraphs(path: Path) -> list[tuple[str, int | None]]:
    """Paragraphs from a bundle of FlipBuilder 'basic-html' pages (text in <pre>)."""
    from bs4 import BeautifulSoup
    raw = path.read_text(encoding="utf-8", errors="replace")
    pages = raw.split(PAGE_SEP)[1:] or [" 1 -->\n" + raw]   # a plain HTML file = one page
    out: list[tuple[str, int | None]] = []
    for chunk in pages:
        m = re.match(r"\s*(\d+)", chunk)
        pno = int(m.group(1)) if m else None
        soup = BeautifulSoup(chunk, "lxml")
        pre = soup.find("pre")
        if pre is not None:
            text = pre.get_text()
        else:
            for tag in soup(["script", "style", "nav", "header", "footer"]):
                tag.decompose()
            text = (soup.body or soup).get_text("\n\n")
        # FlipBuilder lays text out with spaces; paragraphs are separated by blank lines
        blocks = re.split(r"\n\s*\n", text)
        for b in blocks:
            ls = [x.strip() for x in b.split("\n") if x.strip()]
            ls = [x for x in ls if not re.fullmatch(r"[-–\s]*\d{1,3}[-–\s\d]*", x)]
            if not ls:
                continue
            # keep article marker lines as their own lines
            cur: list[str] = []
            for x in ls:
                x = re.sub(r"\s{2,}", " ", x)
                is_mark = bool(EN_ART.fullmatch(x) or AR_ART.fullmatch(x))
                if is_mark and cur:
                    out.append((join_lines(cur), pno))
                    cur = []
                if not cur and out and not is_mark and (EN_ART.fullmatch(out[-1][0]) or AR_ART.fullmatch(out[-1][0])) \
                        and words(x) <= 12 and not SENT_END.search(x):
                    out.append((x, pno))        # article heading line right after the marker
                    continue
                cur.append(x)
                if is_mark:
                    out.append((x, pno))
                    cur = []
            if cur:
                out.append((join_lines(cur), pno))
    # merge marker-only paragraphs with the following heading line
    merged: list[tuple[str, int | None]] = []
    for t, p in out:
        if merged and (EN_ART.fullmatch(merged[-1][0]) or AR_ART.fullmatch(merged[-1][0])) \
                and "\n" not in merged[-1][0] and words(t) <= 12 and not SENT_END.search(t):
            merged[-1] = (merged[-1][0] + "\n" + t, merged[-1][1])
        else:
            merged.append((t, p))
    return merged


@dataclass
class _PlainLine:
    text: str
    page: int
    block: int = 0


def sorted_pdf_lines(path: Path) -> list[_PlainLine]:
    """Lines in visual reading order (pymupdf sort=True), for PDFs whose text layer is stored out of
    order (MR 51/2021 English: case 4 sits inside case 3). Bidi-misplaced punctuation at the start of a
    line (".country", ",conditions") is moved to the line end: an ordering repair, not a content change."""
    import pymupdf
    out: list[_PlainLine] = []
    for pno, page in enumerate(pymupdf.open(path), 1):
        for raw in page.get_text(sort=True).splitlines():
            t = norm_ws(raw)
            if not t or re.fullmatch(r"\d{1,3}", t):
                continue
            m = re.match(r"^([.,;])\s*(\S.*)$", t)
            if m:
                t = m.group(2) + m.group(1)
            m = re.match(r"^(\S.*?)\s+\.\s?(\d{1,2})$", t)   # item number pushed to the line end: "... . 10"
            if m:
                t = f"{m.group(2)}. {m.group(1)}"
            out.append(_PlainLine(t, pno))
    return out


def pdf_law_paragraphs(path: Path, counter, sort: bool = False) -> list[tuple[str, int | None]]:
    # law mode: "Article (n)" / "المادة (n)" lines repeat on many pages but are structure, not running headers
    keep = re.compile(r"^\s*(?::\s*)?(?:Article\s*\(?\s*\d+\s*\)?\s*$|(?:ال)?مادة\s*[\(（]?\s*[0-9٠-٩]+\s*[\)）]?\s*$)", re.I)
    lines = sorted_pdf_lines(path) if sort else pdf_lines(path, None, counter, keep_rx=keep)[0]
    out: list[tuple[str, int | None]] = []
    cur: list[str] = []
    cur_block = None
    cur_page = None
    for l in lines:
        is_marker = bool(EN_ART.match(l.text) or AR_ART.match(l.text) or AR_ART_ORD.match(l.text))
        # a new paragraph starts at an article marker, a numbered/lettered/bulleted item, or a block
        # change after a line that ends a sentence; other line wraps are joined (whitespace only)
        prev_end = bool(cur) and bool(re.search(r"[.:;؛]\s*$", cur[-1]))
        item = bool(EN_PARA.match(l.text) or AR_PARA.match(l.text)
                    or re.match(r"^\s*(?:[•▪●-]|\(?[a-z]\)|[a-z]\.|\([ivx]+\))\s", l.text))
        new_para = is_marker or item or (l.block != cur_block and (prev_end or not cur))
        if new_para and cur:
            out.append((join_lines(cur), cur_page))
            cur = []
        if not cur:
            cur_page = l.page
        cur.append(l.text)
        cur_block = l.block
        if is_marker:
            out.append((l.text, l.page))
            cur = []
    if cur:
        out.append((join_lines(cur), cur_page))
    return out


# ---------------------------------------------------------------------------
# document dispatcher
# ---------------------------------------------------------------------------
# Per-document parser settings (structure only, never content).
PARSE_CONFIG: dict[str, dict] = {
    "US-NIST-AI-100-1": {"mode": "pdf", "extra_markers": [r"^((?:GOVERN|MAP|MEASURE|MANAGE)\s+\d+(?:\.\d+)?):"]},
    "AE-AI-CHARTER-2024": {"mode": "pdf", "glyph_fixes": TH_LIGATURE},
    "AE-NSAI-2031": {"mode": "pdf", "numbered": False},
    "SA-NSDAI": {"mode": "pdf", "numbered": False},
    "SG-IMDA-AGENTIC-2026": {"mode": "pdf"},
    "WHO-AI-HEALTH-2021": {"mode": "pdf"},
    "WHO-AI-LMM-2024": {"mode": "pdf"},
    # DoH RAI: numbered provisions are one or two sentences and are cited individually (3.1.4.5.1)
    "AE-DOH-RAI-2025": {"mode": "pdf", "atomic": True},
    "AE-DOH-DGS-2025": {"mode": "pdf", "atomic": True},
    "AE-DHA-AI-POLICY": {"mode": "pdf", "atomic": True},
    # MR 51/2021 English: text layer out of reading order; read in visual order
    "AE-MR-51-2021": {"mode": "pdf", "sorted_text": True},
    # ADHICS: control / sub-control codes printed alone on a line ("HR 2", "HR 2.1")
    "AE-DOH-ADHICS": {"mode": "pdf", "font_headings": False, "extra_markers": [r"^((?:HR|AM|PE|AC|OM|CM|HI|TP|SA|IM|SC|IG)\s?\d{1,2}(?:\.\d{1,2})?)$"]},
    # bilingual file (EN pages 1-34, AR pages 36-69); keys "<doc_id>:<lang>" override "<doc_id>"
    "AE-CSC-NCS-2025:en": {"mode": "pdf", "pages": (1, 34)},
    "AE-CSC-NCS-2025:ar": {"mode": "pdf", "pages": (36, 69)},
}


def parse_document(row: dict, path: Path, lang: str) -> tuple[list[Unit], dict]:
    """Return (units, info). info: mode, glyph_repairs, notes, extraction status."""
    info: dict = {"notes": [], "glyph_repairs": {}}
    cfg = PARSE_CONFIG.get(f"{row['doc_id']}:{lang}") or PARSE_CONFIG.get(row["doc_id"], {})
    itype = row["instrument_type"]
    is_law = itype in ("law", "decree", "regulation") or row["doc_id"].startswith(("AE-FDL", "AE-FL", "AE-CR"))
    counter: collections.Counter = collections.Counter()
    suffix = path.suffix.lower()
    if suffix in (".xhtml",) or (suffix in (".html", ".htm") and b"oj-ti-art" in path.read_bytes()[:3_000_000]):
        info["mode"] = "eu_xhtml"
        units = parse_eu_xhtml(path)
    elif suffix in (".html", ".htm"):
        info["mode"] = "law_html"
        paras = flipbook_paragraphs(path)
        units, notes = split_law(paras, lang)
        info["notes"] += notes
    elif suffix == ".pdf":
        import pymupdf
        doc = pymupdf.open(path)
        nwords = sum(len(p.get_text().split()) for p in doc)
        if nwords < 20 * max(1, doc.page_count) * 0.1 and nwords < 100:
            info["mode"] = "pdf_no_text"
            info["notes"].append(f"no text layer ({nwords} words on {doc.page_count} pages; scanned image)")
            return [], info
        if is_law:
            info["mode"] = "law_pdf"
            paras = pdf_law_paragraphs(path, counter, sort=cfg.get("sorted_text", False))
            units, notes = split_law(paras, lang)
            info["notes"] += notes
        else:
            info["mode"] = "pdf_sections"
            lines, _ = pdf_lines(path, cfg.get("glyph_fixes"), counter, cfg.get("pages"))
            secs = split_sections(lines, numbered=cfg.get("numbered", True),
                                  font_headings=cfg.get("font_headings", True),
                                  extra_markers=cfg.get("extra_markers"))
            units = sections_to_units(secs, atomic=cfg.get("atomic", False))
    else:
        info["mode"] = "unsupported"
        info["notes"].append(f"unsupported file type {suffix}")
        return [], info
    info["glyph_repairs"] = dict(counter)
    # make clause id cores unique and stable (document order)
    seen: collections.Counter = collections.Counter()
    for u in units:
        core = u.id_core()
        seen[core] += 1
        if seen[core] > 1:
            u.id_suffix += f"-dup{seen[core]}"
    return [u for u in units if u.text.strip()], info


def clause_quality(text: str, lang: str) -> tuple[bool, str]:
    if lang == "ar":
        return arabic_quality(text)
    letters = sum(c.isalpha() for c in text)
    if letters < 8:
        return False, "too_little_text"
    odd = sum(1 for c in text if unicodedata.category(c) in ("Co", "Cn") or c == "�")
    if odd / max(1, len(text)) > 0.02:
        return False, "unmapped_glyphs"
    return True, "ok"
