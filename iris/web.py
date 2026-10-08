"""HTML pages."""
import glob
import json
import os
from datetime import datetime

from flask import (Blueprint, Response, abort, current_app, flash, g, redirect, render_template, request,
                   send_from_directory, url_for)
from werkzeug.datastructures import FileStorage

from . import analytics, export, pipeline, services
from .auth import login_required
from .db import get_db, user_categories

bp = Blueprint("web", __name__)


def _filters_and_categories():
    f = services.read_filters(request.args)
    return f, user_categories(get_db(), g.user["user_id"])


def _filters_text(f, cats):
    names = {str(c["category_id"]): c["name"] for c in cats}
    parts = []
    if f.get("date_from") or f.get("date_to"):
        parts.append(f"{f.get('date_from', 'start')} to {f.get('date_to', 'today')}")
    if f.get("category"):
        parts.append(names.get(f["category"], "?"))
    if f.get("status"):
        parts.append(f["status"].replace("_", " "))
    if f.get("q"):
        parts.append(f"search '{f['q']}'")
    return ", ".join(parts) or "all documents"


# ------------------------------------------------------------ landing page
@bp.route("/")
def home():
    return render_template("home.html")


# ------------------------------------------------------------ dashboard
@bp.route("/dashboard")
@login_required
def dashboard():
    f, cats = _filters_and_categories()
    s = analytics.summarize(get_db(), g.user["user_id"], f)
    recent = services.list_documents(get_db(), g.user["user_id"], f, limit=6)
    return render_template("dashboard.html", s=s, f=f, cats=cats, recent=recent,
                           chart_data=json.dumps(dict(by_category=s["by_category"], monthly=s["monthly"],
                                                      top_vendors=s["top_vendors"])))


# ------------------------------------------------------------ upload
@bp.route("/upload", methods=("GET", "POST"))
@login_required
def upload():
    if request.method == "POST":
        files = [fs for fs in request.files.getlist("files") if fs and fs.filename]
        if not files:
            flash("Choose at least one receipt or invoice to upload.", "error")
            return redirect(url_for("web.upload"))
        return _process_many(files)
    return render_template("upload.html", tesseract=pipeline.tesseract_version(),
                           n_samples=len(_sample_files()))


def _process_many(files):
    db, uid = get_db(), g.user["user_id"]
    done, review, last = 0, 0, None
    for fs in files:
        try:
            last, rec = services.process_upload(db, uid, fs)
            done += 1
            review += rec["status"] == "needs_review"
        except services.UploadError as e:
            flash(str(e), "error")
    if done == 1 and len(files) == 1:
        flash("Document processed. Check the extracted details below and save to verify.", "success")
        return redirect(url_for("web.document", doc_id=last))
    if done:
        flash(f"{done} document(s) processed" + (f", {review} need review." if review else ", none need review."),
              "success")
        return redirect(url_for("web.documents", status="needs_review") if review else url_for("web.documents"))
    return redirect(url_for("web.upload"))


def _sample_files():
    folder = current_app.config["SAMPLE_FOLDER"]
    return sorted(p for p in glob.glob(os.path.join(folder, "*"))
                  if os.path.splitext(p)[1].lower() in pipeline.ALLOWED_EXTENSIONS)


@bp.route("/upload/samples", methods=("POST",))
@login_required
def upload_samples():
    """One-click demo: process the bundled sample documents."""
    paths = _sample_files()
    if not paths:
        flash("No sample documents found in the sample_receipts folder.", "error")
        return redirect(url_for("web.upload"))
    files = [FileStorage(stream=open(p, "rb"), filename=os.path.basename(p)) for p in paths]
    try:
        return _process_many(files)
    finally:
        for fs in files:
            fs.stream.close()


# ------------------------------------------------------------ documents
@bp.route("/documents")
@login_required
def documents():
    f, cats = _filters_and_categories()
    docs = services.list_documents(get_db(), g.user["user_id"], f)
    total = sum(d["total"] or 0 for d in docs)
    return render_template("documents.html", docs=docs, f=f, cats=cats, total=total)


@bp.route("/documents/<int:doc_id>", methods=("GET", "POST"))
@login_required
def document(doc_id):
    db, uid = get_db(), g.user["user_id"]
    doc, items = services.get_document(db, uid, doc_id)
    if doc is None:
        abort(404)
    if request.method == "POST":
        names, qtys, amts = (request.form.getlist(k) for k in ("item_name", "item_qty", "item_amount"))
        new_items = [dict(name=n, qty=q, amount=a) for n, q, a in zip(names, qtys, amts)]
        try:
            warnings = services.update_document(db, uid, doc_id, request.form, new_items)
        except ValueError:
            flash("Amounts must be numbers, for example 1250.50.", "error")
            return redirect(url_for("web.document", doc_id=doc_id))
        if warnings:
            flash("Saved and marked verified. Note: " + " ".join(pipeline.FLAG_TEXT.get(w, w) for w in warnings),
                  "warn")
        else:
            flash("Saved and marked verified. All checks pass.", "success")
        return redirect(url_for("web.document", doc_id=doc_id))
    flags = json.loads(doc["flags"] or "[]")
    dup = services.find_duplicate(db, uid, doc["vendor"], doc["doc_date"], doc["total"], exclude_id=doc_id) \
        if "possible_duplicate" in flags else None
    items_sum = round(sum(i["amount"] for i in items), 2)
    nav = db.execute("""SELECT
        (SELECT doc_id FROM documents WHERE user_id=? AND status='needs_review' AND doc_id!=? ORDER BY doc_id LIMIT 1)
        AS next_review""", (uid, doc_id)).fetchone()
    return render_template("document.html", doc=doc, items=items, flags=flags, flag_text=pipeline.FLAG_TEXT,
                           cats=user_categories(db, uid), dup=dup, items_sum=items_sum,
                           next_review=nav["next_review"])


