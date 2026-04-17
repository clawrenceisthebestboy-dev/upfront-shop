"""Monthly Profit & Loss.

CAUTION: per shop policy, cash-paid invoices are deleted from the DB after
printing. Those numbers are NOT in the P&L produced by this module. The P&L
here covers electronically-tracked jobs only:
  * invoices closed as Card or Check (status='paid' / 'archived')
  * open invoices issued in the month (A/R snapshot)

Add cash manually using the "Cash sales (external)" line in the printed report.
"""
from __future__ import annotations
import datetime as dt
import sqlite3
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Tuple

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
)

from .markup import quantize
from .pricing import LineItem, compute_totals

NAVY = colors.HexColor("#0B2545")
GREY = colors.HexColor("#4A4A4A")
LIGHT = colors.HexColor("#F2F4F8")


def _money(v) -> str:
    d = Decimal(str(v))
    s = f"${abs(d):,.2f}"
    return f"({s})" if d < 0 else s


def month_bounds(year: int, month: int) -> Tuple[str, str]:
    start = dt.date(year, month, 1)
    if month == 12:
        end = dt.date(year + 1, 1, 1)
    else:
        end = dt.date(year, month + 1, 1)
    return start.isoformat(), end.isoformat()


def compute_month_pl(conn: sqlite3.Connection, year: int, month: int,
                     external_cash_sales: Decimal = Decimal("0")) -> Dict:
    start, end = month_bounds(year, month)
    jobs = conn.execute(
        "SELECT * FROM jobs "
        "WHERE (invoiced_at IS NOT NULL AND invoiced_at >= ? AND invoiced_at < ?) "
        "   OR (paid_at IS NOT NULL AND paid_at >= ? AND paid_at < ?)",
        (start, end, start, end),
    ).fetchall()

    parts_rev = Decimal("0")
    labor_rev = Decimal("0")
    parts_cost = Decimal("0")
    tax_collected = Decimal("0")
    card_fees_absorbed = Decimal("0")
    cash_discounts_given = Decimal("0")
    paid_count = 0
    invoice_count = 0
    open_ar = Decimal("0")

    for j in jobs:
        line_rows = conn.execute(
            "SELECT * FROM line_items WHERE job_id=?", (j["id"],)
        ).fetchall()
        lines = [
            LineItem(
                kind=r["kind"], description=r["description"],
                quantity=Decimal(str(r["quantity"])),
                unit_cost=Decimal(str(r["unit_cost"])),
                unit_price=Decimal(str(r["unit_price"])),
                taxable=bool(r["taxable"]),
                part_id=r["part_id"],
            ) for r in line_rows
        ]
        totals = compute_totals(
            lines,
            payment_method=j["payment_method"] or "unpaid",
            tax_rate=Decimal(str(j["tax_rate"])),
        )
        invoice_count += 1
        parts_rev += totals.parts_subtotal
        labor_rev += totals.labor_subtotal
        parts_cost += totals.parts_cost
        tax_collected += totals.tax
        # The 3.5% non-cash adjustment is always baked into every invoice;
        # cash/check-paid jobs also get a matching 3.5% discount which
        # cancels it. We track both for transparency on the P&L.
        card_fees_absorbed += totals.non_cash_adjustment
        cash_discounts_given += totals.cash_check_discount
        if j["status"] in ("paid","archived"):
            paid_count += 1
        else:
            open_ar += totals.grand_total

    # Time clock labor cost
    te = conn.execute(
        "SELECT SUM( (julianday(COALESCE(clock_out,datetime('now'))) - julianday(clock_in)) * 24 * hourly_rate ) AS cost "
        "FROM time_entries WHERE clock_in >= ? AND clock_in < ?",
        (start, end),
    ).fetchone()
    wage_cost = Decimal(str(te["cost"] or 0)).quantize(Decimal("0.01"))

    # --- Profit broken out separately for parts vs labor ---
    parts_profit = parts_rev - parts_cost
    # Labor profit = labor revenue minus technician wages (from timeclock).
    # If there's no timeclock data, labor_profit == labor_rev (pure revenue).
    labor_profit = labor_rev - wage_cost

    # Margin % per line
    parts_margin_pct = (parts_profit / parts_rev * 100) if parts_rev > 0 else Decimal("0")
    labor_margin_pct = (labor_profit / labor_rev * 100) if labor_rev > 0 else Decimal("0")

    gross_revenue = parts_rev + labor_rev + external_cash_sales
    # Processing is approximately net-zero (surcharge ~ processor fee).
    processor_fee_est = card_fees_absorbed
    net_revenue = gross_revenue - cash_discounts_given
    # Combined gross profit = parts profit + labor profit - processor fees
    # (external cash sales are NOT included in parts/labor profit split because
    # the shop keeps those records externally per policy)
    gross_profit = parts_profit + labor_profit - processor_fee_est

    return {
        "period_start": start, "period_end": end,
        "invoice_count": invoice_count,
        "paid_count": paid_count,
        # Revenue
        "parts_revenue": parts_rev,
        "labor_revenue": labor_rev,
        "external_cash_sales": external_cash_sales,
        "gross_revenue": gross_revenue,
        # COGS
        "parts_cost": parts_cost,
        "wage_cost": wage_cost,
        # Profit split — the thing Jon wants called out
        "parts_profit": parts_profit,
        "labor_profit": labor_profit,
        "parts_margin_pct": parts_margin_pct,
        "labor_margin_pct": labor_margin_pct,
        # Other
        "tax_collected": tax_collected,
        "card_surcharge_collected": card_fees_absorbed,
        "processor_fee_est": processor_fee_est,
        "cash_discounts_given": cash_discounts_given,
        "open_ar": open_ar,
        "net_revenue": net_revenue,
        "gross_profit": gross_profit,
        "gross_margin_pct": (gross_profit / net_revenue * 100) if net_revenue > 0 else Decimal("0"),
    }


