"""Spending summaries, trends and insights for the dashboard, exports and API."""
from datetime import datetime

from .services import filter_sql


def month_label(ym):
    try:
        return datetime.strptime(ym, "%Y-%m").strftime("%b %Y")
    except (TypeError, ValueError):
        return ym or "Undated"


def summarize(db, user_id, f):
    where, params = filter_sql(user_id, f)
    base = f"FROM documents d LEFT JOIN categories c USING(category_id) WHERE {where}"
    k = db.execute(f"""SELECT COUNT(*) n, COALESCE(SUM(d.total),0) spent, COALESCE(AVG(d.total),0) avg,
                       COALESCE(MAX(d.total),0) biggest, SUM(d.status='needs_review') review,
                       SUM(d.status='verified') verified, AVG(d.ocr_confidence) conf {base}""", params).fetchone()
    by_cat = [dict(r) for r in db.execute(
        f"""SELECT COALESCE(c.name,'Others') category, ROUND(SUM(d.total),2) spent, COUNT(*) n
            {base} GROUP BY COALESCE(c.name,'Others') ORDER BY spent DESC""", params)]
    monthly = [dict(r) for r in db.execute(
        f"""SELECT substr(d.doc_date,1,7) month, ROUND(SUM(d.total),2) spent, COUNT(*) n
            {base} AND d.doc_date IS NOT NULL GROUP BY month ORDER BY month""", params)]
    vendors = [dict(r) for r in db.execute(
        f"""SELECT d.vendor, ROUND(SUM(d.total),2) spent, COUNT(*) n
            {base} AND d.vendor IS NOT NULL GROUP BY lower(d.vendor) ORDER BY spent DESC LIMIT 6""", params)]
    cat_month = [dict(r) for r in db.execute(
        f"""SELECT substr(d.doc_date,1,7) month, COALESCE(c.name,'Others') category, SUM(d.total) spent
            {base} AND d.doc_date IS NOT NULL GROUP BY month, category""", params)]
    biggest = db.execute(f"""SELECT d.doc_id, d.vendor, d.total, d.doc_date {base}
                             ORDER BY d.total DESC LIMIT 1""", params).fetchone()
    for m in monthly:
        m["label"] = month_label(m["month"])
    kpis = dict(documents=k["n"], spent=round(k["spent"] or 0, 2), average=round(k["avg"] or 0, 2),
                needs_review=k["review"] or 0, verified=k["verified"] or 0,
                ocr_confidence=round(k["conf"], 1) if k["conf"] is not None else None)
    return dict(kpis=kpis, by_category=by_cat, monthly=monthly, top_vendors=vendors,
                insights=insights(kpis, by_cat, monthly, vendors, cat_month, biggest))


def insights(kpis, by_cat, monthly, vendors, cat_month, biggest):
    """Plain-language observations, most useful first. Each: (kind, text)."""
    out = []
    if not kpis["documents"]:
        return out
    total = kpis["spent"] or 0
    if by_cat and total:
        top = by_cat[0]
        out.append(("info", f"{top['category']} is your largest expense head: {money(top['spent'])} "
                            f"({100 * top['spent'] / total:.0f}% of total spending)."))
    if len(monthly) >= 2:
        cur, prev = monthly[-1], monthly[-2]
        if prev["spent"]:
            ch = 100 * (cur["spent"] - prev["spent"]) / prev["spent"]
            kind = "warn" if ch > 15 else ("good" if ch < -15 else "info")
            word = "more" if ch >= 0 else "less"
            out.append((kind, f"You spent {abs(ch):.0f}% {word} in {cur['label']} ({money(cur['spent'])}) "
                              f"than in {prev['label']} ({money(prev['spent'])})."))
        cm = {}
        for r in cat_month:
            cm.setdefault(r["category"], {})[r["month"]] = r["spent"]
        rises = [(c, v.get(cur["month"], 0) - v.get(prev["month"], 0)) for c, v in cm.items()]
        rises = [r for r in rises if r[1] > 0]
        if rises:
            c, d = max(rises, key=lambda r: r[1])
            out.append(("info", f"{c} rose the most in {cur['label']}: {money(d)} more than the previous month."))
    if len(monthly) >= 1:
        avg = sum(m["spent"] for m in monthly) / len(monthly)
        out.append(("info", f"Average monthly spending is {money(avg)} across {len(monthly)} month(s)."))
    if biggest is not None and biggest["total"]:
        out.append(("info", f"Largest single expense: {money(biggest['total'])} at {biggest['vendor'] or 'unknown vendor'}"
                            f"{' on ' + _day(biggest['doc_date']) if biggest['doc_date'] else ''}."))
    if vendors:
        v = vendors[0]
        out.append(("info", f"You spend most at {v['vendor']}: {money(v['spent'])} over {v['n']} bill(s)."))
    if kpis["needs_review"]:
        out.append(("warn", f"{kpis['needs_review']} document(s) need your review before the numbers are fully reliable."))
    return out


def _day(iso):
    try:
        return datetime.strptime(iso, "%Y-%m-%d").strftime("%d %b %Y")
    except (TypeError, ValueError):
        return iso


def money(v, symbol="₹"):
    """Indian digit grouping: 1234567.5 -> ₹12,34,567.50"""
    if v is None:
        return "-"
    neg = v < 0
    whole, frac = f"{abs(v):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{'-' if neg else ''}{symbol}{whole}.{frac}"
