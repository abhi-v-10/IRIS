# AI-Based Invoice and Receipt Intelligence System (IRIS)

A web application that reads photos, scans and PDFs of invoices and receipts, extracts the vendor, date,
line items, tax and total with OCR, checks that the numbers add up, categorises each expense, and shows
spending summaries, trends and insights on a dashboard.

B.Tech CSE mini project, 2026-27.

---

## 1. Install (once)

### Step 1 – Tesseract OCR engine (required)

| OS | How |
|---|---|
| **Windows** | Download the installer from the UB Mannheim build: <https://github.com/UB-Mannheim/tesseract/wiki>. Install with the default options (it goes to `C:\Program Files\Tesseract-OCR`). The app finds it there automatically. |
| Ubuntu / Debian | `sudo apt install tesseract-ocr` |
| macOS | `brew install tesseract` |

If you install Tesseract somewhere else, set an environment variable `TESSERACT_CMD` to the full path of
`tesseract.exe` (Windows) or `tesseract` (macOS/Linux).

### Step 2 – Python 3.10 or newer

From <https://www.python.org/downloads/>. **On Windows, tick "Add python.exe to PATH"** in the installer.

## 2. Run

* **Windows:** double-click **`start_windows.bat`**.
* **macOS / Linux:** `./start_mac_linux.sh`

The first run creates a virtual environment and installs the packages (a few minutes, needs internet).
After that it starts in seconds and opens <http://127.0.0.1:5000> in your browser. Stop it with **Ctrl+C**.

Manual alternative:

```bash
python -m venv venv
venv\Scripts\activate            # Windows   (macOS/Linux: source venv/bin/activate)
pip install -r requirements.txt
python run.py
```

Options: `python run.py --port 8080`, and `python run.py --lan` to open it from a phone on the same Wi-Fi
(useful for photographing receipts directly; the address to use is printed at start-up).

## 3. Try it

1. Open the app and **create an account**.
2. On the dashboard click **Load sample documents**. Five bundled documents are processed:
   a GST tax invoice (PDF), a tilted restaurant bill photo, a pharmacy receipt, a blurred fuel receipt and a
   grocery bill. The fuel receipt is flagged for review because OCR misread its total – this demonstrates
   the validation step.
3. Or upload your own receipts on the **Upload** page (JPG, PNG, HEIC or PDF; several at once).

### Demo account with six months of data (for presentations)

```bash
python tools/seed_demo.py          # about one minute; then log in as demo@iris.local / demo1234
python tools/seed_demo.py --reset  # rebuild it from scratch
```

(Run it with the virtual environment active, e.g. `venv\Scripts\python tools\seed_demo.py` on Windows.)

### A 5-minute demo script for the viva

1. **Dashboard** – total spent, top category, monthly trend, category split, top vendors and the insights list.
2. **Upload** a receipt (a real photo from your phone works best) and point out the processing steps.
3. **Review page** – the original image beside the extracted fields, the OCR confidence bar, and *Show raw OCR text*.
4. Open **Metro Fuel Station** (needs review). The live check shows ₹520.00 ≠ ₹526.00. Change the total to 520,
   watch the check turn green, click **Save & verify**.
5. **Documents** – filter by category or date; **Export PDF** to show the generated report.
6. **Categories** – add a category with keywords, click *Re-apply to documents*.
7. **Settings & API** – show the API key and run one `curl` command (see section 5).

## 4. Features and where they are in the report

| Report requirement | Where in the app |
|---|---|
| FR1 Register / log in (hashed passwords) | Register and Log in pages |
| FR2 Accept JPG / PNG / HEIC (and PDF), reject other files | Upload page; unsupported or unreadable files get a clear error |
| FR3 Pre-processing (resize, denoise, deskew, threshold) | `iris/pipeline.py` → `preprocess()` |
| FR4 OCR | Tesseract via `pytesseract`; confidence shown on each document |
| FR5 Extract vendor, date, items, subtotal, tax, total (+ GSTIN, invoice no.) | `iris/pipeline.py` → `parse()` |
| FR6 Arithmetic validation and review flags | `validate()`; *Needs review* badge and messages |
| FR7 Automatic categorisation | Keyword scoring against **your own editable categories** |
| FR8 Correct extracted values → verified | Review page with editable fields and line items, live checks |
| FR9 Relational database | SQLite, schema in `iris/schema.sql` |
| FR10 Dashboard with filters | Dashboard: KPIs, monthly trend, category split, top vendors, insights, date/category filters |
| FR11 CSV / PDF export | Buttons on Dashboard and Documents (respect the current filters) |
| Manage categories (use case) | Categories page: add, edit keywords, delete, re-apply |
| Duplicate detection | Same vendor + date + total is flagged as a possible duplicate |
| REST API | Section 5 below |
| Security | Salted password hashes, CSRF tokens on every form, per-user data isolation, random file names, 15 MB upload limit |

