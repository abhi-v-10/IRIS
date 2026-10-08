"""Automated tests for the Invoice & Receipt Intelligence System.   Run:  python -m pytest -v"""
import io
import json
import os
import re
from datetime import date

import pytest

from iris import create_app
from iris import pipeline as P

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES = os.path.join(ROOT, "sample_receipts")
P.configure_tesseract()
needs_ocr = pytest.mark.skipif(P.tesseract_version() is None, reason="Tesseract OCR is not installed")


# ============================================================== fixtures
@pytest.fixture()
def app(tmp_path):
    a = create_app({"TESTING": True, "SECRET_KEY": "test", "DATABASE": str(tmp_path / "t.db"),
                    "UPLOAD_FOLDER": str(tmp_path / "uploads")})
    os.makedirs(a.config["UPLOAD_FOLDER"], exist_ok=True)
    return a


def token(client, path="/login"):
    html = client.get(path).get_data(as_text=True)
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def register(client, name="Asha", email="asha@example.com", pw="secret1"):
    return client.post("/register", data=dict(csrf_token=token(client, "/register"), name=name, email=email,
                                              password=pw, confirm=pw))


def upload(client, *names):
    files = [(open(os.path.join(SAMPLES, n), "rb"), n) for n in names]
    try:
        return client.post("/upload", data={"csrf_token": token(client, "/upload"), "files": files},
                           content_type="multipart/form-data")
    finally:
        for f, _ in files:
            f.close()


# ============================================================== 1. pipeline unit tests
class TestParsing:
    def test_dates(self):
        assert P.parse_date("Date: 05/09/2026") == "2026-09-05"
        assert P.parse_date("Date: 5-9-2026") == "2026-09-05"
        assert P.parse_date("Dt 05.09.2026") == "2026-09-05"
        assert P.parse_date("Date: 05 Sep 2026") == "2026-09-05"
        assert P.parse_date("2026-09-05") == "2026-09-05"
        assert P.parse_date("Date: 05/09/26") == "2026-09-05"

    def test_impossible_date_rejected(self):
        assert P.parse_date("Date: 31/02/2026") is None

    def test_amount_formats(self):
        assert P.to_amount("1,450.00") == 1450.0
        assert P.to_amount("1575,00") == 1575.0        # comma as decimal point (OCR)
        assert P.to_amount("1740. 00") == 1740.0       # stray space (OCR)
        assert P.to_amount("1,23,456.50") == 123456.5  # Indian grouping

    def test_items(self):
        assert P.parse_items("Basmati Rice 5kg  2   1280.00") == [dict(name="Basmati Rice 5kg", qty=2, amount=1280.0)]
        assert P.parse_items("Veg Biryani      2  220.00  440.00") == [dict(name="Veg Biryani", qty=2, amount=440.0)]
        assert P.parse_items("Paneer Tikka I 260.00 260.00") == [dict(name="Paneer Tikka", qty=1, amount=260.0)]  # OCR: 1 -> I
        assert P.parse_items("Cough Syrup          120.00") == [dict(name="Cough Syrup", qty=1, amount=120.0)]
        assert P.parse_items("Wireless Mouse 8471 2 650.00 1300.00")[0]["name"] == "Wireless Mouse"   # HSN removed

    def test_summary_lines_are_not_items(self):
        assert P.parse_items("Subtotal  3  100.00\nGST 5%  5.00\nTOTAL  105.00\nCash  200.00") == []

    def test_total_and_tax(self):
        t = "Sub Total 1060.00\nCGST 2.5% 26.50\nSGST 2.5% 26.50\nGrand Total 1113.00"
        assert P.parse_total(t) == (1113.0, False)
        assert P.parse_tax(t) == 53.0
        assert P.parse_amount_line(t, r"sub\s*total") == 1060.0

    def test_amounts_are_not_taken_from_a_date_and_time(self):
        t = "Auth-Code : 112696\n15 Sep 2026, 08:51.54 AM\nRRN - 000000009515"
        assert P.parse_total(P.strip_times(t)) == (None, False)      # the old rule read '2026, 08' as 2026.08
        assert P.parse_date(t) == "2026-09-15"
        assert P.to_amount("50") == 50.0                             # amounts shorter than three characters

    def test_payment_slip(self):
        """Card and UPI slips: no 'Total' line, the amount sits alone under the heading."""
        t = "QUICKPAY\nPayment Successful\nRs 650\nPaid at Sunrise Fuel Station\nFrom ICICI Bank"
        assert P.parse_total(t) == (650.0, False)
        assert P.parse_vendor(t) == "Sunrise Fuel Station"           # the shop, not the payment app
        assert P.categorize(dict(vendor="Sunrise Fuel Station", items=[]),
                            list(P.DEFAULT_CATEGORIES.items())) == "Fuel"

    def test_fuel_slip_gets_one_implied_item(self):
        """Fuel slips print one amount and no item lines; the pipeline records a single 'Fuel' item."""
        rec = dict(vendor="Sunrise Fuel Station", items=[], subtotal=None, tax=None, total=650.0,
                   date="2026-09-15", ocr_confidence=90, total_guessed=False)
        rec["category"] = P.categorize(rec, list(P.DEFAULT_CATEGORIES.items()))
        P.implied_fuel_item(rec)
        assert rec["items"] == [dict(name="Fuel", qty=1, amount=650.0)]
        assert P.validate(rec, date(2026, 9, 30)) == []               # no 'no line items' flag any more

    def test_implied_item_only_for_fuel_with_a_total(self):
        rec = dict(category="Dining", items=[], total=650.0)
        assert P.implied_fuel_item(rec)["items"] == []
        rec = dict(category="Fuel", items=[], total=None)
        assert P.implied_fuel_item(rec)["items"] == []

    def test_vendor_ignores_ocr_rubble(self):
        assert P.parse_vendor("=F ON ee Wy WAZ\nFreshmart Supermarket") == "Freshmart Supermarket"

    def test_total_fallback_is_flagged(self):
        assert P.parse_total("Paid 40.00\nBill Amount 250.00") == (250.0, False)
        assert P.parse_total("Misc 40.00\nOther 250.00") == (250.0, True)

    def test_gstin_vendor_invoice(self):
        rec = P.parse(".. Circuit Point Electronics\nGSTIN: 36AAKFC4821M1Z3\nTAX INVOICE\nInvoice No: CPE/2026/0457")
        assert rec["vendor"] == "Circuit Point Electronics"
        assert rec["gstin"] == "36AAKFC4821M1Z3"
        assert rec["invoice_no"] == "CPE/2026/0457"


