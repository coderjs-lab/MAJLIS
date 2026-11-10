"""Builds the Word version of the report in the OFFICIAL submission template, from majlis_report.tex.

The LaTeX file is the single source of truth: sections, paragraphs, bullets, tables, captions and numbers are
converted from it, so the .docx and the PDF always say the same thing. The template's own title paragraph,
field lines, numbered headings, bullet style and page setup are cloned. Figures come from render_figures.py.
An HTML twin is written next to it so page count can be checked with a browser.

Usage (from ITUAIReadiness/majlis):
  .venv/bin/python report/render_figures.py && .venv/bin/python report/build_docx.py
"""
from __future__ import annotations

import copy
import html
import re
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from docx.text.paragraph import Paragraph

HERE = Path(__file__).resolve().parent
TEX = (HERE / "majlis_report.tex").read_text(encoding="utf-8")
# generated table bodies (tab_*.tex) are inlined; figure inputs stay as images
TEX = re.sub(r"\\input\{(generated/tab_[^}]+)\}", lambda m: (HERE / m.group(1)).read_text(encoding="utf-8").strip(), TEX)
TEMPLATE = HERE / "submission-template.docx"
OUT_DOCX = HERE / "MAJLIS_Technical_Report.docx"
OUT_HTML = HERE / "figures" / "docx_preview.html"

TITLE = "AI for Good Sandbox Hackathon – Team MAJLIS – MAJLIS: Rehearsing AI Incidents Across Institutions with Verifiable Law"
META = [("Team leader", "Aya Elsayed"), ("Team members", "Aya Elsayed, Abhra Dubey, Harmanjot Singh"),
        ("Contact details", "abhra.dubey@mbzuai.ac.ae"), ("Github link", "https://github.com/coderjs-lab/MAJLIS")]
COLORS = {"okc": "1F7A4D", "denyc": "B42318", "escc": "A86A00", "brand": "0E4F4C"}
FIGS = {"fig:arch": ("fig1_architecture.png", 6.1), "fig:timeline": ("fig2_timeline.png", 4.8),
        "fig:outcomes": ("fig3_outcomes.png", 2.8), "fig:cites": ("fig4_citations.png", 2.8)}
TABLE_WIDTHS = {"tab:req": [0.8, 2.6, 3.1], "tab:map": [0.85, 1.85, 1.75, 2.05],
                "tab:rules": [2.4, 1.0, 3.1], "tab:gaps": [1.65, 0.75, 2.2, 1.35, 0.55],
                "tab:kb": [3.7, 0.8, 1.0, 1.0]}
BODY_PT, TABLE_PT, CAPTION_PT = 9.0, 7.0, 7.6

NUMBERS = dict(re.findall(r"\\newcommand\{\\(\w+)\}\{([^}]*)\}",
                          (HERE / "generated" / "numbers.tex").read_text(encoding="utf-8")))


# ------------------------------------------------------------------------------- LaTeX to marked-up text
def braced(s: str, i: int) -> tuple[str, int]:
    """Returns the content of the {...} group starting at s[i] == '{' and the index after it."""
    assert s[i] == "{", s[i:i + 20]
    depth, j = 0, i
    while True:
        if s[j] == "{" and s[j - 1] != "\\":
            depth += 1
        elif s[j] == "}" and s[j - 1] != "\\":
            depth -= 1
            if depth == 0:
                return s[i + 1:j], j + 1
        j += 1


def replace_cmd(s: str, cmd: str, fn, nargs: int = 1) -> str:
    out, i = [], 0
    while True:
        k = s.find("\\" + cmd + "{", i)
        if k < 0:
            out.append(s[i:])
            return "".join(out)
        out.append(s[i:k])
        j = k + len(cmd) + 1
        args = []
        for _ in range(nargs):
            a, j = braced(s, j)
            args.append(a)
        out.append(fn(*args))
        i = j