@bp.route("/documents/<int:doc_id>/file")
@login_required
def document_file(doc_id):
    row = get_db().execute("SELECT file_path, preview_path FROM documents WHERE doc_id=? AND user_id=?",
                           (doc_id, g.user["user_id"])).fetchone()
    if row is None:
        abort(404)
    name = row["file_path"] if request.args.get("original") else (row["preview_path"] or row["file_path"])
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], name)


@bp.route("/documents/<int:doc_id>/delete", methods=("POST",))
@login_required
def document_delete(doc_id):
    if services.delete_document(get_db(), g.user["user_id"], doc_id):
        flash("Document deleted.", "success")
    return redirect(url_for("web.documents"))


# ------------------------------------------------------------ categories
@bp.route("/categories", methods=("GET", "POST"))
@login_required
def categories():
    db, uid = get_db(), g.user["user_id"]
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            name = request.form.get("name", "").strip()[:40]
            if not name:
                flash("Enter a category name.", "error")
            elif db.execute("SELECT 1 FROM categories WHERE user_id=? AND lower(name)=lower(?)", (uid, name)).fetchone():
                flash(f"A category called '{name}' already exists.", "error")
            else:
                db.execute("INSERT INTO categories(user_id, name, keywords) VALUES (?,?,?)",
                           (uid, name, _clean_keywords(request.form.get("keywords", ""))))
                db.commit()
                flash(f"Category '{name}' added.", "success")
        elif action == "save":
            cid = request.form.get("category_id")
            db.execute("UPDATE categories SET keywords=? WHERE category_id=? AND user_id=?",
                       (_clean_keywords(request.form.get("keywords", "")), cid, uid))
            db.commit()
            flash("Keywords saved. Use 'Re-apply to documents' to update existing records.", "success")
        elif action == "delete":
            cid = request.form.get("category_id")
            row = db.execute("SELECT name FROM categories WHERE category_id=? AND user_id=?", (cid, uid)).fetchone()
            if row and row["name"] != "Others":
                others = db.execute("SELECT category_id FROM categories WHERE user_id=? AND name='Others'",
                                    (uid,)).fetchone()["category_id"]
                db.execute("UPDATE documents SET category_id=? WHERE category_id=? AND user_id=?", (others, cid, uid))
                db.execute("DELETE FROM categories WHERE category_id=? AND user_id=?", (cid, uid))
                db.commit()
                flash(f"Category '{row['name']}' deleted; its documents moved to Others.", "success")
        elif action == "recategorize":
            n = services.recategorize_all(db, uid)
            flash(f"Categories re-applied. {n} document(s) changed category (verified documents are left as you set them).",
                  "success")
        return redirect(url_for("web.categories"))
    counts = {r["category_id"]: (r["n"], r["spent"]) for r in db.execute(
        "SELECT category_id, COUNT(*) n, SUM(total) spent FROM documents WHERE user_id=? GROUP BY category_id", (uid,))}
    return render_template("categories.html", cats=user_categories(db, uid), counts=counts)


def _clean_keywords(s):
    return " ".join(dict.fromkeys(w for w in s.lower().replace(",", " ").split() if w))[:2000]


# ------------------------------------------------------------ export
def _export_data():
    f, cats = _filters_and_categories()
    db, uid = get_db(), g.user["user_id"]
    docs = services.list_documents(db, uid, f)
    return f, cats, docs


@bp.route("/export.csv")
@login_required
def export_csv():
    f, cats, docs = _export_data()
    ids = [d["doc_id"] for d in docs] or [-1]
    items = {}
    for i in get_db().execute(f"SELECT * FROM line_items WHERE doc_id IN ({','.join('?' * len(ids))}) ORDER BY item_id", ids):
        items.setdefault(i["doc_id"], []).append(i)
    name = f"expenses_{datetime.now():%Y%m%d}.csv"
    return Response(export.to_csv(docs, items), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={name}"})


@bp.route("/export.pdf")
@login_required
def export_pdf():
    f, cats, docs = _export_data()
    s = analytics.summarize(get_db(), g.user["user_id"], f)
    pdf = export.to_pdf(g.user["name"], _filters_text(f, cats), s, docs)
    name = f"expense_report_{datetime.now():%Y%m%d}.pdf"
    return Response(pdf, mimetype="application/pdf", headers={"Content-Disposition": f"attachment; filename={name}"})


# ------------------------------------------------------------ settings
@bp.route("/settings")
@login_required
def settings():
    return render_template("settings.html", tesseract=pipeline.tesseract_version())