class TestValidationAndCategories:
    def rec(self, **kw):
        base = dict(items=[dict(name="a", qty=1, amount=100.0)], subtotal=100.0, tax=5.0, total=105.0,
                    date="2026-01-01", ocr_confidence=90)
        base.update(kw)
        return base

    def test_consistent_record_has_no_flags(self):
        assert P.validate(self.rec(), date(2026, 9, 30)) == []

    def test_mismatches(self):
        assert "total_mismatch" in P.validate(self.rec(total=120.0), date(2026, 9, 30))
        assert "items_sum_mismatch" in P.validate(self.rec(subtotal=90.0, total=95.0), date(2026, 9, 30))

    def test_no_tax_line_compares_items_with_total(self):
        assert "total_mismatch" in P.validate(self.rec(subtotal=None, tax=None, total=110.0), date(2026, 9, 30))

    def test_sanity_flags(self):
        f = P.validate(self.rec(date=None, total=None, items=[], ocr_confidence=40), date(2026, 9, 30))
        assert {"missing_date", "missing_total", "no_items_found", "low_ocr_confidence"} <= set(f)
        assert "date_in_future" in P.validate(self.rec(date="2027-01-01"), date(2026, 9, 30))

    def test_categorize(self):
        cats = list(P.DEFAULT_CATEGORIES.items())
        assert P.categorize(dict(vendor="CarePlus Pharmacy", items=[]), cats) == "Health"
        assert P.categorize(dict(vendor="Zzz Traders", items=[]), cats) == "Others"
        assert P.categorize(dict(vendor="X", items=[dict(name="steak")]), [("Groceries", "tea")]) == "Others"  # whole words