def tex2md(s: str) -> str:
    """LaTeX inline markup to a tiny markup: **bold**, ⟪italic⟫, ⟦color|text⟧, ⟦ref:label⟧."""
    for name in sorted(NUMBERS, key=len, reverse=True):
        s = re.sub(r"\\" + name + r"(?![A-Za-z])\\? ?", lambda m, v=NUMBERS[name]: v + (" " if m.group(0).endswith(" ") else ""), s)
    s = replace_cmd(s, "ref", lambda a: f"⟦ref:{a}⟧")
    s = replace_cmd(s, "textcolor", lambda c, t: f"⟦{c}|{tex2md(t)}⟧", 2)
    s = replace_cmd(s, "href", lambda a, b: tex2md(b), 2)
    s = replace_cmd(s, "url", lambda a: a)
    s = replace_cmd(s, "texttt", lambda a: tex2md(a))
    s = replace_cmd(s, "textbf", lambda a: f"**{tex2md(a)}**")
    s = replace_cmd(s, "emph", lambda a: f"⟪{tex2md(a)}⟫")
    s = replace_cmd(s, "textit", lambda a: f"⟪{tex2md(a)}⟫")
    s = replace_cmd(s, "mbox", lambda a: a)
    for a, b in [("\\%", "%"), ("\\&", "&"), ("\\_", "_"), ("\\enspace", " "), ("\\quad", " "), ("\\noindent", ""),
                 ("\\par", ""), ("\\medskip", ""), ("~", " "), ("\\ ", " "), ("\\,", " ")]:
        s = s.replace(a, b)
    s = re.sub(r"\\[A-Za-z]+\*?", "", s)          # any leftover command (layout only)
    s = s.replace("{", "").replace("}", "")
    return re.sub(r"\s+", " ", s).strip()


def caption_of(block: str) -> str:
    for cmd in ("captionof{figure}", "captionof{table}", "caption"):
        k = block.find("\\" + cmd + "{")
        if k >= 0:
            return tex2md(braced(block, k + len(cmd) + 1)[0])
    return ""


def label_of(block: str) -> str:
    m = re.search(r"\\label\{([^}]*)\}", block)
    return m.group(1) if m else ""


def parse_table(block: str):
    inner = block[block.index("\\toprule") + len("\\toprule"): block.index("\\bottomrule")]
    head, body = inner.split("\\midrule", 1)
    body = body.replace("\\midrule", "")  # inner rules (e.g. verified above, rejected below) have no Word equivalent
    split_row = lambda r: [tex2md(c) for c in r.split(" & ")]
    header = split_row(head.strip().rstrip("\\").strip())
    rows = [split_row(r.strip()) for r in re.split(r"\\\\\s*\n", body) if r.strip()]
    return header, rows


# --------------------------------------------------------------------------------------- document model
def parse_blocks() -> list:
    body = TEX[TEX.index("\\begin{document}") + len("\\begin{document}"): TEX.index("\\end{document}")]
    tb = body.index("\\twocolumn[")
    title_block, rest = body[: body.index("}]", tb) + 2], body[body.index("}]", tb) + 2:]
    summary = tex2md(title_block[title_block.index("\\textbf{In one paragraph.}"): title_block.index("\\\\[3pt]")])
    k = title_block.index("\\textit{This is")
    disclaimer = "⟪" + tex2md(braced(title_block, k + len("\\textit"))[0]) + "⟫"
    blocks: list = [("summary", summary, disclaimer)]
    pat = re.compile(r"(\\section\{[^}]*\})|(\\begin\{figure\*\}.*?\\end\{figure\*\})|(\\begin\{table\*\}.*?\\end\{table\*\})"
                     r"|(\\par\\medskip\\noindent\\begin\{minipage\}.*?\\end\{minipage\}\\par\\medskip)"
                     r"|(\\begin\{itemize\}.*?\\end\{itemize\})", re.S)
    pos = 0
    for m in pat.finditer(rest):
        for para in re.split(r"\n\s*\n", rest[pos:m.start()]):
            if para.strip():
                blocks.append(("p", tex2md(para)))
        g = m.group(0)
        if m.group(1):
            blocks.append(("h", tex2md(g[len("\\section{"):-1])))
        elif m.group(5):
            g = g.replace("\\end{itemize}", "")
            blocks.append(("bullets", [tex2md(x) for x in g.split("\\item")[1:]]))
        elif "tabularx" in g:
            header, rows = parse_table(g)
            blocks.append(("table", label_of(g), header, rows, caption_of(g)))
        else:
            blocks.append(("figure", label_of(g), caption_of(g)))
        pos = m.end()
    for para in re.split(r"\n\s*\n", rest[pos:]):
        if para.strip():
            blocks.append(("p", tex2md(para)))
    return place(blocks)


