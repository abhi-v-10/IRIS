# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Project context for Claude Code

This folder contains a college mini project, built together with Claude in a claude.ai chat and continued here.
Read this file first; it replaces the chat history.

## What this is

**AI-Based Invoice and Receipt Intelligence System (IRIS)** – B.Tech CSE mini project, Chaitanya (Deemed to be
University), Hyderabad, academic year 2026-27. Two deliverables:

1. **The working web app** (this folder): upload a photo/scan/PDF of a bill → OCR → extract fields → validate →
   categorize → dashboard with spending summaries, trends and insights.
2. **The project report** (`report/`): a ~30-page PDF (A4, Times, navy headings) that is printed and bound after the
   college's mandatory front pages (title, certificate, acknowledgement, declaration). Those front pages come from a
   college template and are NOT generated here; the report starts at the Abstract.

The student works on **Windows** (PowerShell, Python 3.13 in `venv/`). Keep every path and command Windows-friendly.

## Layout

| Path | What |
|---|---|
| `run.py` | Start the app: `python run.py` (options `--port`, `--lan`, `--debug`) → http://127.0.0.1:5000 |
| `start_windows.bat`, `start_mac_linux.sh` | One-click start (creates `venv`, installs requirements) |
| `iris/pipeline.py` | AI pipeline: load (PDF via pypdfium2) → preprocess (OpenCV) → OCR (Tesseract, confidence) → parse → categorize → validate |
| `iris/services.py` | Upload processing, duplicate detection, corrections (→ status `verified`), filtered queries, delete, re-categorize |
| `iris/analytics.py` | KPIs, category/month/vendor aggregation, plain-language insights, Indian money format |
| `iris/export.py` | CSV and PDF report export |
| `iris/auth.py` | Register/login (werkzeug scrypt hashes), CSRF tokens on all forms, `login_required` |
| `iris/web.py`, `iris/api.py` | HTML pages / REST API (Bearer API key per user) |
| `iris/db.py`, `iris/schema.sql` | SQLite; tables users, categories (per user, keywords), documents, line_items |
| `iris/templates/`, `iris/static/` | Jinja2 templates, `style.css`, `app.js`, Chart.js bundled locally (works offline) |
| `sample_receipts/` | 6 demo documents + `expected.json` (made by `tools/make_samples.py`) |
| `tools/` | `gen_receipts.py` (60 labelled synthetic receipts, fixed seed), `evaluate.py`, `make_samples.py`, `seed_demo.py`, `browser_check.py` (Playwright workflow test + report screenshots), `fonts/` (bundled DejaVu fonts) |
| `tests/test_app.py` | 38 pytest tests (parsing, validation, security, upload/review incl. HEIC, dashboard, export, API, deskew) |
| `instance/` | Created at runtime: `iris.db`, `uploads/`, `secret_key`. Delete it to reset. Never ship it. |
| `report/` | Report source – see below |

## Common commands

```powershell
python run.py                                   # run the app
python -m pytest -q                             # all tests (~50 s; needs Tesseract)
python -m pytest -q -k test_categorize          # one test / one pattern
python -m pytest -q tests/test_app.py::TestValidationAndCategories   # one class
python tools/seed_demo.py --reset               # demo account demo@iris.local / demo1234, 41 docs over 6 months
python tools/gen_receipts.py data_synth         # regenerate the 60 test receipts (deterministic)
python tools/evaluate.py data_synth             # accuracy numbers
python report/collect_results.py                # re-measure all report numbers -> report/data/report_data.json
python report/build.py                          # rebuild the report PDF -> report/AI_Invoice_Receipt_Intelligence_Mini_Project_Report.pdf
# optional (need `pip install playwright matplotlib` + `python -m playwright install chromium`, not in requirements.txt):
python tools/browser_check.py --shots           # browser workflow test + refresh report/fig/s_*.png and report/data/api_upload.json
python report/make_charts.py                    # redraw report/fig/results.png and deskew.png from report_data.json
```

Full refresh after a pipeline or OCR-engine change: pytest → evaluate → collect_results → `seed_demo.py --reset` →
`browser_check.py --shots` → `make_charts.py` → build. `content*.py` call `check(...)`, which stops the build if a
re-measurement no longer supports a sentence written in words (e.g. "four of five samples correct") – then edit the prose.

Tesseract must be installed (Windows default path `C:\Program Files\Tesseract-OCR` is auto-detected; otherwise set
`TESSERACT_CMD`).

## The report (`report/`)

