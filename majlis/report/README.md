# MAJLIS technical report

| File | What it is |
|---|---|
| [`MAJLIS_Technical_Report.pdf`](MAJLIS_Technical_Report.pdf) | The report, 5 pages, built from the LaTeX source |
| [`MAJLIS_Technical_Report.docx`](MAJLIS_Technical_Report.docx) | The same report in the organisers' official Word template |
| [`majlis_report.tex`](majlis_report.tex) | LaTeX source (text, tables, TikZ architecture figure) |
| [`generated/`](generated/) | Every number (`numbers.tex`), the data figures and the knowledge-base table, generated from the run logs |
| [`figures/`](figures/) | PNG renders of the four figures, used by the Word version |
| [`make_data.py`](make_data.py) | Writes `generated/` from the committed ledgers in `../runs/` (nothing is typed in by hand) |
| [`render_figures.py`](render_figures.py) | Renders the figures to PNG from the same TikZ/pgfplots code |
| [`build_docx.py`](build_docx.py) | Converts the LaTeX source into the official template (`submission-template.docx`) |

The runs behind the numbers are listed in [`generated/runs.txt`](generated/runs.txt).

## Rebuild

From `itu/majlis` (the `majlis` folder of this repository), with the Python environment from the main README and [tectonic](https://tectonic-typesetting.github.io/) installed:

```bash
.venv/bin/python report/make_data.py \
  --gov runs/20261109-222620_s1_failover_governed_en \
  --ungov runs/20261109-222623_s1_failover_ungoverned_en \
  --ar runs/20261109-222626_s1_failover_governed_ar \
  --cards runs/20261109-224223_s1_failover_governed_en \
  --ungov_early runs/20261109-154057_s1_failover_ungoverned_en
(cd report && tectonic -X compile majlis_report.tex && cp majlis_report.pdf MAJLIS_Technical_Report.pdf)
.venv/bin/python report/render_figures.py
.venv/bin/python report/build_docx.py
```