def place(blocks: list) -> list:
    """No floats in Word: each table goes right after the first paragraph that cites it. Figures 3 and 4
    sit side by side. Then figures and tables are numbered in reading order and references resolved."""
    tables = {b[1]: b for b in blocks if b[0] == "table"}
    out = [b for b in blocks if b[0] != "table"]
    for label, tbl in tables.items():
        idx = next((i for i, b in enumerate(out) if b[0] == "p" and f"⟦ref:{label}⟧" in b[1]), len(out) - 1)
        out.insert(idx + 1, tbl)
    figs = {b[1]: b for b in out if b[0] == "figure"}
    if "fig:arch" in figs:  # the architecture figure goes right under the summary, as in research papers
        out.remove(figs["fig:arch"])
        out.insert(1, figs["fig:arch"])
    if "fig:outcomes" in figs and "fig:cites" in figs:
        i = out.index(figs["fig:outcomes"])
        out = [b for b in out if b is not figs["fig:cites"]]
        out[i] = ("figpair", figs["fig:outcomes"], figs["fig:cites"])
    nums, f, t = {}, 0, 0
    for b in out:
        for fb in ([b] if b[0] == "figure" else list(b[1:]) if b[0] == "figpair" else []):
            f += 1
            nums[fb[1]] = f
        if b[0] == "table":
            t += 1
            nums[b[1]] = t
    resolve = lambda s: re.sub(r"⟦ref:([^⟧]+)⟧", lambda m: str(nums.get(m.group(1), "?")), s)

    def fix(b):
        if b[0] in ("p", "h"):
            return (b[0], resolve(b[1]))
        if b[0] == "bullets":
            return ("bullets", [resolve(x) for x in b[1]])
        if b[0] == "summary":
            return ("summary", resolve(b[1]), resolve(b[2]))
        if b[0] == "table":
            return ("table", b[1], b[2], b[3], f"Table {nums[b[1]]}. " + resolve(b[4]))
        if b[0] == "figure":
            return ("figure", b[1], f"Figure {nums[b[1]]}. " + resolve(b[2]))
        if b[0] == "figpair":
            return ("figpair", fix(b[1]), fix(b[2]))
        return b
    return [fix(b) for b in out]


# --------------------------------------------------------------------------------------------- DOCX out
TOKEN = re.compile(r"(\*\*|⟪|⟫|⟦[a-z]+\|[^⟧]*⟧)")


def add_runs(par, text: str, size: float, bold: bool = False, italic: bool = False):
    b, it = bold, italic
    for tok in TOKEN.split(text):
        if not tok:
            continue
        if tok == "**":
            b = not b
            continue
        if tok in ("⟪", "⟫"):
            it = tok == "⟪"
            continue
        color = None
        if tok.startswith("⟦"):
            color, tok = tok[1:-1].split("|", 1)
        r = par.add_run(tok)
        r.font.size = Pt(size)
        r.bold, r.italic = b or bool(color), it
        if color:
            r.font.color.rgb = RGBColor.from_string(COLORS.get(color, "000000"))


def shade(cell, fill: str):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    tcPr.append(shd)


def no_borders(table):
    tblPr = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        e = OxmlElement(f"w:{side}")
        e.set(qn("w:val"), "nil")
        borders.append(e)
    # schema order: tblBorders must come before shd, tblLayout, tblCellMar, tblLook, tblCaption, tblDescription
    later = [c for c in tblPr if c.tag in {qn(f"w:{t}") for t in ("shd", "tblLayout", "tblCellMar", "tblLook",
                                                                   "tblCaption", "tblDescription")}]
    if later:
        later[0].addprevious(borders)
    else:
        tblPr.append(borders)


