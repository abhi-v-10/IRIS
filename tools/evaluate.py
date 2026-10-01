"""Evaluate the pipeline on labelled synthetic receipts.

Usage:  python tools/gen_receipts.py data_synth     (creates 60 receipts + gt.json)
        python tools/evaluate.py data_synth         (prints and saves results.json)
"""
import json
import os
import sys
import time
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from iris.pipeline import configure_tesseract, process  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else "data_synth"
ARITH = ("items_sum_mismatch", "total_mismatch")


def prf(rows):
    tp = sum(r["tp"] for r in rows); fp = sum(r["fp"] for r in rows); fn = sum(r["fn"] for r in rows)
    p = tp / (tp + fp) if tp + fp else 0
    rc = tp / (tp + fn) if tp + fn else 0
    return dict(precision=round(100 * p, 1), recall=round(100 * rc, 1),
                f1=round(200 * p * rc / (p + rc), 1) if p + rc else 0.0)


def pct(key, rows):
    return round(100 * sum(r[key] for r in rows) / len(rows), 1)


def main():
    configure_tesseract()
    gt = json.load(open(os.path.join(DATA, "gt.json")))
    res = []
    for g in gt:
        t = time.time()
        r = process(os.path.join(DATA, f"r{g['id']:03d}.png"), today=date(2030, 1, 1))
        dt = time.time() - t
        it_gt = {(i["name"].lower(), i["amount"]) for i in g["items"]}
        it_pr = {(i["name"].lower(), i["amount"]) for i in r["items"]}
        res.append(dict(id=g["id"], noise=g["noise"],
                        store=(r["vendor"] or "").lower() == g["store"].lower(),
                        date=r["date"] == g["date"],
                        total=r["total"] is not None and abs(r["total"] - g["total"]) < 0.01,
                        cat=r["category"] == g["category"],
                        tp=len(it_gt & it_pr), fp=len(it_pr - it_gt), fn=len(it_gt - it_pr),
                        amounts_ok=all(v is not None and abs(v - g[k]) < 0.01
                                       for k, v in (("subtotal", r["subtotal"]), ("tax", r["tax"]), ("total", r["total"]))),
                        flagged=any(f in ARITH for f in r["flags"]), conf=r["ocr_confidence"], time=dt))
        res[-1]["record_ok"] = res[-1]["amounts_ok"] and not (res[-1]["fn"] or res[-1]["fp"])
    out = {"n": len(res), "overall": {k: pct(k, res) for k in ("store", "date", "total", "cat")},
           "items": prf(res), "by_noise": {}}
    for n in ("clean", "blur", "rotate", "speckle"):
        rows = [r for r in res if r["noise"] == n]
        out["by_noise"][n] = {**{k: pct(k, rows) for k in ("store", "date", "total", "cat")}, **prf(rows),
                              "n": len(rows), "conf": round(sum(r["conf"] for r in rows) / len(rows), 1)}
    err = [r for r in res if not r["record_ok"]]
    out["validator"] = dict(records_with_errors=len(err), flagged=sum(r["flagged"] for r in err),
                            false_alarms=sum(1 for r in res if r["flagged"] and r["record_ok"]),
                            fully_correct_records=len(res) - len(err),
                            all_items_correct=sum(1 for r in res if not (r["fn"] or r["fp"])))
    times = sorted(r["time"] for r in res)
    out["time_s"] = dict(mean=round(sum(times) / len(times), 2), median=round(times[len(times) // 2], 2),
                         max=round(times[-1], 2))
    json.dump(out, open(os.path.join(DATA, "results.json"), "w"), indent=1)
    json.dump(res, open(os.path.join(DATA, "per_receipt.json"), "w"), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
