"""Registration, login, logout and access control."""
import functools
import re
import secrets

from flask import (Blueprint, abort, flash, g, redirect, render_template, request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db, seed_categories

bp = Blueprint("auth", __name__)
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ------------------------------------------------------------ CSRF protection for HTML forms
def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


def check_csrf():
    """Every state-changing form POST must carry the token that was put in the page."""
    if request.method == "POST" and not request.path.startswith("/api/"):
        sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
        if not sent or not secrets.compare_digest(sent, session.get("csrf", "")):
            abort(400, "Your session expired. Please reload the page and try again.")


# ------------------------------------------------------------ current user
def load_user():
    uid = session.get("user_id")
    g.user = get_db().execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone() if uid else None


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def create_user(db, name, email, password):
    cur = db.execute("INSERT INTO users(name, email, password_hash, api_key) VALUES (?,?,?,?)",
                     (name, email.lower(), generate_password_hash(password), secrets.token_urlsafe(24)))
    seed_categories(db, cur.lastrowid)
    db.commit()
    return cur.lastrowid


# ------------------------------------------------------------ routes
@bp.route("/register", methods=("GET", "POST"))
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        pw = request.form.get("password", "")
        error = None
        if not name:
            error = "Please enter your name."
        elif not EMAIL.match(email):
            error = "Please enter a valid email address."
        elif len(pw) < 6:
            error = "Password must be at least 6 characters."
        elif pw != request.form.get("confirm", ""):
            error = "Passwords do not match."
        elif get_db().execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            error = "An account with this email already exists."
        if error:
            flash(error, "error")
        else:
            uid = create_user(get_db(), name, email, pw)
            session.clear()
            session["user_id"] = uid
            flash(f"Welcome, {name}! Upload your first receipt to get started.", "success")
            return redirect(url_for("web.dashboard"))
    return render_template("auth.html", mode="register")


@bp.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = get_db().execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if user and check_password_hash(user["password_hash"], request.form.get("password", "")):
            session.clear()
            session["user_id"] = user["user_id"]
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("web.dashboard"))
        flash("Incorrect email or password.", "error")
    return render_template("auth.html", mode="login")


@bp.route("/logout", methods=("POST",))
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("auth.login"))