def write_docx(blocks: list) -> None:
    doc = Document(str(TEMPLATE))
    body = doc.element.body
    paras = doc.paragraphs
    proto = {
        "title": copy.deepcopy(paras[0]._p),
        "meta": copy.deepcopy(paras[1]._p),
        "head": copy.deepcopy(next(p for p in paras if p.text.strip() == "Introduction")._p),
        "bullet": copy.deepcopy(next(p for p in paras if p.text.strip().startswith("appropriate corrective"))._p),
    }
    sect = body.sectPr
    for el in list(body):
        if el is not sect:
            body.remove(el)

    def new(kind: str) -> Paragraph:
        el = copy.deepcopy(proto[kind])
        for r in el.findall(qn("w:r")):
            el.remove(r)
        sect.addprevious(el)
        return Paragraph(el, doc._body)

    def spacing(p, after=3, before=0):
        p.paragraph_format.space_after = Pt(after)
        p.paragraph_format.space_before = Pt(before)
        p.paragraph_format.line_spacing = 1.0

    def picture(cell_or_doc_par, label, width):
        name, w = FIGS[label]
        cell_or_doc_par.add_run().add_picture(str(HERE / "figures" / name), width=Inches(width or w))

    p = new("title")
    add_runs(p, TITLE, 13, bold=True)
    spacing(p, after=6)
    for k, v in META:
        p = new("meta")
        add_runs(p, f"**{k}:** {v}", BODY_PT)
        spacing(p, after=0)
    for b in blocks:
        kind = b[0]
        if kind == "summary":
            t = doc.add_table(rows=1, cols=1)
            t.alignment = WD_TABLE_ALIGNMENT.CENTER
            c = t.cell(0, 0)
            c.width = Inches(6.5)
            shade(c, "F3F1EC")
            no_borders(t)
            cp = c.paragraphs[0]
            add_runs(cp, b[1], 9)
            spacing(cp, after=2)
            cp2 = c.add_paragraph()
            add_runs(cp2, b[2], 8.5, italic=True)
            spacing(cp2, after=0)
            sect.addprevious(t._tbl)
        elif kind == "h":
            p = new("head")
            add_runs(p, b[1], 11.5, bold=True)
            spacing(p, after=2, before=7)
            p.paragraph_format.keep_with_next = True
        elif kind == "p":
            p = new("meta")
            add_runs(p, b[1], BODY_PT)
            spacing(p, after=2)
        elif kind == "bullets":
            for item in b[1]:
                p = new("bullet")
                add_runs(p, item, BODY_PT)
                spacing(p, after=1)
        elif kind == "figure":
            p = new("meta")
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            picture(p, b[1], None)
            spacing(p, after=1, before=4)
            p.paragraph_format.keep_with_next = True
            cap = new("meta")
            add_runs(cap, re.sub(r"^(Figure \d+\.)", r"**\1**", b[2]), CAPTION_PT)
            spacing(cap, after=6)
        elif kind == "figpair":
            t = doc.add_table(rows=2, cols=2)
            t.alignment = WD_TABLE_ALIGNMENT.CENTER
            no_borders(t)
            for col, fb in enumerate(b[1:]):
                c = t.cell(0, col)
                c.width = Inches(3.25)
                cp = c.paragraphs[0]
                cp.alignment = WD_ALIGN_PARAGRAPH.CENTER
                picture(cp, fb[1], None)
                cc = t.cell(1, col).paragraphs[0]
                add_runs(cc, re.sub(r"^(Figure \d+\.)", r"**\1**", fb[2]), CAPTION_PT)
                spacing(cc, after=4)
            sect.addprevious(t._tbl)
        elif kind == "table":
            _, label, header, rows, caption = b
            widths = TABLE_WIDTHS[label]
            t = doc.add_table(rows=1 + len(rows), cols=len(header))
            try:
                t.style = doc.styles["Grid Table Light"]
            except KeyError:
                t.style = doc.styles["Table Grid"]
            t.alignment = WD_TABLE_ALIGNMENT.CENTER
            t.autofit = False
            for ri, row in enumerate([header, *rows]):
                for ci in range(len(header)):
                    cell = t.cell(ri, ci)
                    cell.width = Inches(widths[ci])
                    cp = cell.paragraphs[0]
                    add_runs(cp, row[ci] if ci < len(row) else "", TABLE_PT, bold=(ri == 0))
                    spacing(cp, after=0)
                    if ri == 0:
                        shade(cell, "E8E6E1")
            sect.addprevious(t._tbl)
            cap = new("meta")
            add_runs(cap, re.sub(r"^(Table \d+\.)", r"**\1**", caption), CAPTION_PT)
            spacing(cap, after=6, before=2)
    doc.save(str(OUT_DOCX))