- Built with ReportLab: `build.py` assembles `content1.py` (abstract, contents, Ch 1–2), `content2.py` (Ch 3–5),
  `content3.py` (Ch 6–8, references, appendices A–C); `rlh.py` has the layout helpers (`CH`, `H2`, `P`, `B`, `N`,
  `TAB`, `FIG`, `CODE`, `APPX`) and the page header/footer. Page numbers: roman for front matter, arabic from Ch 1.
- Numbers in the text come from `report/data/report_data.json` (produced by `collect_results.py`), not typed by hand.
  If the pipeline changes, re-run evaluate → collect_results → build so the report never disagrees with the app.
- `report/fig/` holds pre-rendered diagrams, charts and app screenshots (PNG). Screenshots come from the demo account
  at 1280 px width, 2x scale, via `tools/browser_check.py --shots` (crop heights keep the original aspect ratios so the
  page flow stays the same). `s_categories`, `s_dash_bottom`, `s_export_pdf`, `s_login`, `s_settings`, `gantt`, `dfd0`
  are not used in the report.
- Student's preferences: **about 30 pages total**; **no List of Figures / List of Tables**; keep it compact – no
  padding, no repeated explanations. Current state: 32 pages (3 front + 29 body).
- Times-Roman has no ₹ glyph: write "Rs." in report prose. The code font ("Mono", DejaVu) does support ₹.
- Keep the honest framing: accuracy is measured on **synthetic** receipts, so it is a proof of concept.

## Key results (as in the report)

Measured on 2026-10-01 with Tesseract 5.5.3, OpenCV 4.14, Python 3.13 (Windows). Earlier numbers (Tesseract 5.3.4)
differed: the OCR engine version changes results, so re-measure after any Tesseract upgrade.

60 synthetic receipts, 4 conditions (clean / blur / rotate <3° / speckle): vendor 98.3%, date 98.3% (one rotated
receipt with no date found, flagged missing_date), total 100%, line-item F1 89.3%, ~0.57 s per receipt. Validator
flagged every record with a wrong number (2 of 18 records with any error; the other 16 had only misspelt item names,
two also with an unread subtotal line but no wrong number) with 0 false alarms. 5 of 6 realistic samples fully
correct; the blurred fuel receipt (blur 1.1 in make_samples.py; total misread 520→526) is correctly flagged. The
restaurant bill's GSTIN now reads correctly with Tesseract 5.5.3. Deskew: always rotating small tilts gives F1 84.7%
vs 89.8% without; at 12° item recall is 0% without deskew and 96.7% with it.

## Design decisions worth knowing

- **Deskew only when tilt ≥ 3°** (`MIN_SKEW` in `pipeline.py`). Measured: rotating small tilts lowered item F1
  (84.7% vs 89.8%); at 12° tilt, item recall is 0% without deskew and 96.7% with it. `rotate_bound` enlarges the canvas
  so corners aren't cut off (the first version cut them off).
- **Categories live per user in the DB**, seeded from `pipeline.DEFAULT_CATEGORIES` at registration. `db.init_db`
  also migrates existing databases: it inserts default categories added later, and rewrites a keyword list only when
  it still exactly matches a retired default (`db.RETIRED_KEYWORDS`), so user edits survive. Add a default category
  by editing `DEFAULT_CATEGORIES`; if it takes keywords away from another category, put the old string in
  `RETIRED_KEYWORDS` too.
- **Fuel is its own category** (split out of Transport). Fuel bills are usually payment slips with one amount and no
  item lines, so `pipeline.implied_fuel_item` records a single `Fuel` item for the total; this clears the
  `no_items_found` flag and makes the arithmetic check pass. It runs in `process()` only, not on re-categorize.
- **Validation is the core idea**: items = subtotal, subtotal (or items) + tax = total; plus missing/future date,
  guessed total, no items, low OCR confidence (<60), possible duplicate. Any flag → status `needs_review`.
- Extraction and categorization are **rule-based** (regex + keyword anchors; whole-word keyword scoring). The "AI" is
  Tesseract's LSTM OCR. LayoutLM/Donut and a learned categorizer are listed as future work.
- `requirements.txt` pins `opencv-python-headless<5`: OpenCV 5 changed results slightly. 4.13 vs 4.14 made no
  difference to the tests; the Tesseract version matters much more (see Key results).
- Item parsing treats a quantity read as `I`, `l` or `|` in the name-qty-rate-amount layout as 1 (Tesseract 5.5.3
  reads the restaurant bill's "1" as "I").
- Fonts are bundled in `tools/fonts/` because Windows has no `/usr/share/fonts` (this caused an `OSError: cannot open
  resource` in `seed_demo.py` before the fix).

## Still to do (student's side)

- Fill team names, roll numbers and guide into the college front pages; optionally merge them in front of the report PDF.
- Optional but valuable for the viva: test on 20–30 real receipt photos and report those results too.
