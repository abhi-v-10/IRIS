"""Database helpers (SQLite)."""
import os
import sqlite3

from flask import current_app, g

from .pipeline import DEFAULT_CATEGORIES


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(path):
    """Create the tables on first run only, so restarting the app never fails."""
    con = sqlite3.connect(path)
    try:
        exists = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
        if not exists:
            with open(os.path.join(os.path.dirname(__file__), "schema.sql")) as f:
                con.executescript(f.read())
            con.commit()
        else:
            _add_new_default_categories(con)
    finally:
        con.close()


# Keyword lists that earlier versions gave every user. A list that is still exactly the old default was
# never edited by the user, so it is safe to replace with the current one; an edited list is left alone.
RETIRED_KEYWORDS = {
    "Transport": ["cab ride petrol diesel fuel pass toll bus metro uber ola rapido parking auto railway irctc"],
}


def _add_new_default_categories(con):
    """Give existing accounts the default categories that were added after they registered."""
    con.execute("PRAGMA foreign_keys = ON")
    users = [r[0] for r in con.execute("SELECT user_id FROM users")]
    for uid in users:
        con.executemany("INSERT OR IGNORE INTO categories(user_id, name, keywords) VALUES (?,?,?)",
                        [(uid, n, k) for n, k in DEFAULT_CATEGORIES.items()])
    for name, old_lists in RETIRED_KEYWORDS.items():
        for old in old_lists:
            con.execute("UPDATE categories SET keywords=? WHERE name=? AND keywords=?",
                        (DEFAULT_CATEGORIES[name], name, old))
    con.commit()


def seed_categories(db, user_id):
    db.executemany("INSERT OR IGNORE INTO categories(user_id, name, keywords) VALUES (?,?,?)",
                   [(user_id, n, k) for n, k in DEFAULT_CATEGORIES.items()])


def user_categories(db, user_id):
    return db.execute("SELECT * FROM categories WHERE user_id=? ORDER BY name='Others', name",
                      (user_id,)).fetchall()