# --------------------------------------------------------------------------------------------- HTML twin
def md_html(s: str) -> str:
    s = html.escape(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = s.replace("⟪", "<i>").replace("⟫", "</i>")
    return re.sub(r"⟦([a-z]+)\|([^⟧]*)⟧", lambda m: f"<b style='color:#{COLORS.get(m.group(1), '000')}'>{m.group(2)}</b>", s)


def write_html(blocks: list) -> None:
    css = f"""@page {{ size: 8.5in 11in; margin: 1in; }}
body {{ font-family: Aptos, Carlito, 'Liberation Sans', Arial, sans-serif; font-size: {BODY_PT}pt; line-height: 1.17; }}
h1 {{ font-size: 13pt; text-align: center; margin: 0 0 6pt; }} h2 {{ font-size: 11.5pt; margin: 7pt 0 2pt; counter-increment: h; }}
h2::before {{ content: counter(h) ". "; }} p {{ margin: 0 0 2pt; text-align: justify; }} .m {{ margin: 0; }}
.box {{ background: #F3F1EC; padding: 4pt 6pt; font-size: 9pt; margin: 4pt 0; }} ul {{ margin: 0 0 3pt 14pt; padding: 0; }}
table.t {{ border-collapse: collapse; font-size: {TABLE_PT}pt; width: 100%; line-height: 1.12; }}
table.t td, table.t th {{ border: 0.5pt solid #bbb; padding: 1.5pt 3pt; vertical-align: top; text-align: left; }} table.t th {{ background: #E8E6E1; }}
.cap {{ font-size: {CAPTION_PT}pt; margin: 2pt 0 6pt; }} img {{ display: block; margin: 4pt auto 1pt; }}"""
    o = [f"<!doctype html><html><head><meta charset='utf-8'><style>{css}</style></head><body><h1>{md_html(TITLE)}</h1>"]
    o += [f"<p class='m'><b>{k}:</b> {v}</p>" for k, v in META]
    for b in blocks:
        if b[0] == "summary":
            o.append(f"<div class='box'>{md_html(b[1])}<br><i>{md_html(b[2])}</i></div>")
        elif b[0] == "h":
            o.append(f"<h2>{md_html(b[1])}</h2>")
        elif b[0] == "p":
            o.append(f"<p>{md_html(b[1])}</p>")
        elif b[0] == "bullets":
            o.append("<ul>" + "".join(f"<li>{md_html(x)}</li>" for x in b[1]) + "</ul>")
        elif b[0] == "figure":
            o.append(f"<img src='{FIGS[b[1]][0]}' style='width:{FIGS[b[1]][1]}in'><p class='cap'>{md_html(b[2])}</p>")
        elif b[0] == "figpair":
            cells = "".join(f"<td style='width:50%;vertical-align:top'><img src='{FIGS[fb[1]][0]}' style='width:{FIGS[fb[1]][1]}in'>"
                            f"<p class='cap'>{md_html(fb[2])}</p></td>" for fb in b[1:])
            o.append(f"<table style='width:100%'><tr>{cells}</tr></table>")
        elif b[0] == "table":
            _, label, header, rows, cap = b
            tot = sum(TABLE_WIDTHS[label])
            cols = "".join(f"<col style='width:{w / tot * 100:.1f}%'>" for w in TABLE_WIDTHS[label])
            o.append(f"<table class='t'><colgroup>{cols}</colgroup><tr>" + "".join(f"<th>{md_html(h)}</th>" for h in header) + "</tr>"
                     + "".join("<tr>" + "".join(f"<td>{md_html(c)}</td>" for c in r) + "</tr>" for r in rows)
                     + f"</table><p class='cap'>{md_html(cap)}</p>")
    o.append("</body></html>")
    OUT_HTML.write_text("\n".join(o), encoding="utf-8")


def main() -> None:
    blocks = parse_blocks()
    write_docx(blocks)
    write_html(blocks)
    kinds = [b[0] for b in blocks]
    print(f"wrote {OUT_DOCX.name}: {kinds.count('h')} sections, {kinds.count('p')} paragraphs, "
          f"{kinds.count('table')} tables, {kinds.count('figure') + 2 * kinds.count('figpair')} figures")


if __name__ == "__main__":
    main()
