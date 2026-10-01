"""CSV and PDF export of the user's (filtered) expense records."""
import csv
import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .analytics import money


def to_csv(docs, items_by_doc):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["doc_id", "date", "vendor", "gstin", "invoice_no", "category", "subtotal", "tax", "total",
                "status", "ocr_confidence", "items"])
    for d in docs:
        items = "; ".join(f"{i['name']} x{i['qty']} = {i['amount']:.2f}" for i in items_by_doc.get(d["doc_id"], []))
        w.writerow([d["doc_id"], d["doc_date"] or "", d["vendor"] or "", d["gstin"] or "", d["invoice_no"] or "",
                    d["category"] or "", _f(d["subtotal"]), _f(d["tax"]), _f(d["total"]), d["status"],
                    d["ocr_confidence"] if d["ocr_confidence"] is not None else "", items])
    return "﻿" + buf.getvalue()          # BOM so Excel opens the ₹/UTF-8 text correctly


def _f(v):
    return f"{v:.2f}" if v is not None else ""


def to_pdf(user_name, filters_text, summary, docs):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=16 * mm,
                            bottomMargin=16 * mm, title="Expense Report")
    st = getSampleStyleSheet()
    navy = colors.HexColor("#1f3a5f")
    rs = lambda v: money(v, "Rs. ")                                       # noqa: E731  (Rs. prints in every font)
    story = [Paragraph("Expense Report", st["Title"]),
             Paragraph(f"{user_name} &nbsp;|&nbsp; generated {datetime.now():%d %b %Y, %H:%M}", st["Normal"]),
             Paragraph(f"Filters: {filters_text}", st["Normal"]), Spacer(1, 8)]
    k = summary["kpis"]
    story.append(_table([["Total spent", "Documents", "Average per document", "Needs review"],
                         [rs(k["spent"]), str(k["documents"]), rs(k["average"]), str(k["needs_review"])]],
                        [45 * mm] * 4, navy))
    story.append(Spacer(1, 10))
    story.append(Paragraph("Spending by category", st["Heading3"]))
    total = k["spent"] or 1
    story.append(_table([["Category", "Documents", "Amount", "Share"]] +
                        [[c["category"], str(c["n"]), rs(c["spent"]), f"{100 * c['spent'] / total:.1f}%"]
                         for c in summary["by_category"]], [70 * mm, 30 * mm, 45 * mm, 30 * mm], navy))
    if summary["monthly"]:
        story.append(Spacer(1, 10))
        story.append(Paragraph("Monthly trend", st["Heading3"]))
        story.append(_table([["Month", "Documents", "Amount"]] +
                            [[m["label"], str(m["n"]), rs(m["spent"])] for m in summary["monthly"]],
                            [70 * mm, 30 * mm, 45 * mm], navy))
    if summary["insights"]:
        story.append(Spacer(1, 10))
        story.append(Paragraph("Insights", st["Heading3"]))
        for _, t in summary["insights"]:
            story.append(Paragraph("&bull; " + t.replace("₹", "Rs. "), st["Normal"]))
    story.append(Spacer(1, 10))
    story.append(Paragraph("Documents", st["Heading3"]))
    small = st["BodyText"].clone("small", fontSize=8, leading=10)
    rows = [["Date", "Vendor", "Category", "Total", "Status"]]
    for d in docs:
        rows.append([d["doc_date"] or "-", Paragraph(d["vendor"] or "-", small), d["category"] or "-",
                     rs(d["total"]), d["status"].replace("_", " ")])
    story.append(_table(rows, [24 * mm, 64 * mm, 30 * mm, 32 * mm, 28 * mm], navy, fs=8))
    doc.build(story)
    return buf.getvalue()


def _table(rows, widths, head, fs=9):
    t = Table(rows, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), head), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                           ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), fs),
                           ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b8c2cf")),
                           ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f4f8")]),
                           ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    return t
