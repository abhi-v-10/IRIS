"""Invoice & Receipt Intelligence System (IRIS) - Flask application factory."""
import os
import secrets

from flask import Flask, render_template, request

from . import analytics, api, auth, db, pipeline, web

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _secret_key(instance):
    """A random key created once and kept in instance/secret_key, so logins survive restarts."""
    path = os.path.join(instance, "secret_key")
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(secrets.token_hex(32))
    with open(path) as f:
        return f.read().strip()


def create_app(test_config=None):
    # IRIS_INSTANCE lets a deployment keep the database, the uploads and the secret key on a
    # mounted disk instead of inside the (throw-away) application folder. Locally it is unset,
    # so everything stays in ./instance as before.
    instance = os.environ.get("IRIS_INSTANCE") or os.path.join(ROOT, "instance")
    app = Flask(__name__, instance_path=instance)
    os.makedirs(instance, exist_ok=True)
    app.config.update(DATABASE=os.path.join(instance, "iris.db"), UPLOAD_FOLDER=os.path.join(instance, "uploads"),
                      SAMPLE_FOLDER=os.path.join(ROOT, "sample_receipts"), MAX_CONTENT_LENGTH=15 * 1024 * 1024,
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                      # Behind HTTPS (any real deployment) the session cookie must not travel over plain HTTP.
                      SESSION_COOKIE_SECURE=os.environ.get("IRIS_HTTPS") == "1")
    if test_config:
        app.config.update(test_config)
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or _secret_key(instance)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    pipeline.configure_tesseract()
    db.init_db(app.config["DATABASE"])
    app.teardown_appcontext(db.close_db)
    app.before_request(auth.load_user)
    app.before_request(auth.check_csrf)
    app.register_blueprint(auth.bp)
    app.register_blueprint(web.bp)
    app.register_blueprint(api.bp)

    app.jinja_env.filters["money"] = analytics.money
    app.jinja_env.filters["nicedate"] = _nicedate
    app.jinja_env.globals.update(csrf_token=auth.csrf_token)

    @app.context_processor
    def review_badge():
        from flask import g
        if getattr(g, "user", None) is None:
            return {}
        n = db.get_db().execute("SELECT COUNT(*) FROM documents WHERE user_id=? AND status='needs_review'",
                                (g.user["user_id"],)).fetchone()[0]
        return {"review_count": n}

    @app.errorhandler(404)
    def not_found(_):
        if request.path.startswith("/api/"):
            return {"error": "Not found."}, 404
        return render_template("error.html", code=404, message="That page or document does not exist."), 404

    @app.errorhandler(400)
    def bad_request(e):
        return render_template("error.html", code=400, message=e.description), 400

    @app.errorhandler(413)
    def too_large(_):
        msg = "The upload is too large (15 MB limit per request)."
        if request.path.startswith("/api/"):
            return {"error": msg}, 413
        return render_template("error.html", code=413, message=msg), 413

    return app


def _nicedate(iso):
    from datetime import datetime
    try:
        return datetime.strptime(iso, "%Y-%m-%d").strftime("%d %b %Y")
    except (TypeError, ValueError):
        return iso or "No date"