## 5. REST API

Get your key from **Settings & API**, then:

```bash
curl -H "Authorization: Bearer YOUR_KEY" -F "file=@receipt.jpg" http://127.0.0.1:5000/api/upload
curl -H "Authorization: Bearer YOUR_KEY" "http://127.0.0.1:5000/api/documents?status=needs_review"
curl -H "Authorization: Bearer YOUR_KEY" http://127.0.0.1:5000/api/summary
curl -X PUT -H "Authorization: Bearer YOUR_KEY" -H "Content-Type: application/json" \
     -d "{\"total\": 520.00}" http://127.0.0.1:5000/api/documents/1
curl http://127.0.0.1:5000/api/health
```

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/upload` | Upload one or more files (field `file`); returns the extracted record(s) |
| GET | `/api/documents` | List documents; filters `date_from`, `date_to`, `category`, `status`, `q` |
| GET | `/api/documents/<id>` | One document with its line items and flags |
| PUT | `/api/documents/<id>` | Correct fields (and optionally `items`); marks it verified |
| DELETE | `/api/documents/<id>` | Delete the document and its file |
| GET | `/api/summary` | KPIs, spend by category, monthly totals, top vendors, insights |
| GET | `/api/health` | Whether the OCR engine is available (no key needed) |

## 6. Tests and evaluation

```bash
python -m pytest -v                        # 32 automated tests (parsing, validation, auth, upload, API, export...)
python tools/gen_receipts.py data_synth    # 60 labelled synthetic receipts in 4 image conditions
python tools/evaluate.py data_synth        # accuracy, precision/recall/F1, validator effectiveness, timing
python tools/make_samples.py               # rebuild the 5 documents in sample_receipts/
```

Optional browser test (report Section 7.3) and screenshot refresh – needs Playwright, which the app itself does not:

```bash
pip install playwright matplotlib && python -m playwright install chromium
python tools/browser_check.py              # register, upload, correct, export, log out – desktop and phone width
python tools/browser_check.py --shots      # also refresh the report screenshots (uses the demo account)
python report/make_charts.py               # redraw Figures 7.1 and 7.2 from report/data/report_data.json
```

## 7. Project structure

```
invoice-intelligence/
├── run.py                  start the web server
├── start_windows.bat       one-click start (Windows)
├── start_mac_linux.sh      one-click start (macOS / Linux)
├── requirements.txt
├── iris/                   the application
│   ├── __init__.py         app factory, error pages
│   ├── pipeline.py         AI pipeline: pre-process → OCR → parse → categorise → validate
│   ├── services.py         upload processing, duplicates, corrections, queries
│   ├── analytics.py        summaries, trends, insights
│   ├── export.py           CSV and PDF reports
│   ├── auth.py             registration, login, CSRF protection
│   ├── web.py              HTML pages
│   ├── api.py              REST API
│   ├── db.py, schema.sql   database
│   ├── templates/          HTML templates
│   └── static/             CSS, JavaScript, Chart.js (bundled, works offline)
├── sample_receipts/        5 demo documents (+ expected.json)
├── tools/                  gen_receipts, evaluate, make_samples, seed_demo, browser_check
├── tests/test_app.py       automated tests
└── instance/               created at runtime: database, uploaded files, secret key (not shared)
```

## 8. Troubleshooting

| Problem | Fix |
|---|---|
| "Tesseract OCR engine was not found" | Install it (Step 1). If installed in a custom folder, set `TESSERACT_CMD`. Restart the app. |
| `python` is not recognised (Windows) | Reinstall Python and tick "Add python.exe to PATH", or use `py` instead of `python`. |
| Port 5000 already in use | `python run.py --port 8080` |
| Poor extraction on a photo | Photograph the bill flat, in good light, filling the frame; avoid shadows. Correct any flagged values on the review page. |
| Start over with an empty database | Stop the app and delete the `instance` folder. |

## 9. Known limitations

* Rule-based extraction works best on printed, single-page English bills; handwritten bills and unusual layouts
  may need manual correction (the review page and validation flags are designed for this).
* Accuracy figures in the report come from synthetic receipts; real-world accuracy will be lower.
* Categories use keyword rules, not a trained model. Multi-page PDFs: only the first page is read.
* This is a single-machine prototype: for real deployment use HTTPS, a production WSGI server and PostgreSQL.
