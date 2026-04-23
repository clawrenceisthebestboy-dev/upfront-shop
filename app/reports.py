"""Profit & Loss reports — daily and monthly.

This program's reporting is scoped to **credit-card and check** transactions
only. That's by design:
  * invoices closed as Card or Check (status='paid' / 'archived')
  * open invoices issued in the period (A/R snapshot)
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


def day_bounds(day: dt.date) -> Tuple[str, str]:
    """Return [start, end) half-open ISO bounds for a single calendar day."""
    start = day
    end = day + dt.timedelta(days=1)
    return start.isoformat(), end.isoformat()


def week_bounds(any_day: dt.date, week_starts_on: int = 0) -> Tuple[str, str]:
    """Return [start, end) half-open ISO bounds for the 7-day week that
    contains ``any_day``. ``week_starts_on`` uses Python's weekday numbering
    (Monday=0 … Sunday=6). Default is Monday-start weeks.
    """
    # days since the week's start anchor
    offset = (any_day.weekday() - week_starts_on) % 7
    start = any_day - dt.timedelta(days=offset)
    end = start + dt.timedelta(days=7)
    return start.isoformat(), end.isoformat()


def compute_month_pl(conn: sqlite3.Connection, year: int, month: int) -> Dict:
    """Monthly P&L. Delegates to _compute_pl with month-level bounds."""
    start, end = month_bounds(year, month)
    return _compute_pl(conn, start, end)


def compute_day_pl(conn: sqlite3.Connection, day: dt.date) -> Dict:
    """Daily P&L for a single calendar day. Same shape as compute_month_pl."""
    start, end = day_bounds(day)
    return _compute_pl(conn, start, end)


def compute_week_pl(conn: sqlite3.Connection, any_day: dt.date,
                    week_starts_on: int = 0) -> Dict:
    """Weekly P&L for the week containing ``any_day``. Same shape as
    compute_day_pl / compute_month_pl."""
    start, end = week_bounds(any_day, week_starts_on=week_starts_on)
    return _compute_pl(conn, start, end)


def _compute_pl(conn: sqlite3.Connection, start: str, end: str) -> Dict:
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
    # Renamed from "cash_discounts" — in practice, cash invoices are deleted
    # from the DB before month-end per shop policy, so the only discount rows
    # this loop ever sees are check-paid jobs. No cash figures appear here.
    check_discounts_given = Decimal("0")
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
        # The 3.5% card-processing adjustment is baked into every invoice;
        # check-paid jobs get a matching 3.5% discount that cancels it.
        # (Cash-paid jobs do not survive in the DB to be seen here.)
        card_fees_absorbed += totals.non_cash_adjustment
        check_discounts_given += totals.cash_check_discount
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

    gross_revenue = parts_rev + labor_rev
    # Card processing is approximately net-zero (surcharge ~ processor fee).
    processor_fee_est = card_fees_absorbed
    net_revenue = gross_revenue - check_discounts_given
    # Combined gross profit = parts profit + labor profit - processor fees.
    # Cash sales are intentionally excluded from this report — they're
    # tracked on paper per shop policy (see module docstring).
    gross_profit = parts_profit + labor_profit - processor_fee_est

    # Margin % per line — guard against Decimal 0/0 producing NaN (no exception raised)
    if parts_rev > 0:
        parts_margin_pct = parts_profit / parts_rev * 100
        if parts_margin_pct.is_nan():
            parts_margin_pct = Decimal("0")
    else:
        parts_margin_pct = Decimal("0")

    if labor_rev > 0:
        labor_margin_pct = labor_profit / labor_rev * 100
        if labor_margin_pct.is_nan():
            labor_margin_pct = Decimal("0")
    else:
        labor_margin_pct = Decimal("0")

    if net_revenue > 0:
        gross_margin_pct = gross_profit / net_revenue * 100
        if gross_margin_pct.is_nan():
            gross_margin_pct = Decimal("0")
    else:
        gross_margin_pct = Decimal("0")

    return {
        "period_start": start, "period_end": end,
        "invoice_count": invoice_count,
        "paid_count": paid_count,
        # Revenue
        "parts_revenue": parts_rev,
        "labor_revenue": labor_rev,
        "gross_revenue": gross_revenue,
        # COGS
        "parts_cost": parts_cost,
        "wage_cost": wage_cost,
        # Profit split — the thing Josh wants called out
        "parts_profit": parts_profit,
        "labor_profit": labor_profit,
        "parts_margin_pct": parts_margin_pct,
        "labor_margin_pct": labor_margin_pct,
        # Other
        "tax_collected": tax_collected,
        "card_surcharge_collected": card_fees_absorbed,
        "processor_fee_est": processor_fee_est,
        "check_discounts_given": check_discounts_given,
        "open_ar": open_ar,
        "net_revenue": net_revenue,
        "gross_profit": gross_profit,
        "gross_margin_pct": (gross_profit / net_revenue * 100) if net_revenue > 0 else Decimal("0"),
    }


def render_pl_pdf(out_path: str | Path, shop: Dict[str,str], pl: Dict,
                  year: int | None = None, month: int | None = None,
                  *, period_label: str | None = None,
                  file_slug: str | None = None) -> None:
    """Render a P&L PDF. Accepts either (year, month) for a monthly report or
    a pre-formatted period_label (e.g. "April 16, 2026") for a daily one.
    file_slug is used in the PDF title metadata only.
    """
    out_path = str(out_path)
    if period_label is None:
        if year is None or month is None:
            raise ValueError("provide period_label, or both year and month")
        period_label = dt.date(year, month, 1).strftime("%B %Y")
        if file_slug is None:
            file_slug = f"{year}-{month:02d}"
    doc = SimpleDocTemplate(out_path, pagesize=LETTER,
                            leftMargin=0.7*inch, rightMargin=0.7*inch,
                            topMargin=0.6*inch, bottomMargin=0.6*inch,
                            title=f"P&L {file_slug or period_label}")
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Heading1"], fontName="Helvetica-Bold",
                        fontSize=20, leading=22, textColor=NAVY, spaceAfter=4)
    sub = ParagraphStyle("sub", parent=ss["BodyText"], fontName="Helvetica",
                         fontSize=10, textColor=GREY)
    body = ParagraphStyle("body", parent=ss["BodyText"], fontName="Helvetica", fontSize=10)
    story = []
    story.append(Paragraph(f"{shop.get('shop_name','')} — Profit & Loss", h1))
    story.append(Paragraph(period_label, sub))
    story.append(HRFlowable(width="100%", thickness=1, color=NAVY, spaceBefore=6, spaceAfter=6))

    # ---- Top summary: revenue ----
    # Row indices:
    #   0 header "Revenue"
    #   1 parts revenue
    #   2 labor revenue
    #   3 gross revenue (bold, subtotal)
    #   4 less check discounts given
    #   5 net revenue (bold, subtotal, underlined)
    rev_rows = [
        ["Revenue", ""],
        ["  Parts & materials revenue", _money(pl["parts_revenue"])],
        ["  Labor revenue", _money(pl["labor_revenue"])],
        ["  Gross revenue", _money(pl["gross_revenue"])],
        ["  Less: check discounts given", f"-{_money(pl['check_discounts_given'])}"],
        ["  Net revenue", _money(pl["net_revenue"])],
    ]
    t = Table(rev_rows, colWidths=[4.2*inch, 2.3*inch])
    t.setStyle(TableStyle([
        ("FONTNAME", (0,0), (-1,-1), "Helvetica"),
        ("FONTSIZE", (0,0), (-1,-1), 10),
        ("ALIGN", (1,0), (1,-1), "RIGHT"),
        ("TEXTCOLOR",(0,0),(0,0),NAVY), ("FONTNAME",(0,0),(0,0),"Helvetica-Bold"),
        ("FONTNAME",(0,3),(-1,3),"Helvetica-Bold"),
        ("FONTNAME",(0,5),(-1,5),"Helvetica-Bold"),
        ("LINEABOVE",(0,5),(-1,5),0.5,NAVY),
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
        ["  Card processing adjustment collected",  _money(pl["card_surcharge_collected"])],
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
        "<b>Scope:</b> credit-card and check transactions only.",
        ParagraphStyle("note", parent=body, fontSize=9, textColor=GREY, leading=12)
    ))
    doc.build(story)
