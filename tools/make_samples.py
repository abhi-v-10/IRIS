"""Create realistic demo documents in sample_receipts/ (run: python tools/make_samples.py).

  1. gst_tax_invoice.pdf   - A4 GST tax invoice (GSTIN, invoice no, HSN, CGST + SGST)
  2. restaurant_bill.jpg   - restaurant bill with qty / rate / amount columns, slight tilt and noise
  3. pharmacy_receipt.png  - pharmacy receipt with a '05 Sep 2026' style date and no quantity column
  4. fuel_receipt.jpg      - short fuel receipt photographed with blur
  5. grocery_receipt.png   - supermarket receipt (same layout family as the test set)
  6. card_payment_slip.jpg - card/UPI payment slip photographed on a dark desk: no line items, no 'Total'
                             keyword, the amount printed large under 'Payment Successful'
"""
import os
import random

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sample_receipts")
FONTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")   # bundled: works on Windows too
MONO = os.path.join(FONTS, "DejaVuSansMono.ttf")
MONO_B = os.path.join(FONTS, "DejaVuSansMono-Bold.ttf")
random.seed(11)


def font(path, size):
    return ImageFont.truetype(path, size)


def paper(lines, width=560, fsize=21, bold_rows=(), f=MONO):
    fn, fb = font(f, fsize), font(MONO_B, fsize)
    h = 70 + len(lines) * int(fsize * 1.55)
    img = Image.new("L", (width, h), 250)
    d = ImageDraw.Draw(img)
    for k, line in enumerate(lines):
        d.text((24, 34 + k * int(fsize * 1.55)), line, font=fb if k in bold_rows else fn, fill=25)
    return img


def photo_effects(img, angle=0.0, blur=0.0, noise=0.0, bg=150):
    """Put the paper on a darker background, tilt it and add blur/noise like a phone photo."""
    canvas_img = Image.new("L", (img.width + 120, img.height + 120), bg)
    canvas_img.paste(img, (60, 60))
    if angle:
        canvas_img = canvas_img.rotate(angle, expand=True, fillcolor=bg, resample=Image.BICUBIC)
    if blur:
        canvas_img = canvas_img.filter(ImageFilter.GaussianBlur(blur))
    if noise:
        a = np.array(canvas_img).astype(int) + np.random.default_rng(3).normal(0, noise, (canvas_img.height, canvas_img.width)).astype(int)
        canvas_img = Image.fromarray(a.clip(0, 255).astype("uint8"))
    return canvas_img.convert("RGB")


def gst_invoice_pdf(path):
    c = canvas.Canvas(path, pagesize=A4)
    w, h = A4
    y = h - 60
    c.setFont("Helvetica-Bold", 18); c.drawString(50, y, "Circuit Point Electronics"); y -= 18
    c.setFont("Helvetica", 10)
    for t in ["Plot 14, Madhapur, Hyderabad, Telangana 500081", "GSTIN: 36AAKFC4821M1Z3"]:
        c.drawString(50, y, t); y -= 14
    y -= 8
    c.setFont("Helvetica-Bold", 14); c.drawString(50, y, "TAX INVOICE"); y -= 20
    c.setFont("Helvetica", 10.5)
    c.drawString(50, y, "Invoice No: CPE/2026/0457"); c.drawString(330, y, "Date: 14/08/2026"); y -= 14
    c.drawString(50, y, "Bill To: Ravi Kumar, Kukatpally, Hyderabad"); y -= 26
    c.setFont("Helvetica-Bold", 10.5)
    cols = [50, 280, 330, 400, 480]
    for x, t in zip(cols, ["Description", "HSN", "Qty", "Rate", "Amount"]):
        c.drawString(x, y, t)
    y -= 6; c.line(50, y, 545, y); y -= 16
    c.setFont("Helvetica", 10.5)
    rows = [("Wireless Mouse", "8471", 2, 650.00), ("USB C Cable", "8544", 3, 249.00),
            ("Laptop Stand", "8473", 1, 1350.00), ("Power Bank 10000mAh", "8507", 1, 1499.00)]
    sub = 0
    for name, hsn, q, rate in rows:
        amt = q * rate; sub += amt
        c.drawString(cols[0], y, name); c.drawString(cols[1], y, hsn); c.drawString(cols[2], y, str(q))
        c.drawRightString(cols[3] + 50, y, f"{rate:.2f}"); c.drawRightString(cols[4] + 60, y, f"{amt:.2f}")
        y -= 16
    c.line(50, y + 6, 545, y + 6); y -= 8
    cgst = round(sub * 0.09, 2); sgst = cgst; total = sub + cgst + sgst
    for label, val in [("Taxable Value", sub), ("CGST @ 9%", cgst), ("SGST @ 9%", sgst), ("Grand Total", total)]:
        c.setFont("Helvetica-Bold" if label == "Grand Total" else "Helvetica", 10.5)
        c.drawString(330, y, label); c.drawRightString(540, y, f"{val:.2f}"); y -= 16
    y -= 20; c.setFont("Helvetica", 9); c.drawString(50, y, "Thank you for your business. Goods once sold will not be taken back.")
    c.save()
    return dict(vendor="Circuit Point Electronics", total=total, date="2026-08-14", subtotal=sub, tax=cgst + sgst)


