# Manual downloads checklist (UAE + blocked sources)

Status 2026-11-09: the team downloaded the ticked items in a browser; they are in `kb/raw/manual/`
(status `manual_ok` in the manifest). Still open: FDL 44/2021 Arabic, Charter Arabic, a readable Arabic
text layer for PDPL / FL 2/2019 / NSAI / NCS (all four fail Arabic QA: broken lam-alef joins or
presentation forms), SDAIA AI ethics, Saudi PDPL. The National Cybersecurity Strategy (125 MB, EN+AR) is
read in place from the team's downloads folder and not redistributed (sha256 in the manifest).

Why: these official portals block or break plain automated downloads (403 / TLS errors / image-only files).
Every failed attempt is in `kb/sources/access_log.csv` (evidence for technical gap TG1: no machine-readable
official UAE legal corpus). Download each file **in a normal browser from the official page**, save it under
the exact filename, and tick it. Official sources only (no law-firm copies, no gdpr-info-style mirrors).

## Must
- [x] **AE-FDL-45-2021** PDPL, Federal Decree-Law No. 45 of 2021 on the Protection of Personal Data
  - English PDF: https://uaelegislation.gov.ae/en/legislations/1972 ("Download") -> `kb/raw/manual/AE-FDL-45-2021.pdf`
  - Arabic PDF (authoritative): https://uaelegislation.gov.ae/ar/legislations/1972 -> `kb/raw/manual/AE-FDL-45-2021.ar.pdf`
    (u.ae/government.ae also linked an Arabic PDF; government.ae failed TLS host check, u.ae path 404)
- [x] **AE-FDL-44-2021** Federal Decree-Law No. 44 of 2021 establishing the Emirates Data Office
  - English: https://uaelegislation.gov.ae/en/legislations/2433 -> `kb/raw/manual/AE-FDL-44-2021.pdf`
  - Arabic: https://uaelegislation.gov.ae/ar/legislations/2433 -> `kb/raw/manual/AE-FDL-44-2021.ar.pdf`
- [x] **AE-FL-2-2019** Federal Law No. 2 of 2019 (ICT in health fields), Arabic original
  - English already ingested from the official EHS flipbook text. The EHS Arabic flipbook has no text layer.
  - Arabic PDF: https://uaelegislation.gov.ae/ar/legislations/1209 -> `kb/raw/manual/AE-FL-2-2019.ar.pdf`
- [x] **AE-CR-32-2020** Cabinet Resolution No. 32 of 2020 (Executive Regulations of Federal Law 2/2019)
  - MOHAP's PDF is a scanned image (no text). Text PDF from https://uaelegislation.gov.ae/en/legislations/1444
    (verify the title on the page) -> `kb/raw/manual/AE-CR-32-2020.pdf`; Arabic -> `kb/raw/manual/AE-CR-32-2020.ar.pdf`
- [x] **AE-MOHAP-DATALOC-2021** (now **AE-MR-51-2021**, Ministerial Resolution No. 51 of 2021) the 2021 resolution on exceptions to health-data localisation under Federal Law 2/2019
  - Find the exact instrument on uaelegislation.gov.ae or mohap.gov.ae; record its number/title in `manifest.csv`
    (title column), save -> `kb/raw/manual/AE-MOHAP-DATALOC-2021.pdf`
- [ ] **AE-AI-CHARTER-2024** Arabic version of the UAE Charter for the Development and Use of AI (English ingested)
  - https://uaelegislation.gov.ae/en/policy/details/the-uae-charter-for-the-development-and-use-of-artificial-intelligence
    or ai.gov.ae -> `kb/raw/manual/AE-AI-CHARTER-2024.ar.pdf`
- [ ] **AE-NSAI-2031** Arabic: downloaded, but its PDF text layer breaks lam-alef joins (all 52 clauses failed QA).
  Optional: an Arabic text-layer copy from ai.gov.ae / u.ae -> `kb/raw/manual/AE-NSAI-2031.ar.pdf`

## Should
- [x] **AE-DOH-ADHICS** ADHICS (DoH Abu Dhabi) - doh.gov.ae reset the TLS connection
  - https://www.doh.gov.ae/-/media/032019_ADHICS.ashx (or the current version from the DoH standards page)
    -> `kb/raw/manual/AE-DOH-ADHICS.pdf` (or run `scripts/build_kb.py --retry-blocked` later)
- [x] **AE-FDL-4-2016** Federal Decree-Law No. 4 of 2016 on Medical Liability (its Executive Regulations, Cabinet
  Resolution 40/2019, are ingested) - uaelegislation.gov.ae -> `kb/raw/manual/AE-FDL-4-2016.pdf` (+ `.ar.pdf`)
- [x] **AE-TDRA-TELECOM-LAW** (now **AE-FDL-3-2003**) federal telecom law establishing TDRA - uaelegislation.gov.ae / tdra.gov.ae
  -> `kb/raw/manual/AE-TDRA-TELECOM-LAW.pdf` (put the instrument number in the manifest title)
- [x] **AE-CSC-NCS-2025** UAE National Cybersecurity Strategy - https://csc.gov.ae/ -> `kb/raw/manual/AE-CSC-NCS-2025.pdf`
- [x] **AE-DHA-AI-POLICY** DHA policy on AI in healthcare - https://www.dha.gov.ae/ -> `kb/raw/manual/AE-DHA-AI-POLICY.pdf`

## Could (Saudi pack)
- [ ] **SA-SDAIA-AI-ETHICS** SDAIA AI Ethics Principles - https://sdaia.gov.sa/ (server dropped plain requests)
  -> `kb/raw/manual/SA-SDAIA-AI-ETHICS.pdf`
- [ ] **SA-PDPL** Saudi Personal Data Protection Law - https://sdaia.gov.sa/ -> `kb/raw/manual/SA-PDPL.pdf`

## Then
```
.venv/bin/python scripts/build_kb.py --no-download
```
Check the new rows in `kb/sources/qa_samples.md` and `kb/sources/kb_stats.json` (Arabic files that come out
reversed or with broken letter joins are marked `extraction_failed` and kept out of `clauses.jsonl`).
