"""AI pipeline of the Invoice & Receipt Intelligence System (IRIS).

    load image (JPG/PNG/HEIC, or first page of a PDF)
      -> pre-process (find the sheet of paper, flatten it, resize, denoise, deskew, threshold)
      -> OCR with Tesseract (text + per-word confidence)
      -> parse fields (vendor, GSTIN, invoice no, date, items, subtotal, tax, total)
      -> categorize (keyword scoring against the user's categories)
      -> validate (arithmetic and sanity checks -> review flags)

A photo of a small till receipt lying on a desk is mostly background, so `crop_document` locates the paper
and warps it flat before anything else. Because one set of pre-processing settings cannot suit both a clean
PDF and a creased thermal slip, `process` reads the page with up to three settings and keeps the reading whose
numbers hang together best (`read_score`).
"""
import os
import re
import shutil
from datetime import date

import cv2
import numpy as np
import pytesseract

ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".heic", ".heif", ".pdf"}
HEIC_EXTENSIONS = {".heic", ".heif"}      # iPhone / recent Android photos; browsers cannot show them, so a PNG preview is made
MIN_SKEW = 3.0          # degrees; measured in the evaluation (report Section 7.5)
CROP_MIN, CROP_MAX = 0.04, 0.90   # crop only when the paper covers 4-90% of the frame (above that it is a scan)


# ----------------------------------------------------------------- Tesseract setup
def configure_tesseract():
    """Find the Tesseract executable (TESSERACT_CMD env var, PATH, or default install folders)."""
    cmd = os.environ.get("TESSERACT_CMD")
    if not cmd and not shutil.which("tesseract"):
        for p in (r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                  r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
                  "/opt/homebrew/bin/tesseract", "/usr/local/bin/tesseract"):
            if os.path.exists(p):
                cmd = p
                break
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd


def tesseract_version():
    try:
        return str(pytesseract.get_tesseract_version())
    except Exception:
        return None


