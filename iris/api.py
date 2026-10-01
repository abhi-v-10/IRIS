"""REST API. Authenticate with the per-user API key shown on the Settings page:

    Authorization: Bearer <api_key>

    POST   /api/upload                 multipart file(s) under 'file'  -> extracted record(s)
    GET    /api/documents              ?date_from&date_to&category&status&q
    GET    /api/documents/<id>
    PUT    /api/documents/<id>         JSON corrections -> record is marked verified
    DELETE /api/documents/<id>
    GET    /api/summary                same filters -> KPIs, by_category, monthly, top_vendors, insights
    GET    /api/health                 no auth; reports whether Tesseract is available
"""
import functools

from flask import Blueprint, g, jsonify, request

from . import analytics, pipeline, services
from .db import get_db

bp = Blueprint("api", __name__, url_prefix="/api")


def api_auth(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        key = header[7:].strip() if header.lower().startswith("bearer ") else request.headers.get("X-API-Key", "")
        user = get_db().execute("SELECT * FROM users WHERE api_key=?", (key,)).fetchone() if key else None
        if user is None:
            return jsonify(error="Missing or invalid API key. Send 'Authorization: Bearer <key>'."), 401
        g.api_user = user
        return view(*args, **kwargs)
    return wrapped


@bp.get("/health")
def health():
    v = pipeline.tesseract_version()
    return jsonify(status="ok" if v else "degraded", tesseract=v)


@bp.post("/upload")
@api_auth
def upload():
    files = [f for f in request.files.getlist("file") if f and f.filename]
    if not files:
        return jsonify(error="Send the document as multipart form field 'file'."), 400
    results, errors = [], []
    for f in files:
        try:
            doc_id, _ = services.process_upload(get_db(), g.api_user["user_id"], f)
            doc, items = services.get_document(get_db(), g.api_user["user_id"], doc_id)
            results.append(services.document_dict(doc, items))
        except services.UploadError as e:
            errors.append(dict(file=f.filename, error=str(e)))
    if not results:
        return jsonify(error=errors[0]["error"], errors=errors), 400
    body = results[0] if len(files) == 1 else dict(documents=results, errors=errors)
    return jsonify(body), 201


@bp.get("/documents")
@api_auth
def documents():
    f = services.read_filters(request.args)
    rows = services.list_documents(get_db(), g.api_user["user_id"], f)
    return jsonify(documents=[dict(doc_id=r["doc_id"], date=r["doc_date"], vendor=r["vendor"], category=r["category"],
                                   total=r["total"], status=r["status"]) for r in rows], count=len(rows))


@bp.get("/documents/<int:doc_id>")
@api_auth
def document(doc_id):
    doc, items = services.get_document(get_db(), g.api_user["user_id"], doc_id)
    if doc is None:
        return jsonify(error="Document not found."), 404
    return jsonify(services.document_dict(doc, items))


@bp.put("/documents/<int:doc_id>")
@api_auth
def correct(doc_id):
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error="Send a JSON object, e.g. {\"total\": 520.00}."), 400
    if "category" in body and "category_id" not in body:
        row = get_db().execute("SELECT category_id FROM categories WHERE user_id=? AND lower(name)=lower(?)",
                               (g.api_user["user_id"], body["category"])).fetchone()
        if row is None:
            return jsonify(error=f"Unknown category '{body['category']}'."), 400
        body["category_id"] = row["category_id"]
    items = body.get("items") if isinstance(body.get("items"), list) else None
    try:
        warnings = services.update_document(get_db(), g.api_user["user_id"], doc_id, body, items)
    except KeyError:
        return jsonify(error="Document not found."), 404
    except ValueError:
        return jsonify(error="Amounts must be numbers."), 400
    doc, items = services.get_document(get_db(), g.api_user["user_id"], doc_id)
    return jsonify(document=services.document_dict(doc, items), warnings=warnings)


@bp.delete("/documents/<int:doc_id>")
@api_auth
def delete(doc_id):
    if not services.delete_document(get_db(), g.api_user["user_id"], doc_id):
        return jsonify(error="Document not found."), 404
    return jsonify(deleted=doc_id)


@bp.get("/summary")
@api_auth
def summary():
    s = analytics.summarize(get_db(), g.api_user["user_id"], services.read_filters(request.args))
    s["insights"] = [t for _, t in s["insights"]]
    return jsonify(s)
