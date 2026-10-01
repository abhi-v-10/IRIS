"""Create a demo account filled with ~6 months of receipts, for presentations.

    python tools/seed_demo.py            -> login: demo@iris.local / demo1234   (takes about a minute)
    python tools/seed_demo.py --reset    -> delete the demo account first and rebuild it

Every receipt goes through the real upload pipeline (pre-processing, OCR, extraction, checks), exactly as if
it had been uploaded in the browser. The receipts are synthetic; upload your own photos for real-world data.
"""
import os
import random
import sys
import tempfile
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from werkzeug.datastructures import FileStorage  # noqa: E402

import gen_receipts as G  # noqa: E402
from iris import create_app  # noqa: E402
from iris.auth import create_user  # noqa: E402
from iris.db import get_db  # noqa: E402
from iris.services import UploadError, process_upload  # noqa: E402

EMAIL, PASSWORD = "demo@iris.local", "demo1234"


def main():
    app = create_app()
    with app.app_context():
        db = get_db()
        row = db.execute("SELECT user_id FROM users WHERE email=?", (EMAIL,)).fetchone()
        if row and "--reset" not in sys.argv:
            print(f"Demo account already exists. Log in with {EMAIL} / {PASSWORD}  (use --reset to rebuild it)")
            return
        if row:
            for (name, prev) in db.execute("SELECT file_path, preview_path FROM documents WHERE user_id=?", (row[0],)):
                for n in (name, prev):
                    if n and os.path.exists(os.path.join(app.config["UPLOAD_FOLDER"], n)):
                        os.remove(os.path.join(app.config["UPLOAD_FOLDER"], n))
            db.execute("DELETE FROM users WHERE user_id=?", (row[0],))
            db.commit()
        uid = create_user(db, "Demo User", EMAIL, PASSWORD)

        random.seed(2026)
        today = date.today()
        start = today - timedelta(days=175)
        weights = {"Groceries": 6, "Dining": 5, "Transport": 5, "Health": 2, "Electronics": 1, "Utilities": 2}
        paths = []
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(36):
                r = G.make(i)
                while random.random() > weights[r["category"]] / 6:       # more groceries/dining than gadgets
                    r = G.make(i)
                d = start + timedelta(days=int(175 * (i + random.random()) / 36))
                r["date_text"] = f"{d.day:02d}/{d.month:02d}/{d.year}"
                noise = random.choice(["clean", "clean", "clean", "blur", "rotate", "speckle"])
                p = os.path.join(tmp, f"receipt_{i:02d}_{r['store'].split()[0].lower()}.png")
                G.render(r, noise).save(p)
                paths.append(p)
            samples = sorted(os.path.join(app.config["SAMPLE_FOLDER"], f) for f in os.listdir(app.config["SAMPLE_FOLDER"])
                             if f.lower().endswith((".png", ".jpg", ".jpeg", ".pdf")))
            ok = review = 0
            for n, p in enumerate(paths + samples, 1):
                with open(p, "rb") as f:
                    try:
                        _, rec = process_upload(db, uid, FileStorage(stream=f, filename=os.path.basename(p)))
                        ok += 1
                        review += rec["status"] == "needs_review"
                    except UploadError as e:
                        print("  skipped:", e)
                print(f"\r  processed {n}/{len(paths) + len(samples)}", end="", flush=True)
        print(f"\nDone: {ok} documents, {review} flagged for review.")
        print(f"Start the app (python run.py) and log in with {EMAIL} / {PASSWORD}")


if __name__ == "__main__":
    main()
