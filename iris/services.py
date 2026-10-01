"""Business logic shared by the web pages and the REST API."""
import json
import os
import time
import uuid

from flask import current_app

from . import pipeline
from .db import user_categories


class UploadError(ValueError):
    pass


# ------------------------------------------------------------ upload + processing
def _category_id(db, user_id, name):
    row = db.execute("SELECT category_id FROM categories WHERE user_id=? AND name=?", (user_id, name)).fetchone()
    if row is None:
        row = db.execute("SELECT category_id FROM categories WHERE user_id=? AND name='Others'", (user_id,)).fetchone()
    return row["category_id"] if row else None


def find_duplicate(db, user_id, vendor, doc_date, total, exclude_id=None):
    if not (vendor and doc_date and total is not None):
        return None
    row = db.execute("""SELECT doc_id FROM documents WHERE user_id=? AND lower(vendor)=lower(?) AND doc_date=?
                        AND abs(total-?)<0.01 AND doc_id != ? ORDER BY doc_id LIMIT 1""",
                     (user_id, vendor, doc_date, total, exclude_id or -1)).fetchone()
    return row["doc_id"] if row else None


def process_upload(db, user_id, file_storage):
    """Validate, store and process one uploaded file. Returns (doc_id, record)."""
    original = os.path.basename(file_storage.filename or "")
    ext = os.path.splitext(original)[1].lower()
    if ext not in pipeline.ALLOWED_EXTENSIONS:
        raise UploadError(f"'{original or 'file'}' is not supported. Upload a JPG, PNG, HEIC or PDF.")
    if pipeline.tesseract_version() is None:
        raise UploadError("The Tesseract OCR engine is not installed or not found. See the README (step 1).")
    folder = current_app.config["UPLOAD_FOLDER"]
    stored = uuid.uuid4().hex + ext
    path = os.path.join(folder, stored)
    file_storage.save(path)
    preview = None
    try:
        if ext == ".pdf" or ext in pipeline.HEIC_EXTENSIONS:
            preview = uuid.uuid4().hex + ".png"
            pipeline.save_preview(path, os.path.join(folder, preview))
        cats = [(c["name"], c["keywords"]) for c in user_categories(db, user_id)]
        t0 = time.time()
        rec = pipeline.process(path, cats)
        ms = int((time.time() - t0) * 1000)
    except Exception as exc:  # unreadable/corrupt file: remove it and report cleanly
        for p in (path, preview and os.path.join(folder, preview)):
            if p and os.path.exists(p):
                os.remove(p)
        if isinstance(exc, (ValueError, OSError)) or "pdfium" in type(exc).__module__:
            raise UploadError(f"'{original}' could not be read as an image or PDF.") from exc
        raise
    dup = find_duplicate(db, user_id, rec["vendor"], rec["date"], rec["total"])
    if dup:
        rec["flags"].append("possible_duplicate")
    rec["duplicate_of"] = dup
    status = "needs_review" if rec["flags"] else "processed"
    cur = db.execute("""INSERT INTO documents(user_id, file_path, preview_path, original_name, vendor, gstin, invoice_no,
                        doc_date, subtotal, tax, total, category_id, status, flags, ocr_text, ocr_confidence,
                        processing_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (user_id, stored, preview, original, rec["vendor"], rec["gstin"], rec["invoice_no"], rec["date"],
                      rec["subtotal"], rec["tax"], rec["total"], _category_id(db, user_id, rec["category"]), status,
                      json.dumps(rec["flags"]), rec["ocr_text"], rec["ocr_confidence"], ms))
    db.executemany("INSERT INTO line_items(doc_id, name, qty, amount) VALUES (?,?,?,?)",
                   [(cur.lastrowid, i["name"], i["qty"], i["amount"]) for i in rec["items"]])
    db.commit()
    rec.update(doc_id=cur.lastrowid, status=status, processing_ms=ms)
    return cur.lastrowid, rec


# ------------------------------------------------------------ reading
def get_document(db, user_id, doc_id):
    doc = db.execute("""SELECT d.*, c.name AS category FROM documents d LEFT JOIN categories c USING(category_id)
                        WHERE d.doc_id=? AND d.user_id=?""", (doc_id, user_id)).fetchone()
    if doc is None:
        return None, []
    items = db.execute("SELECT * FROM line_items WHERE doc_id=? ORDER BY item_id", (doc_id,)).fetchall()
    return doc, items


def document_dict(doc, items):
    d = {k: doc[k] for k in ("doc_id", "vendor", "gstin", "invoice_no", "subtotal", "tax", "total", "category",
                             "status", "ocr_confidence", "original_name", "uploaded_at")}
    d["date"] = doc["doc_date"]
    d["flags"] = json.loads(doc["flags"] or "[]")
    d["items"] = [dict(name=i["name"], qty=i["qty"], amount=i["amount"]) for i in items]
    return d


def read_filters(args):
    """Filters shared by the documents list, dashboard, exports and API."""
    f = {k: (args.get(k) or "").strip() for k in ("date_from", "date_to", "category", "status", "q")}
    return {k: v for k, v in f.items() if v}


def filter_sql(user_id, f, alias="d"):
    where, params = [f"{alias}.user_id=?"], [user_id]
    if f.get("date_from"):
        where.append(f"{alias}.doc_date>=?"); params.append(f["date_from"])
    if f.get("date_to"):
        where.append(f"{alias}.doc_date<=?"); params.append(f["date_to"])
    if f.get("category"):
        where.append(f"{alias}.category_id=?"); params.append(f["category"])
    if f.get("status"):
        where.append(f"{alias}.status=?"); params.append(f["status"])
    if f.get("q"):
        where.append(f"(lower({alias}.vendor) LIKE ? OR lower({alias}.invoice_no) LIKE ?)")
        params += [f"%{f['q'].lower()}%"] * 2
    return " AND ".join(where), params


def list_documents(db, user_id, f, limit=None):
    where, params = filter_sql(user_id, f)
    sql = f"""SELECT d.*, c.name AS category,
                     (SELECT COUNT(*) FROM line_items li WHERE li.doc_id=d.doc_id) AS n_items
              FROM documents d LEFT JOIN categories c USING(category_id)
              WHERE {where} ORDER BY COALESCE(d.doc_date, d.uploaded_at) DESC, d.doc_id DESC"""
    if limit:
        sql += f" LIMIT {int(limit)}"
    return db.execute(sql, params).fetchall()


# ------------------------------------------------------------ corrections
def _num(v):
    v = (str(v) if v is not None else "").replace(",", "").replace("₹", "").strip()
    if v == "":
        return None
    return round(float(v), 2)


def update_document(db, user_id, doc_id, data, items=None):
    """Apply user corrections, re-run the checks and mark the record verified.
    data: dict with any of vendor, gstin, invoice_no, date, subtotal, tax, total, category_id.
    items: list of dicts (name, qty, amount) to replace the line items, or None to keep them.
    Returns the list of warnings that still apply (saved anyway because the user confirmed)."""
    doc, old_items = get_document(db, user_id, doc_id)
    if doc is None:
        raise KeyError(doc_id)
    fields = dict(vendor=doc["vendor"], gstin=doc["gstin"], invoice_no=doc["invoice_no"], date=doc["doc_date"],
                  subtotal=doc["subtotal"], tax=doc["tax"], total=doc["total"], category_id=doc["category_id"])
    for k in ("vendor", "gstin", "invoice_no", "date"):
        if k in data:
            fields[k] = (data[k] or "").strip() or None
    for k in ("subtotal", "tax", "total"):
        if k in data:
            fields[k] = _num(data[k])
    if data.get("category_id"):
        ok = db.execute("SELECT 1 FROM categories WHERE category_id=? AND user_id=?",
                        (data["category_id"], user_id)).fetchone()
        if ok:
            fields["category_id"] = int(data["category_id"])
    if items is not None:
        clean = []
        for it in items:
            name = (it.get("name") or "").strip()
            amt = _num(it.get("amount"))
            if name and amt is not None:
                clean.append(dict(name=name, qty=int(_num(it.get("qty")) or 1), amount=amt))
    else:
        clean = [dict(name=i["name"], qty=i["qty"], amount=i["amount"]) for i in old_items]
    check = dict(items=clean, subtotal=fields["subtotal"], tax=fields["tax"], total=fields["total"], date=fields["date"])
    warnings = [f for f in pipeline.validate(check) if f != "no_items_found"]
    if find_duplicate(db, user_id, fields["vendor"], fields["date"], fields["total"], exclude_id=doc_id):
        warnings.append("possible_duplicate")
    db.execute("""UPDATE documents SET vendor=?, gstin=?, invoice_no=?, doc_date=?, subtotal=?, tax=?, total=?,
                  category_id=?, status='verified', flags=?, verified_at=CURRENT_TIMESTAMP WHERE doc_id=? AND user_id=?""",
               (fields["vendor"], fields["gstin"], fields["invoice_no"], fields["date"], fields["subtotal"],
                fields["tax"], fields["total"], fields["category_id"], json.dumps(warnings), doc_id, user_id))
    if items is not None:
        db.execute("DELETE FROM line_items WHERE doc_id=?", (doc_id,))
        db.executemany("INSERT INTO line_items(doc_id, name, qty, amount) VALUES (?,?,?,?)",
                       [(doc_id, i["name"], i["qty"], i["amount"]) for i in clean])
    db.commit()
    return warnings


def delete_document(db, user_id, doc_id):
    doc = db.execute("SELECT file_path, preview_path FROM documents WHERE doc_id=? AND user_id=?",
                     (doc_id, user_id)).fetchone()
    if doc is None:
        return False
    folder = current_app.config["UPLOAD_FOLDER"]
    for name in (doc["file_path"], doc["preview_path"]):
        if name and os.path.exists(os.path.join(folder, name)):
            os.remove(os.path.join(folder, name))
    db.execute("DELETE FROM documents WHERE doc_id=? AND user_id=?", (doc_id, user_id))
    db.commit()
    return True


def recategorize_all(db, user_id):
    """Re-apply the (possibly edited) category keywords to every document the user has not verified."""
    cats = [(c["name"], c["keywords"]) for c in user_categories(db, user_id)]
    docs = db.execute("SELECT doc_id, vendor FROM documents WHERE user_id=? AND status!='verified'", (user_id,)).fetchall()
    changed = 0
    for d in docs:
        items = db.execute("SELECT name FROM line_items WHERE doc_id=?", (d["doc_id"],)).fetchall()
        name = pipeline.categorize(dict(vendor=d["vendor"], items=[dict(name=i["name"]) for i in items]), cats)
        cid = _category_id(db, user_id, name)
        changed += db.execute("UPDATE documents SET category_id=? WHERE doc_id=? AND category_id IS NOT ?",
                              (cid, d["doc_id"], cid)).rowcount
    db.commit()
    return changed