def test_crops_a_photographed_receipt_but_leaves_a_scan_alone():
    import numpy as np
    from PIL import Image
    page = np.array(Image.open(os.path.join(SAMPLES, "grocery_receipt.png")).convert("L"))
    assert P.document_quad(page) is None                    # a scan already fills the frame: nothing to cut
    desk = np.full((page.shape[0] * 3, page.shape[1] * 3), 60, np.uint8)   # the same page on a dark desk
    desk[200:200 + page.shape[0], 150:150 + page.shape[1]] = page
    assert P.document_quad(desk) is not None
    cropped = P.crop_document(desk)
    assert cropped.size < desk.size / 4 and abs(cropped.shape[0] - page.shape[0]) < 40


@needs_ocr
def test_sample_documents_end_to_end():
    expected = json.load(open(os.path.join(SAMPLES, "expected.json")))
    for name, exp in expected.items():
        rec = P.process(os.path.join(SAMPLES, name))
        assert rec["vendor"] == exp["vendor"], name
        assert rec["date"] == exp["date"], name
        if name == "fuel_receipt.jpg":                      # blurred: total is misread, and the validator catches it
            assert "total_mismatch" in rec["flags"]
        else:
            assert rec["total"] == pytest.approx(exp["total"]), name
            # the card slip is a fuel payment: one implied 'Fuel' item stands in for the missing item lines
            assert rec["flags"] == [], name
            if name == "card_payment_slip.jpg":
                assert rec["category"] == "Fuel" and rec["items"] == [dict(name="Fuel", qty=1, amount=rec["total"])]


# ============================================================== 2. authentication & security
def test_pages_require_login(app):
    c = app.test_client()
    for path in ("/", "/upload", "/documents", "/categories", "/settings", "/export.csv"):
        r = c.get(path)
        assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_register_login_logout(app):
    c = app.test_client()
    assert register(c).status_code == 302
    assert "Spending dashboard" in c.get("/dashboard").get_data(as_text=True)
    c.post("/logout", data={"csrf_token": token(c, "/dashboard")})
    assert c.get("/dashboard").status_code == 302
    bad = c.post("/login", data=dict(csrf_token=token(c), email="asha@example.com", password="wrong"))
    assert "Incorrect email or password" in bad.get_data(as_text=True)
    ok = c.post("/login", data=dict(csrf_token=token(c), email="ASHA@example.com", password="secret1"))
    assert ok.status_code == 302


def test_register_validation(app):
    c = app.test_client()
    register(c)
    c2 = app.test_client()
    r = c2.post("/register", data=dict(csrf_token=token(c2, "/register"), name="B", email="asha@example.com",
                                       password="secret1", confirm="secret1"))
    assert "already exists" in r.get_data(as_text=True)
    r = c2.post("/register", data=dict(csrf_token=token(c2, "/register"), name="B", email="b@example.com",
                                       password="123", confirm="123"))
    assert "at least 6" in r.get_data(as_text=True)


def test_passwords_are_hashed(app):
    register(app.test_client())
    import sqlite3
    row = sqlite3.connect(app.config["DATABASE"]).execute("SELECT password_hash FROM users").fetchone()
    assert "secret1" not in row[0] and row[0].startswith(("scrypt:", "pbkdf2:"))


def test_csrf_token_required(app):
    c = app.test_client()
    register(c)
    assert c.post("/categories", data=dict(action="add", name="Hack")).status_code == 400


# ============================================================== 3. upload, review, isolation
def test_rejects_unsupported_file(app):
    c = app.test_client()
    register(c)
    r = c.post("/upload", data={"csrf_token": token(c, "/upload"), "files": [(io.BytesIO(b"hello"), "notes.txt")]},
               content_type="multipart/form-data", follow_redirects=True)
    assert "not supported" in r.get_data(as_text=True)


def test_rejects_corrupt_image(app):
    c = app.test_client()
    register(c)
    r = c.post("/upload", data={"csrf_token": token(c, "/upload"), "files": [(io.BytesIO(b"not a png"), "fake.png")]},
               content_type="multipart/form-data", follow_redirects=True)
    assert "could not be read" in r.get_data(as_text=True)
    assert os.listdir(app.config["UPLOAD_FOLDER"]) == []          # nothing left behind