def render_pl_pdf(out_path: str | Path, shop: Dict[str,str], pl: Dict, year: int, month: int) -> None:
    out_path = str(out_path)
    doc = SimpleDocTemplate(out_path, pagesize=LETTER,
                            leftMargin=0.7*inch, rightMargin=0.7*inch,
                            topMargin=0.6*inch, bottomMargin=0.6*inch,
                            title=f"P&L {year}-{month:02d}")
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Heading1"], fontName="Helvetica-Bold",
                        fontSize=20, leading=22, textColor=NAVY, spaceAfter=4)
    sub = ParagraphStyle("sub", parent=ss["BodyText"], fontName="Helvetica",
                         fontSize=10, textColor=GREY)
    body = ParagraphStyle("body", parent=ss["BodyText"], fontName="Helvetica", fontSize=10)
    story = []
    month_name = dt.date(year, month, 1).strftime("%B %Y")
    story.append(Paragraph(f"{shop.get('shop_name','')} — Profit & Loss", h1))
    story.append(Paragraph(month_name, sub))
    story.append(HRFlowable(width="100%", thickness=1, color=NAVY, spaceBefore=6, spaceAfter=6))

    # ---- Top summary: revenue ----
    rev_rows = [
        ["Revenue", ""],
        ["  Parts & materials revenue", _money(pl["parts_revenue"])],
        ["  Labor revenue", _money(pl["labor_revenue"])],
        ["  Cash sales (manually entered)", _money(pl["external_cash_sales"])],
        ["  Gross revenue", _money(pl["gross_revenue"])],
        ["  Less: cash discounts given", f"-{_money(pl['cash_discounts_given'])}"],
        ["  Net revenue", _money(pl["net_revenue"])],
    ]
    t = Table(rev_rows, colWidths=[4.2*inch, 2.3*inch])
    t.setStyle(TableStyle([
        ("FONTNAME", (0,0), (-1,-1), "Helvetica"),
        ("FONTSIZE", (0,0), (-1,-1), 10),
        ("ALIGN", (1,0), (1,-1), "RIGHT"),
        ("TEXTCOLOR",(0,0),(0,0),NAVY), ("FONTNAME",(0,0),(0,0),"Helvetica-Bold"),
        ("FONTNAME",(0,4),(-1,4),"Helvetica-Bold"),
        ("FONTNAME",(0,6),(-1,6),"Helvetica-Bold"),
        ("LINEABOVE",(0,6),(-1,6),0.5,NAVY),
        ("TOPPADDING",(0,0),(-1,-1),2), ("BOTTOMPADDING",(0,0),(-1,-1),2),
    ]))
    story.append(t)
    story.append(Spacer(1, 10))

    # ---- Parts & Materials profit block ----
    story.append(Paragraph(
        "<b>Parts &amp; Materials — Profitability</b>",
        ParagraphStyle("ph", parent=ss["Heading2"], fontName="Helvetica-Bold",
                       fontSize=12, textColor=NAVY)
    ))
    parts_rows = [
        ["Parts revenue (customer-facing, marked up)", _money(pl["parts_revenue"])],
        ["Parts cost (shop cost of goods)",            _money(pl["parts_cost"])],
        ["Parts profit",                               _money(pl["parts_profit"])],
        ["Parts margin",                               f"{pl['parts_margin_pct']:.1f}%"],
    ]
    t = Table(parts_rows, colWidths=[4.2*inch, 2.3*inch])
    t.setStyle(TableStyle([
        ("FONTNAME", (0,0), (-1,-1), "Helvetica"),
        ("FONTSIZE", (0,0), (-1,-1), 10),
        ("ALIGN",(1,0),(1,-1),"RIGHT"),
        ("BACKGROUND",(0,0),(-1,-1),LIGHT),
        ("BOX",(0,0),(-1,-1),0.4,GREY),
        ("FONTNAME",(0,2),(-1,2),"Helvetica-Bold"),
        ("FONTNAME",(0,3),(-1,3),"Helvetica-Bold"),
        ("TEXTCOLOR",(0,2),(-1,2),NAVY),
        ("LINEABOVE",(0,2),(-1,2),0.5,NAVY),
        ("TOPPADDING",(0,0),(-1,-1),4), ("BOTTOMPADDING",(0,0),(-1,-1),4),
    ]))
    story.append(t)
    story.append(Spacer(1, 10))

    # ---- Labor profit block ----
    story.append(Paragraph(
        "<b>Labor — Profitability</b>",
        ParagraphStyle("lh", parent=ss["Heading2"], fontName="Helvetica-Bold",
                       fontSize=12, textColor=NAVY)
    ))
    labor_rows = [
        ["Labor revenue (invoiced to customers)",          _money(pl["labor_revenue"])],
        ["Technician wages (from time-clock)",             _money(pl["wage_cost"])],
        ["Labor profit",                                   _money(pl["labor_profit"])],
        ["Labor margin",                                   f"{pl['labor_margin_pct']:.1f}%"],
    ]
    t = Table(labor_rows, colWidths=[4.2*inch, 2.3*inch])
    t.setStyle(TableStyle([
        ("FONTNAME", (0,0), (-1,-1), "Helvetica"),
        ("FONTSIZE", (0,0), (-1,-1), 10),
        ("ALIGN",(1,0),(1,-1),"RIGHT"),
        ("BACKGROUND",(0,0),(-1,-1),LIGHT),
        ("BOX",(0,0),(-1,-1),0.4,GREY),
        ("FONTNAME",(0,2),(-1,2),"Helvetica-Bold"),
        ("FONTNAME",(0,3),(-1,3),"Helvetica-Bold"),
        ("TEXTCOLOR",(0,2),(-1,2),NAVY),
        ("LINEABOVE",(0,2),(-1,2),0.5,NAVY),
        ("TOPPADDING",(0,0),(-1,-1),4), ("BOTTOMPADDING",(0,0),(-1,-1),4),
    ]))
    story.append(t)
    story.append(Spacer(1, 10))

    # ---- Combined gross profit + other ----
    bottom = [
        ["Combined gross profit", ""],
        ["  Parts profit",                          _money(pl["parts_profit"])],
        ["  Labor profit",                          _money(pl["labor_profit"])],
        ["  Less: card processor fee (est.)",       f"-{_money(pl['processor_fee_est'])}"],
        ["GROSS PROFIT",                            _money(pl["gross_profit"])],
        ["Blended gross margin",                    f"{pl['gross_margin_pct']:.1f}%"],
        ["", ""],
        ["Other",                                   ""],
        ["  Sales tax collected (remit to ME)",     _money(pl["tax_collected"])],
        ["  Non-cash adjustment collected",         _money(pl["card_surcharge_collected"])],
        ["  Open A/R (unpaid invoices)",            _money(pl["open_ar"])],
        ["  Invoices / paid this month",            f"{pl['invoice_count']} / {pl['paid_count']}"],
    ]
    t = Table(bottom, colWidths=[4.2*inch, 2.3*inch])
    t.setStyle(TableStyle([
        ("FONTNAME", (0,0), (-1,-1), "Helvetica"),
        ("FONTSIZE", (0,0), (-1,-1), 10),
        ("ALIGN",(1,0),(1,-1),"RIGHT"),
        ("TEXTCOLOR",(0,0),(0,0),NAVY), ("FONTNAME",(0,0),(0,0),"Helvetica-Bold"),
        ("LINEABOVE",(0,4),(-1,4),1,NAVY),
        ("FONTNAME",(0,4),(-1,4),"Helvetica-Bold"),
        ("FONTSIZE",(0,4),(-1,4),12),
        ("TEXTCOLOR",(0,4),(-1,4),NAVY),
        ("FONTNAME",(0,5),(-1,5),"Helvetica-Bold"),
        ("TEXTCOLOR",(0,7),(0,7),NAVY), ("FONTNAME",(0,7),(0,7),"Helvetica-Bold"),
        ("TOPPADDING",(0,0),(-1,-1),2), ("BOTTOMPADDING",(0,0),(-1,-1),2),
    ]))
    story.append(t)

    story.append(Spacer(1, 16))
    story.append(Paragraph(
        "<b>Note on cash sales:</b> per shop policy, cash-paid invoices are "
        "printed and kept physically (not retained in the app). Enter your "
        "monthly cash total on the P&L screen before printing so it lands in "
        "the 'Cash sales (manually entered)' line above.",
        ParagraphStyle("note", parent=body, fontSize=9, textColor=GREY, leading=12)
    ))
    doc.build(story)