def restaurant(path):
    lines = ["SPICE ROUTE RESTAURANT", "Banjara Hills, Hyderabad", "GSTIN: 36ABFPS7719K1ZQ",
             "Bill No: SR-2231   Date: 21/09/2026", "-" * 38, "Item           Qty   Rate   Amount", "-" * 38,
             "Paneer Tikka     1  260.00  260.00", "Veg Biryani      2  220.00  440.00", "Butter Naan      4   45.00  180.00",
             "Sweet Lime Soda  2   90.00  180.00", "-" * 38, "Sub Total              1060.00", "CGST 2.5%                26.50",
             "SGST 2.5%                26.50", "Grand Total            1113.00", "-" * 38, "Thank you! Visit again"]
    photo_effects(paper(lines, bold_rows=(0, 15)), angle=-2.2, noise=10).save(path, quality=90)
    return dict(vendor="Spice Route Restaurant", total=1113.00, date="2026-09-21", subtotal=1060.00, tax=53.00)


def pharmacy(path):
    lines = ["CAREPLUS PHARMACY", "Ameerpet, Hyderabad", "Date: 05 Sep 2026", "Invoice No: CP88213", "-" * 34,
             "Paracetamol 650mg     32.00", "Vitamin C Tablets    180.00", "Cough Syrup          120.00", "Hand Sanitizer        95.00",
             "-" * 34, "Subtotal             427.00", "GST 12%               51.24", "TOTAL                478.24", "Get well soon"]
    paper(lines, width=500, bold_rows=(0, 12)).convert("RGB").save(path)
    return dict(vendor="Careplus Pharmacy", total=478.24, date="2026-09-05", subtotal=427.00, tax=51.24)


def fuel(path):
    lines = ["METRO FUEL STATION", "Hitec City, Hyderabad", "Date: 17-09-2026", "Receipt No: MF0932", "-" * 30,
             "Petrol 5L         520.00", "-" * 30, "TOTAL             520.00", "Paid by UPI"]
    photo_effects(paper(lines, width=460, bold_rows=(0, 7)), angle=1.2, blur=1.0).save(path, quality=88)
    return dict(vendor="Metro Fuel Station", total=520.00, date="2026-09-17", subtotal=None, tax=None)


def grocery(path):
    lines = ["FRESHMART SUPERMARKET", "GSTIN: 36ABCDE1234F1Z5", "Date: 28/09/2026", "Bill No: 50412", "-" * 34,
             "Basmati Rice 5kg      1     640.00", "Toned Milk 1L         4     224.00", "Whole Wheat Atta      1     285.00",
             "Tea Powder            1     210.00", "-" * 34, "Subtotal                  1359.00", "GST 5%                      67.95",
             "TOTAL                     1426.95", "-" * 34, "Thank you! Visit again"]
    paper(lines, width=520, fsize=20).convert("RGB").save(path)
    return dict(vendor="Freshmart Supermarket", total=1426.95, date="2026-09-28", subtotal=1359.00, tax=67.95)


def card_payment_slip(path):
    """A POS slip as a phone photo: small piece of paper on a dark desk, tilted, so the pipeline has to
    find the paper first. The amount has no 'Total' label and no paise, and there are no line items."""
    lines = ["QUICKPAY", "Payment Successful", "Rs 650", "Paid at Sunrise Fuel Station",
             "From ICICI Bank", "-" * 28, "Auth-Code : 112696", "15 Sep 2026, 08:51:54 AM",
             "RRN - 000000009515", "-" * 28, "Payment Details", "Txn ID    2026091501103000",
             "Card No.  XXXXXXXXXXXX6124", "Card Type VISA", "Trans Type SALE", "-" * 28, "Customer Copy"]
    img = paper(lines, width=430, fsize=18, bold_rows=(0, 1, 2))
    photo_effects(img, angle=-6.5, blur=0.6, noise=6, bg=55).save(path, quality=90)
    return dict(vendor="Sunrise Fuel Station", total=650.00, date="2026-09-15", subtotal=None, tax=None)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    truth = {
        "gst_tax_invoice.pdf": gst_invoice_pdf(os.path.join(OUT, "gst_tax_invoice.pdf")),
        "restaurant_bill.jpg": restaurant(os.path.join(OUT, "restaurant_bill.jpg")),
        "pharmacy_receipt.png": pharmacy(os.path.join(OUT, "pharmacy_receipt.png")),
        "fuel_receipt.jpg": fuel(os.path.join(OUT, "fuel_receipt.jpg")),
        "grocery_receipt.png": grocery(os.path.join(OUT, "grocery_receipt.png")),
        "card_payment_slip.jpg": card_payment_slip(os.path.join(OUT, "card_payment_slip.jpg")),
    }
    import json
    json.dump(truth, open(os.path.join(OUT, "expected.json"), "w"), indent=1)
    print("created", len(truth), "sample documents in", OUT)