@needs_ocr
def test_upload_review_and_correct(app):
    c = app.test_client()
    register(c)
    r = upload(c, "fuel_receipt.jpg")
    assert r.status_code == 302 and "/documents/1" in r.headers["Location"]
    page = c.get("/documents/1").get_data(as_text=True)
    assert "Please check this document" in page and "needs review" in page
    r = c.post("/documents/1", data={"csrf_token": token(c, "/documents/1"), "vendor": "Metro Fuel Station",
                                     "date": "2026-09-17", "total": "520.00", "subtotal": "", "tax": "",
                                     "item_name": ["Petrol 5L"], "item_qty": ["1"], "item_amount": ["520.00"]},
               follow_redirects=True)
    assert "All checks pass" in r.get_data(as_text=True)
    import sqlite3
    row = sqlite3.connect(app.config["DATABASE"]).execute("SELECT status, total, flags FROM documents").fetchone()
    assert row == ("verified", 520.0, "[]")


@needs_ocr
def test_pdf_upload_and_duplicate_detection(app):
    c = app.test_client()
    register(c)
    upload(c, "gst_tax_invoice.pdf")
    upload(c, "gst_tax_invoice.pdf")
    import sqlite3
    rows = sqlite3.connect(app.config["DATABASE"]).execute(
        "SELECT preview_path IS NOT NULL, gstin, flags FROM documents ORDER BY doc_id").fetchall()
    assert rows[0][0] == 1 and rows[0][1] == "36AAKFC4821M1Z3" and rows[0][2] == "[]"
    assert "possible_duplicate" in rows[1][2]
    assert c.get("/documents/1/file").mimetype == "image/png"     # PDF preview is served to the browser


@needs_ocr
def test_heic_upload(app, tmp_path):
    pytest.importorskip("pillow_heif")
    from PIL import Image
    from pillow_heif import register_heif_opener
    register_heif_opener()
    Image.open(os.path.join(SAMPLES, "grocery_receipt.png")).convert("RGB").save(tmp_path / "bill.heic")
    c = app.test_client()
    register(c)
    with open(tmp_path / "bill.heic", "rb") as f:
        r = c.post("/upload", data={"csrf_token": token(c, "/upload"), "files": (f, "bill.heic")},
                   content_type="multipart/form-data")
    assert r.status_code == 302 and "/documents/1" in r.headers["Location"]
    import sqlite3
    row = sqlite3.connect(app.config["DATABASE"]).execute(
        "SELECT total, vendor, preview_path IS NOT NULL FROM documents").fetchone()
    assert row[0] == pytest.approx(1426.95) and row[1] == "Freshmart Supermarket" and row[2] == 1
    assert c.get("/documents/1/file").mimetype == "image/png"   # browsers cannot show HEIC, so the preview is served


@needs_ocr
def test_users_cannot_see_each_others_documents(app):
    a = app.test_client()
    register(a)
    upload(a, "pharmacy_receipt.png")
    b = app.test_client()
    register(b, name="Bala", email="bala@example.com")
    assert b.get("/documents/1").status_code == 404
    assert b.get("/documents/1/file").status_code == 404
    assert "Careplus" not in b.get("/documents").get_data(as_text=True)


@needs_ocr
def test_delete_removes_record_and_file(app):
    c = app.test_client()
    register(c)
    upload(c, "grocery_receipt.png")
    assert len(os.listdir(app.config["UPLOAD_FOLDER"])) == 1
    c.post("/documents/1/delete", data={"csrf_token": token(c, "/documents/1")})
    assert c.get("/documents/1").status_code == 404
    assert os.listdir(app.config["UPLOAD_FOLDER"]) == []


# ============================================================== 4. dashboard, filters, categories, export
@pytest.fixture()
def loaded(app):
    c = app.test_client()
    register(c)
    c.post("/upload/samples", data={"csrf_token": token(c, "/upload")})
    return c


@needs_ocr
def test_dashboard_and_filters(loaded, app):
    html = loaded.get("/dashboard").get_data(as_text=True)
    assert "Insights" in html and "largest expense head" in html and "chartMonthly" in html
    import sqlite3
    health = sqlite3.connect(app.config["DATABASE"]).execute(
        "SELECT category_id FROM categories WHERE name='Health'").fetchone()[0]
    only = loaded.get(f"/documents?category={health}").get_data(as_text=True)
    assert "Careplus Pharmacy" in only and "Freshmart" not in only
    dated = loaded.get("/documents?date_from=2026-09-20&date_to=2026-09-30").get_data(as_text=True)
    assert "Freshmart" in dated and "Careplus" not in dated
    assert "Metro Fuel" in loaded.get("/documents?status=needs_review").get_data(as_text=True)


