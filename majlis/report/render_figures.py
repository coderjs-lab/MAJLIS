"""Renders the report's four figures to PNG from the same LaTeX/TikZ code used in majlis_report.tex.

Each figure is compiled as a standalone document with tectonic, then rasterised with pdftoppm.
Output: report/figures/fig1_architecture.png, fig2_timeline.png, fig3_outcomes.png, fig4_citations.png

Usage (from ITUAIReadiness/majlis): .venv/bin/python report/render_figures.py
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEX = (HERE / "majlis_report.tex").read_text(encoding="utf-8")
OUT = HERE / "figures"
BUILD = HERE / "figures" / "_build"


def preamble() -> str:
    """Everything the figures need from the report preamble: fonts, colours, TikZ styles, numbers."""
    head = TEX[: TEX.index("\\begin{document}")]
    keep = []
    for line in head.splitlines():
        if line.startswith("\\documentclass") or "geometry" in line or "titlesec" in line or "\\titl" in line \
                or "hyperref" in line or "caption" in line or "enumitem" in line or "\\setlist" in line \
                or "\\setlength{\\parskip}" in line or "stfloats" in line or "fraction" in line or "number}" in line:
            continue
        keep.append(line)
    body = "\n".join(keep).replace("\\input{generated/numbers.tex}", f"\\input{{{HERE / 'generated' / 'numbers.tex'}}}")
    return "\\documentclass[border=3pt]{standalone}\n" + body


def arch_tikz() -> str:
    start = TEX.index("\\begin{tikzpicture}[\n  font=\\footnotesize,\n  box/.style")
    end = TEX.index("\\end{tikzpicture}", start) + len("\\end{tikzpicture}")
    return TEX[start:end]


def figure_sources() -> dict[str, str]:
    gen = HERE / "generated"
    wrap = lambda body, width: f"\\begin{{minipage}}{{{width}}}\\centering\n{body}\n\\end{{minipage}}"
    return {
        "fig1_architecture": arch_tikz(),
        "fig2_timeline": (gen / "fig_timeline.tex").read_text(encoding="utf-8"),
        "fig3_outcomes": wrap((gen / "fig_outcomes.tex").read_text(encoding="utf-8"), "3.4in"),
        "fig4_citations": wrap((gen / "fig_citations.tex").read_text(encoding="utf-8"), "3.4in"),
    }


def main() -> None:
    BUILD.mkdir(parents=True, exist_ok=True)
    pre = preamble()
    for name, body in figure_sources().items():
        src = BUILD / f"{name}.tex"
        src.write_text(f"{pre}\n\\begin{{document}}\n{body}\n\\end{{document}}\n", encoding="utf-8")
        r = subprocess.run(["tectonic", "-X", "compile", src.name], cwd=BUILD, capture_output=True, text=True)
        if r.returncode != 0:
            errs = [l for l in r.stderr.splitlines() if l.startswith("error")]
            raise SystemExit(f"{name}: tectonic failed\n" + "\n".join(errs[:10]))
        subprocess.run(["pdftoppm", "-png", "-r", "300", "-singlefile", f"{name}.pdf", str(OUT / name)],
                       cwd=BUILD, check=True)
        print(f"rendered {OUT / (name + '.png')}")
    shutil.rmtree(BUILD)


if __name__ == "__main__":
    main()