# ----------------------------------------------------------------- 1. loading
def load_image(path):
    """Return a grayscale numpy image. PDFs are rendered (page 1) at 200 dpi; HEIC/HEIF photos are decoded with
    pillow-heif and turned upright using their EXIF orientation (phones store photos sideways)."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(path)
        try:
            img = np.array(pdf[0].render(scale=200 / 72).to_pil().convert("L"))
        finally:
            pdf.close()
    elif ext in HEIC_EXTENSIONS:
        try:
            from PIL import Image, ImageOps
            from pillow_heif import register_heif_opener
        except ImportError as exc:
            raise ValueError("HEIC support needs the pillow-heif package (pip install pillow-heif).") from exc
        register_heif_opener()
        with Image.open(path) as im:
            img = np.array(ImageOps.exif_transpose(im).convert("L"))
    else:
        img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError("The file could not be read as an image.")
    return img


def save_preview(path, out_path):
    """Save a PNG preview (used for PDFs and HEIC photos, which the browser cannot show itself)."""
    cv2.imwrite(out_path, load_image(path))
    return out_path


# ----------------------------------------------------------------- 2. pre-processing
def deskew_angle(gray):
    """Estimate the skew of the text block in degrees (0 if unsure)."""
    inv = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    coords = np.column_stack(np.where(inv > 0))
    if len(coords) < 50:
        return 0.0
    rect = cv2.minAreaRect(coords[:, ::-1].astype(np.float32))   # (x, y) points
    (w, h), ang = rect[1], rect[2]
    if w < h:                       # normalise so the angle describes the long (text-line) side
        ang -= 90
    if ang < -45:
        ang += 90
    if ang > 45:
        ang -= 90
    return ang if 0.3 < abs(ang) < 15 else 0.0


def rotate_bound(img, ang):
    """Rotate without cutting off the corners (the canvas grows to fit)."""
    h, w = img.shape
    m = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0)
    cos, sin = abs(m[0, 0]), abs(m[0, 1])
    nw, nh = int(h * sin + w * cos), int(h * cos + w * sin)
    m[0, 2] += nw / 2 - w / 2
    m[1, 2] += nh / 2 - h / 2
    return cv2.warpAffine(img, m, (nw, nh), flags=cv2.INTER_CUBIC, borderValue=255)


def _order_quad(pts):
    """Corners as top-left, top-right, bottom-right, bottom-left."""
    pts = pts.reshape(4, 2).astype(np.float32)
    s, d = pts.sum(1), np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]], np.float32)


def document_quad(gray):
    """Corners of the sheet of paper in a photo, or None if the page already fills the frame (a scan or PDF)."""
    sc = 900 / max(gray.shape)
    small = cv2.resize(gray, None, fx=sc, fy=sc, interpolation=cv2.INTER_AREA)
    k = max(4, int(0.02 * max(small.shape)))          # a scan or PDF has bright paper right out to the edges,
    border = np.concatenate([small[:k].ravel(), small[-k:].ravel(),   # so there is nothing to cut away
                             small[:, :k].ravel(), small[:, -k:].ravel()])
    if np.median(border) > 180:
        return None
    th = cv2.threshold(cv2.GaussianBlur(small, (7, 7), 0), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, np.ones((11, 11), np.uint8))   # join the text back into one blob
    cnts = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]
    if not cnts:
        return None
    paper = max(cnts, key=cv2.contourArea)
    if not CROP_MIN < cv2.contourArea(paper) / small.size < CROP_MAX:
        return None
    approx = cv2.approxPolyDP(paper, 0.02 * cv2.arcLength(paper, True), True)
    if len(approx) != 4:            # a creased or partly hidden edge: use the enclosing rectangle instead
        approx = cv2.boxPoints(cv2.minAreaRect(paper)).reshape(4, 1, 2)
    quad = _order_quad(np.array(approx, np.float32)) / sc
    sides = [np.linalg.norm(quad[i] - quad[(i + 1) % 4]) for i in range(4)]
    return quad if min(sides) > 120 and max(sides) / min(sides) < 12 else None


def crop_document(gray):
    """Keep only the sheet of paper, seen square-on (perspective correction). Unchanged if none is found."""
    quad = document_quad(gray)
    if quad is None:
        return gray
    w = int(max(np.linalg.norm(quad[2] - quad[3]), np.linalg.norm(quad[1] - quad[0])))
    h = int(max(np.linalg.norm(quad[1] - quad[2]), np.linalg.norm(quad[0] - quad[3])))
    dst = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], np.float32)
    return cv2.warpPerspective(gray, cv2.getPerspectiveTransform(quad, dst), (w, h), flags=cv2.INTER_CUBIC)


def preprocess(img, deskew=True, crop=True, denoise=15, block=31):
    if crop:
        img = crop_document(img)    # photos: throw the desk away and flatten the paper
    h, w = img.shape[:2]
    if w < 1200:                    # small scans: enlarge towards the resolution OCR likes
        img = cv2.resize(img, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)
    elif w > 2000:                  # big phone photos: shrink to keep processing fast
        f = 1600 / w
        img = cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
    if denoise:
        img = cv2.fastNlMeansDenoising(img, None, denoise, 7, 21)
    ang = deskew_angle(img) if deskew else 0.0
    if abs(ang) >= MIN_SKEW:        # Tesseract copes with small tilts itself; rotating those only blurs the text
        img = rotate_bound(img, ang)
    if not block:                   # Otsu: one global cut, which suits high-contrast thermal paper
        return cv2.threshold(img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    return cv2.adaptiveThreshold(img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, block, 15)


# ----------------------------------------------------------------- 3. OCR
def ocr(img):
    """Return (text, mean word confidence 0-100). One Tesseract call gives both."""
    d = pytesseract.image_to_data(img, config="--oem 3 --psm 6", output_type=pytesseract.Output.DICT)
    lines, confs = {}, []
    for i, word in enumerate(d["text"]):
        word = word.strip()
        if not word:
            continue
        key = (d["block_num"][i], d["par_num"][i], d["line_num"][i])
        lines.setdefault(key, []).append(word)
        c = float(d["conf"][i])
        if c >= 0:
            confs.append(c)
    text = "\n".join(" ".join(ws) for _, ws in sorted(lines.items()))
    return text, round(sum(confs) / len(confs), 1) if confs else 0.0


# ----------------------------------------------------------------- 4. parsing
# 1,450.00 | 1740. 00 (stray OCR space) | 1575,00 (comma as decimal point, never with a space after it, so that
# the "2026, 08" inside a date-and-time line is not read as an amount)
AMT = r"(\d[\d,]*(?:\. ?|,)\d{2})(?![\d.,])"
# A clock time: hh:mm:ss (OCR turns the colons into . or ') or hh:mm with am/pm. Two separators or an
# am/pm marker are required, so that a plain amount such as 95.00 is never mistaken for a time.
TIME = re.compile(r"\b\d{1,2}\s*[:.']\s*\d{2}\s*[:.']\s*\d{2}\s*(?:[ap]\.?\s?m\.?)?|"
                  r"\b\d{1,2}\s*[:.']\s*\d{2}\s*[ap]\.?\s?m\.?", re.I)
LONE_AMOUNT = re.compile(r"^[^\d]{0,4}(\d[\d,]*(?:\.\d{2})?)[^\d]{0,3}$")   # a payment slip's big '₹650' line
PAID_TO = re.compile(r"\bpaid\s+(?:at|to)\b\s*[:\-]?\s*(.+)", re.I)
MERCHANT = re.compile(r"\b(?:merchant|store|shop|vendor)\s*(?:name)?\s*[:\-]\s*(.+)", re.I)
MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
NOT_ITEM = re.compile(r"total|gst|tax|sub|cash|change|card|upi|paid|balance|round|discount|"
                      r"saving|tender|amount|net\b|due|invoice|date|qty|rate|price", re.I)
HEADER_WORDS = re.compile(r"gstin|tax invoice|invoice|receipt|bill|date|phone|ph\.|tel|mob|"
                          r"welcome|original|duplicate|copy|cash memo", re.I)


def to_amount(s):
    s = s.replace(" ", "")
    if len(s) > 2 and s[-3] == ",":        # comma used as the decimal point
        s = s[:-3] + "." + s[-2:]
    return float(s.replace(",", ""))


def strip_times(text):
    """Blank out clock times so that '08:51.54 AM' and '2026, 08:51' are not mistaken for amounts."""
    return "\n".join(TIME.sub(" ", line) for line in text.splitlines())


def parse_date(text):
    """Find the first real calendar date; lines containing 'date' are searched first."""
    pats = [
        (r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\b", "dmy"),
        (r"\b(\d{4})[/.-](\d{1,2})[/.-](\d{1,2})\b", "ymd"),
        (r"\b(\d{1,2})[\s-]*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[\s,-]*(\d{4})\b", "dMy"),
        (r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{2})\b", "dmy2"),
    ]
    lines = text.splitlines()
    ordered = [l for l in lines if re.search(r"date|dt", l, re.I)] + lines
    for line in ordered:
        for pat, kind in pats:
            for m in re.finditer(pat, line, re.I):
                a, b, c = m.groups()
                try:
                    if kind == "dmy":
                        d = date(int(c), int(b), int(a))
                    elif kind == "ymd":
                        d = date(int(a), int(b), int(c))
                    elif kind == "dMy":
                        d = date(int(c), MONTHS[b.lower()[:3]], int(a))
                    else:
                        d = date(2000 + int(c), int(b), int(a))
                except ValueError:
                    continue
                if 2000 <= d.year <= 2100:
                    return d.isoformat()
    return None


def parse_amount_line(text, key, exclude=None, last=True):
    found = None
    for line in text.splitlines():
        if re.search(key, line, re.I) and not (exclude and re.search(exclude, line, re.I)):
            m = re.findall(AMT, line)
            if m:
                found = to_amount(m[-1])
                if not last:
                    return found
    return found


TOTAL_KEYS = (r"grand\s*total", r"net\s*(amount|payable|total)", r"amount\s*payable", r"amount\s*paid",
              r"total\s*amount", r"bill\s*amount", r"^\W*total\b|\btotal\s*[:\-]?\s*(rs|inr|₹)?\.?\s*\d",
              r"you\s*paid", r"\bpaid\b")
NOT_TOTAL = r"sub\s*-?\s*total|total\s*(qty|items?|quantity|savings?|discount)"


def parse_total(text):
    """Most specific total keyword wins; the last matching line is used."""
    for key in TOTAL_KEYS:
        v = parse_amount_line(text, key, exclude=NOT_TOTAL)
        if v is not None:
            return v, False
    # Card and UPI slips print the amount large, on a line of its own, under a heading such as
    # 'Payment Successful' or 'Amount Paid'; the rupee sign often survives OCR as a stray letter.
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if re.search(r"payment\s*success|amount\s*paid|\bpaid\b|\btotal\b", line, re.I) \
                and not re.search(NOT_TOTAL, line, re.I):
            for nxt in lines[i + 1:i + 3]:
                m = LONE_AMOUNT.match(nxt.strip())
                if m:
                    return to_amount(m.group(1)), False
    amounts = [to_amount(a) for a in re.findall(AMT, text)]
    return (max(amounts), True) if amounts else (None, False)   # fallback: largest amount


def parse_tax(text):
    total, found = 0.0, False
    for line in text.splitlines():
        if re.search(r"\b[csiu]?gst\b|\btax\b|\bvat\b|cess", line, re.I) and \
                not re.search(r"gstin|total|incl|taxable|invoice", line, re.I):
            m = re.findall(AMT, line)
            if m:
                total += to_amount(m[-1])
                found = True
    return round(total, 2) if found else None


def parse_items(text):
    items = []
    name = r"([A-Za-z][A-Za-z0-9 .%/&()'-]{1,}?)"
    pats = [re.compile(r"^\s*" + name + r"\s+(\d{1,3}|[Il|])\s*(?:x|@|nos?)?\s+" + AMT + r"\s+" + AMT + r"\s*$", re.I),  # name qty rate amount (OCR may read qty 1 as I, l or |)
            re.compile(r"^\s*" + name + r"\s+(\d{1,3})\s+" + AMT + r"\s*$"),                                        # name qty amount
            re.compile(r"^\s*" + name + r"\s+(?:rs\.?|inr|₹)?\s*" + AMT + r"\s*$", re.I)]                         # name amount
    for line in text.splitlines():
        for k, p in enumerate(pats):
            m = p.match(line)
            if not m:
                continue
            nm = re.sub(r"\s+\d{4,8}$", "", m.group(1).strip(" .-:"))     # drop a trailing HSN/SAC code
            if NOT_ITEM.search(nm) or len(re.sub(r"[^A-Za-z]", "", nm)) < 2:
                break
            if k == 0:
                qty = int(m.group(2)) if m.group(2).isdigit() else 1
                items.append(dict(name=nm, qty=qty, amount=to_amount(m.group(4))))
            elif k == 1:
                items.append(dict(name=nm, qty=int(m.group(2)), amount=to_amount(m.group(3))))
            else:
                items.append(dict(name=nm, qty=1, amount=to_amount(m.group(2))))
            break
    return items


def _vendor_name(line):
    """A line is usable as a vendor name only if it has a real word in it, not just OCR rubble."""
    clean = re.sub(r"^[^A-Za-z0-9]+|[^A-Za-z0-9)]+$", "", line.strip())
    words = re.findall(r"[A-Za-z]{2,}", clean)
    if len(re.sub(r"[^A-Za-z]", "", clean)) < 3 or not words or max(map(len, words)) < 4:
        return None
    return None if re.search(AMT, clean) else clean.title()


def parse_vendor(text):
    # A payment app names the shop explicitly ('Paid at SHIVA SHAKTI FUEL STATION'); that beats the top of the
    # page, which is the app's own logo.
    for pat in (PAID_TO, MERCHANT):
        m = pat.search(text)
        if m:
            name = _vendor_name(m.group(1))
            if name:
                return name
    for line in text.splitlines()[:6]:
        if not HEADER_WORDS.search(line):
            name = _vendor_name(line)
            if name:
                return name
    return None


def parse(text):
    money = strip_times(text)              # amounts are read from a copy with clock times removed
    total, guessed = parse_total(money)
    gstin = re.search(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b", text.upper())
    inv = re.search(r"(?:invoice|inv|bill|receipt)\s*(?:no|number|#)\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/-]{2,})", text, re.I)
    return dict(vendor=parse_vendor(text), gstin=gstin.group(0) if gstin else None,
                invoice_no=inv.group(1) if inv else None, date=parse_date(text), items=parse_items(money),
                subtotal=parse_amount_line(money, r"sub\s*-?\s*total|taxable\s*(value|amount)"),
                tax=parse_tax(money), total=total, total_guessed=guessed)


# ----------------------------------------------------------------- 5. categorization
DEFAULT_CATEGORIES = {
    "Groceries": "rice milk atta flour sugar tea egg eggs tomato onion vegetables fruits dal oil mart supermarket "
                 "kirana organics basket stores grocery dmart bigbasket blinkit zepto more ratnadeep",
    "Dining": "restaurant cafe biryani tadka paneer naan coffee dosa jamun hotel dhaba bakery pizza burger "
              "swiggy zomato meals food kitchen",
    "Fuel": "petrol diesel fuel cng lpg gas pump filling bunk hp hpcl bpcl ioc iocl indianoil bharat shell nayara",
    "Transport": "cab ride pass toll bus metro uber ola rapido parking auto railway irctc",
    "Electronics": "usb mouse phone power bank electronics gadget circuit cable charger laptop headphones "
                   "croma reliance digital earphones",
    "Health": "pharmacy medico chemist paracetamol vitamin sanitizer syrup tablet tablets medicine medplus "
              "apollo clinic hospital diagnostics",
    "Utilities": "electricity broadband water grid airnet aqua bill recharge jio airtel gas wifi internet "
                 "tsspdcl bescom",
    "Shopping": "clothing apparel shirt jeans shoes fashion mall trends lifestyle",
    "Others": "",
}


FUEL_CATEGORY = "Fuel"


def implied_fuel_item(rec):
    """A fuel bill is often a payment slip with one amount and no item lines (see the error analysis).
    When the record is categorised as fuel, has no items and has a total, record one 'Fuel' item for that
    total, so the amount is still accounted for instead of being flagged as an unreadable receipt."""
    if rec.get("category") != FUEL_CATEGORY or rec.get("items") or rec.get("total") is None:
        return rec
    rec["items"] = [dict(name="Fuel", qty=1, amount=rec["total"])]
    rec["items_implied"] = True
    return rec


def categorize(rec, categories):
    """categories: list of (name, keywords-string). Highest keyword-hit count wins; ties -> first."""
    blob = " ".join([rec.get("vendor") or ""] + [i["name"] for i in rec.get("items", [])]).lower()
    best, best_score = "Others", 0
    for name, kws in categories:
        score = sum(1 for k in (kws or "").lower().split() if re.search(r"\b" + re.escape(k) + r"\b", blob))
        if score > best_score:
            best, best_score = name, score
    return best


# ----------------------------------------------------------------- 6. validation
FLAG_TEXT = {
    "items_sum_mismatch": "Line items do not add up to the subtotal.",
    "total_mismatch": "The amounts do not add up: subtotal (or items) plus tax is not equal to the total.",
    "missing_date": "No date was found.",
    "missing_total": "No total amount was found.",
    "total_guessed": "No 'Total' line was found; the largest amount was used.",
    "no_items_found": "No line items were recognised.",
    "date_in_future": "The date is in the future.",
    "low_ocr_confidence": "The image quality is low; please check every value.",
    "possible_duplicate": "A document with the same vendor, date and total already exists.",
}


def validate(rec, today=None):
    flags = []
    items_sum = round(sum(i["amount"] for i in rec["items"]), 2) if rec["items"] else None
    if items_sum is not None and rec["subtotal"] is not None and abs(items_sum - rec["subtotal"]) > 0.05:
        flags.append("items_sum_mismatch")
    base = rec["subtotal"] if rec["subtotal"] is not None else items_sum
    tax = rec["tax"] if rec["tax"] is not None else (0.0 if rec["subtotal"] is None else None)
    if None not in (base, tax, rec["total"]) and abs(base + tax - rec["total"]) > 0.05:
        flags.append("total_mismatch")          # no tax line and no subtotal -> items must equal the total
    if not rec.get("date"):
        flags.append("missing_date")
    elif rec["date"] > (today or date.today()).isoformat():
        flags.append("date_in_future")
    if rec.get("total") is None:
        flags.append("missing_total")
    if rec.get("total_guessed"):
        flags.append("total_guessed")
    if not rec["items"]:
        flags.append("no_items_found")
    if rec.get("ocr_confidence") is not None and rec["ocr_confidence"] < 60:
        flags.append("low_ocr_confidence")
    return flags


# ----------------------------------------------------------------- full pipeline
PASSES = (dict(denoise=15, block=31),      # clean scans, PDFs and good photos
          dict(denoise=7, block=51),       # gentler: faint or uneven thermal print
          dict(denoise=0, block=0))        # Otsu, no denoising: high-contrast photos with thin strokes
GOOD_ENOUGH = 8.0                          # a reading this solid needs no second opinion


def read_score(rec, conf):
    """How well a reading hangs together, used to choose between pre-processing passes. The arithmetic
    carries the most weight: if the amounts add up, the page was almost certainly read correctly."""
    s = conf / 100.0
    s += 2 if rec["total"] is not None else 0
    s += 0 if rec["total_guessed"] else 1
    s += 1 if rec["date"] else 0
    s += 0.5 if rec["vendor"] else 0
    s += 0.4 * min(len(rec["items"]), 8)
    if not [f for f in validate(rec) if f in ("items_sum_mismatch", "total_mismatch")]:
        s += 3
    return round(s, 3)


def process(path, categories=None, today=None):
    img = crop_document(load_image(path))        # locate the paper once, then re-read it with each setting
    best = None
    for n, opts in enumerate(PASSES):
        text, conf = ocr(preprocess(img, crop=False, **opts))
        rec = parse(text)
        rec["ocr_text"], rec["ocr_confidence"], rec["ocr_pass"] = text, conf, n
        score = read_score(rec, conf)
        if best is None or score > best[0]:
            best = (score, rec)
        if score >= GOOD_ENOUGH:           # already consistent: skip the slower fall-backs
            break
    rec = best[1]
    rec["category"] = categorize(rec, categories or list(DEFAULT_CATEGORIES.items()))
    implied_fuel_item(rec)
    rec["flags"] = validate(rec, today)
    return rec