@needs_ocr
def test_categories_add_edit_delete_reapply(loaded, app):
    t = token(loaded, "/categories")
    loaded.post("/categories", data=dict(csrf_token=t, action="add", name="Fuel", keywords="petrol diesel"))
    loaded.post("/categories", data=dict(csrf_token=t, action="recategorize"))
    import sqlite3
    db = sqlite3.connect(app.config["DATABASE"])
    q = "SELECT c.name FROM documents d JOIN categories c USING(category_id) WHERE d.vendor LIKE 'Metro Fuel%'"
    assert db.execute(q).fetchone()[0] in ("Fuel", "Transport")
    fuel = db.execute("SELECT category_id FROM categories WHERE name='Fuel'").fetchone()[0]
    loaded.post("/categories", data=dict(csrf_token=t, action="delete", category_id=fuel))
    assert db.execute("SELECT COUNT(*) FROM categories WHERE name='Fuel'").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM documents WHERE category_id IS NULL").fetchone()[0] == 0


@needs_ocr
def test_exports(loaded):
    csv_text = loaded.get("/export.csv").get_data(as_text=True)
    n_samples = len(json.load(open(os.path.join(SAMPLES, "expected.json"))))
    assert csv_text.lstrip("﻿").startswith("doc_id,date,vendor")
    assert csv_text.count("\n") == n_samples + 1                  # one header row + one row per document
    pdf = loaded.get("/export.pdf")
    assert pdf.data[:4] == b"%PDF" and "attachment" in pdf.headers["Content-Disposition"]


# ============================================================== 5. REST API
@needs_ocr
def test_rest_api(app):
    c = app.test_client()
    register(c)
    import sqlite3
    key = sqlite3.connect(app.config["DATABASE"]).execute("SELECT api_key FROM users").fetchone()[0]
    h = {"Authorization": f"Bearer {key}"}
    assert c.get("/api/health").get_json()["tesseract"]
    assert c.get("/api/summary").status_code == 401
    with open(os.path.join(SAMPLES, "restaurant_bill.jpg"), "rb") as f:
        r = c.post("/api/upload", headers=h, data={"file": (f, "bill.jpg")}, content_type="multipart/form-data")
    assert r.status_code == 201
    d = r.get_json()
    assert d["vendor"] == "Spice Route Restaurant" and d["total"] == 1113.0 and d["category"] == "Dining"
    assert len(d["items"]) == 4
    assert c.get("/api/documents", headers=h).get_json()["count"] == 1
    r = c.put(f"/api/documents/{d['doc_id']}", headers=h, json={"category": "Others"})
    assert r.get_json()["document"]["status"] == "verified" and r.get_json()["document"]["category"] == "Others"
    s = c.get("/api/summary", headers=h).get_json()
    assert s["kpis"]["documents"] == 1 and s["by_category"][0]["category"] == "Others"
    r = c.post("/api/upload", headers=h, data={"file": (io.BytesIO(b"x"), "a.txt")}, content_type="multipart/form-data")
    assert r.status_code == 400
    assert c.delete(f"/api/documents/{d['doc_id']}", headers=h).get_json() == {"deleted": d["doc_id"]}
    assert c.get(f"/api/documents/{d['doc_id']}", headers=h).status_code == 404


def test_app_restarts_on_existing_database(tmp_path):
    cfg = {"TESTING": True, "SECRET_KEY": "t", "DATABASE": str(tmp_path / "x.db"), "UPLOAD_FOLDER": str(tmp_path / "u")}
    create_app(cfg)
    create_app(cfg)          # the old prototype crashed here ("table users already exists")


@needs_ocr
def test_deskew_rescues_a_strongly_tilted_photo(tmp_path):
    from PIL import Image
    p = tmp_path / "tilted.png"
    Image.open(os.path.join(SAMPLES, "grocery_receipt.png")).convert("L").rotate(
        10, expand=True, fillcolor=255, resample=Image.BICUBIC).save(p)
    assert P.process(str(p))["total"] == pytest.approx(1426.95)
    img = P.load_image(str(p))
    text, _ = P.ocr(P.preprocess(img, deskew=False))
    assert P.parse(text)["total"] != pytest.approx(1426.95) or len(P.parse(text)["items"]) < 4  # fails without it
