"""Browser workflow test (report Section 7.3) and the report screenshots, using Playwright + headless Chromium.

    pip install playwright && python -m playwright install chromium      (once; not needed to run the app)
    python tools/seed_demo.py --reset                                      (screenshots use the demo account)
    python tools/browser_check.py              -> workflow test at desktop and phone width
    python tools/browser_check.py --shots      -> also refresh the screenshots in report/fig/ and report/data/api_upload.json

The workflow test runs against a temporary database, so it never touches your own data.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

from playwright.sync_api import expect, sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES = os.path.join(ROOT, "sample_receipts")
FIG = os.path.join(ROOT, "report", "fig")
APP_PY = os.environ.get("IRIS_PYTHON", sys.executable)     # Python that has the app's requirements installed


def start_server(port, db=None):
    code = ("import sys; sys.path.insert(0, %r); from iris import create_app; "
            "cfg = %r; app = create_app(cfg or None); app.run(port=%d)" %
            (ROOT, dict(DATABASE=os.path.join(db, "t.db"), UPLOAD_FOLDER=os.path.join(db, "up")) if db else {}, port))
    proc = subprocess.Popen([APP_PY, "-c", code], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1)
            return proc
        except OSError:
            time.sleep(0.2)
    proc.kill()
    raise SystemExit("The app did not start.")


def workflow(browser, base, width, height, tag):
    """Register, upload two files, correct the flagged receipt, edit items, add a category, export, log out."""
    ctx = browser.new_context(viewport=dict(width=width, height=height), accept_downloads=True)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: m.type == "error" and errors.append(m.text))
    step = lambda s: print(f"  [{tag}] {s}")                                   # noqa: E731

    page.goto(base + "/register")
    page.fill("#name", "Browser Test"); page.fill("#email", f"{tag}@example.com")
    page.fill("#password", "secret1"); page.fill("#confirm", "secret1")
    page.click("button[type=submit]")
    expect(page.locator("h1")).to_have_text("Spending dashboard"); step("registered")

    page.goto(base + "/upload")
    page.set_input_files("#files", [os.path.join(SAMPLES, "restaurant_bill.jpg"), os.path.join(SAMPLES, "fuel_receipt.jpg")])
    expect(page.locator("#upload-hint")).to_have_text("2 files selected")
    page.click("#upload-btn")
    expect(page.locator(".alert-success")).to_contain_text("2 document(s) processed"); step("uploaded two files")

    page.goto(base + "/documents?status=needs_review")
    page.click("text=Metro Fuel Station")
    expect(page.locator("#chk-total")).to_have_class("bad"); step("flagged receipt: total check is red")
    page.fill("#total", "520.00")
    expect(page.locator("#chk-total")).to_have_class("ok"); step("typed 520.00: check turned green live")
    page.click("#add-item")
    page.locator("#items tbody tr:last-child input[name=item_name]").fill("Test item")
    page.locator("#items tbody tr:last-child input[name=item_amount]").fill("10")
    expect(page.locator("#chk-total")).to_have_class("bad")
    page.locator("#items tbody tr:last-child [data-remove]").click()
    expect(page.locator("#chk-total")).to_have_class("ok"); step("added and removed an item")
    page.click("button:has-text('Save & verify')")
    expect(page.locator(".alert-success")).to_contain_text("All checks pass"); step("saved: verified")

    page.goto(base + "/categories")
    page.fill("#new-name", "Education"); page.fill("#new-kw", "books stationery tuition")
    page.click("button:has-text('Add category')")
    expect(page.locator(".alert-success")).to_contain_text("Category 'Education' added"); step("added a category")

    page.goto(base + "/documents")
    for label, ext in (("Export CSV", ".csv"), ("Export PDF", ".pdf")):
        with page.expect_download() as dl:
            page.click(f"text={label}")
        assert dl.value.suggested_filename.endswith(ext)
    step("exported CSV and PDF")

    page.goto(base + "/")
    page.locator("form[action='/logout'] button").click()
    expect(page.locator(".alert-success")).to_contain_text("logged out"); step("logged out")
    ctx.close()
    return errors


def screenshots(browser, base):
    import sqlite3
    db = sqlite3.connect(os.path.join(ROOT, "instance", "iris.db"))
    uid, key = db.execute("SELECT user_id, api_key FROM users WHERE email='demo@iris.local'").fetchone()
    doc = lambda name: db.execute("SELECT doc_id FROM documents WHERE user_id=? AND original_name=?",  # noqa: E731
                                  (uid, name)).fetchone()[0]

    def login(ctx):
        page = ctx.new_page()
        page.goto(base + "/login")
        page.fill("#email", "demo@iris.local"); page.fill("#password", "demo1234")
        page.click("button[type=submit]")
        return page

    def shot(page, name, height=None):
        page.wait_for_timeout(700)                                        # let Chart.js finish its animation
        box = page.locator("main").bounding_box()
        page.screenshot(path=os.path.join(FIG, name), full_page=True,
                        clip=dict(x=box["x"], y=box["y"], width=box["width"], height=height or box["height"]))
        print("  saved", name)

    ctx = browser.new_context(viewport=dict(width=1280, height=900), device_scale_factor=2)
    page = login(ctx)
    page.goto(base + "/"); shot(page, "s_dash_top.png", 780)
    page.goto(base + "/upload")
    page.set_input_files("#files", [os.path.join(SAMPLES, "restaurant_bill.jpg"), os.path.join(SAMPLES, "gst_tax_invoice.pdf")])
    shot(page, "s_upload.png", 560)
    page.goto(base + f"/documents/{doc('fuel_receipt.jpg')}"); shot(page, "s_review_flagged.png")
    page.goto(base + f"/documents/{doc('gst_tax_invoice.pdf')}")
    page.click("details.ocr summary"); shot(page, "s_review_pdf.png")
    page.goto(base + "/documents"); shot(page, "s_documents.png", 900)
    ctx.close()

    from PIL import Image
    ctx = browser.new_context(viewport=dict(width=390, height=844), device_scale_factor=2)
    page = login(ctx)
    parts = []
    for i, path in enumerate(("/", "/upload", f"/documents/{doc('restaurant_bill.jpg')}")):
        page.goto(base + path); page.wait_for_timeout(700)
        p = os.path.join(tempfile.gettempdir(), f"iris_mobile_{i}.png")
        page.screenshot(path=p); parts.append(Image.open(p))
    gap = 40
    out = Image.new("RGB", (sum(p.width for p in parts) + gap * 2, parts[0].height), "white")
    for i, p in enumerate(parts):
        out.paste(p, (i * (p.width + gap), 0))
    out.save(os.path.join(FIG, "s_mobile.png")); print("  saved s_mobile.png")
    ctx.close()

    # Appendix C: upload the restaurant bill again through the REST API (it is flagged as a duplicate), then remove it
    body, boundary = open(os.path.join(SAMPLES, "restaurant_bill.jpg"), "rb").read(), "IRISBOUNDARY"
    data = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"restaurant_bill.jpg\"\r\n"
            f"Content-Type: image/jpeg\r\n\r\n").encode() + body + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(base + "/api/upload", data=data, method="POST", headers={
        "Authorization": f"Bearer {key}", "Content-Type": f"multipart/form-data; boundary={boundary}"})
    rec = json.load(urllib.request.urlopen(req))
    json.dump(rec, open(os.path.join(ROOT, "report", "data", "api_upload.json"), "w", encoding="utf-8"), ensure_ascii=False)
    urllib.request.urlopen(urllib.request.Request(f"{base}/api/documents/{rec['doc_id']}", method="DELETE",
                                                  headers={"Authorization": f"Bearer {key}"}))
    print("  saved report/data/api_upload.json (flags: %s)" % rec["flags"])


def main():
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw:
        browser = pw.chromium.launch()
        server = start_server(5055, db=tmp)
        try:
            print("Browser workflow test")
            errors = workflow(browser, "http://127.0.0.1:5055", 1280, 900, "desktop")
            errors += workflow(browser, "http://127.0.0.1:5055", 390, 844, "phone")
            print("JavaScript errors:", errors or "none")
        finally:
            server.terminate()
        if "--shots" in sys.argv:
            print("Screenshots (demo account)")
            server = start_server(5056)
            try:
                screenshots(browser, "http://127.0.0.1:5056")
            finally:
                server.terminate()
        browser.close()
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
