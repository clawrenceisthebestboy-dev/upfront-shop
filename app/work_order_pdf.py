"""Render a technician-facing work order PDF.

A work order is what the tech gets on the bay wall. Unlike the customer
invoice, it contains NO pricing and NO labor times — just:

  * Shop header
  * What the customer reported (customer concerns) — big and prominent
  * Customer contact block
  * Vehicle block
  * The list of parts/repairs needed, with no dollar figures
  * Blank lines for technician-written notes + sign-off

Work orders are printed, not saved to the database — callers render them
to a temp file, send them to the printer, and move on.
"""
from __future__ import annotations
import os
from pathlib import Path
from typing import Dict, List

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
    Image,
)

from .pricing import LineItem


NAVY = colors.HexColor("#0B2545")
GREY = colors.HexColor("#4A4A4A")
LIGHT = colors.HexColor("#F2F4F8")
ACCENT = colors.HexColor("#C5363A")


def render_work_order_pdf(
    out_path: str | Path,
    shop: Dict[str, str],
    customer: Dict[str, str],
    vehicle: Dict[str, str] | None,
    job: Dict[str, str],
    lines: List[LineItem],
) -> None:
    """Write a work-order PDF for the tech to ``out_path``.

    ``lines`` is the full set of line items from the estimate. Both parts
    and labor descriptions are copied over — part lines show their quantity
    (useful for pulling stock), labor lines show only the description
    (their time is intentionally hidden so techs aren't boxed in).
    """
    out_path = str(out_path)
    doc = SimpleDocTemplate(
        out_path, pagesize=LETTER,
        leftMargin=0.6*inch, rightMargin=0.6*inch,
        topMargin=0.5*inch, bottomMargin=0.5*inch,
        title=f"Work Order {job.get('number','')}",
    )
    story = []
    ss = getSampleStyleSheet()

    h1 = ParagraphStyle("h1", parent=ss["Heading1"], fontName="Helvetica-Bold",
                        fontSize=22, leading=24, textColor=NAVY, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold",
                        fontSize=13, leading=15, textColor=NAVY,
                        spaceBefore=8, spaceAfter=4)
    body = ParagraphStyle("body", parent=ss["BodyText"], fontName="Helvetica",
                          fontSize=10.5, leading=14, textColor=colors.black)
    label = ParagraphStyle("label", parent=body, fontName="Helvetica-Bold",
                           fontSize=10, textColor=NAVY)
    concerns_style = ParagraphStyle(
        "concerns", parent=body, fontName="Helvetica-Bold",
        fontSize=14, leading=18, textColor=colors.black,
    )
    small = ParagraphStyle("small", parent=body, fontSize=8, leading=10, textColor=GREY)

    # ---------- Header: shop info + big "WORK ORDER" tag ----------
    shop_block = (
        f"<b>{shop.get('shop_name','')}</b><br/>"
        f"{shop.get('shop_address1','')}"
        + (f"<br/>{shop.get('shop_address2','')}" if shop.get('shop_address2') else "")
        + f"<br/>{shop.get('shop_city','')}, {shop.get('shop_state','')} {shop.get('shop_zip','')}<br/>"
        f"{shop.get('shop_phone','')}"
        + (f" &nbsp;·&nbsp; {shop.get('shop_email','')}" if shop.get('shop_email') else "")
        + f"<br/>{shop.get('shop_website','')}"
    )
    wo_label = (
        f"WORK ORDER<br/>"
        f"<font size=10 color='#666'>#{job.get('number','')}</font>"
    )

    logo_path = (shop.get("logo_path") or "").strip()
    logo_flow = None
    if logo_path and os.path.isfile(logo_path):
        try:
            logo_flow = Image(logo_path, width=1.1*inch, height=1.1*inch,
                              kind="proportional")
        except Exception:
            logo_flow = None

    if logo_flow is not None:
        header_tbl = Table(
            [[logo_flow,
              Paragraph(shop_block, body),
              Paragraph(wo_label, ParagraphStyle("wok", parent=h1, alignment=2))]],
            colWidths=[1.25*inch, 2.45*inch, 3.6*inch],
        )
    else:
        header_tbl = Table(
            [[Paragraph(shop_block, body),
              Paragraph(wo_label, ParagraphStyle("wok", parent=h1, alignment=2))]],
            colWidths=[3.7*inch, 3.6*inch],
        )
    header_tbl.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("BOTTOMPADDING", (0,0), (-1,-1), 2),
    ]))
    story.append(header_tbl)
    story.append(HRFlowable(width="100%", thickness=1.4, color=NAVY,
                            spaceBefore=6, spaceAfter=8))

    # ---------- Customer concerns (prominent) ----------
    concerns_raw = (job.get("notes") or "").strip()
    story.append(Paragraph("CUSTOMER CONCERNS", h2))
    if concerns_raw:
        story.append(Paragraph(concerns_raw.replace("\n", "<br/>"), concerns_style))
    else:
        # Empty-but-visible box so techs can fill it in by hand if the
        # service writer didn't type anything.
        story.append(Paragraph(
            "<font color='#888'><i>(none recorded — ask the customer)</i></font>",
            concerns_style,
        ))
    story.append(Spacer(1, 10))

    # ---------- Customer & Vehicle side-by-side ----------
    cust_block = (
        f"<b>Customer:</b> {customer.get('first_name','')} "
        f"{customer.get('last_name','')}<br/>"
        f"<b>Phone:</b> {customer.get('phone','') or '—'}<br/>"
        f"<b>Address:</b> {customer.get('address1','') or '—'}"
    )
    city = customer.get("city", "") or ""
    state = customer.get("state", "") or ""
    zipc = customer.get("zip", "") or ""
    city_line = ", ".join(p for p in [city, state] if p)
    if zipc:
        city_line = f"{city_line} {zipc}".strip()
    if city_line:
        cust_block += f"<br/>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; {city_line}"

    if vehicle:
        yr = vehicle.get("year") or ""
        mk = vehicle.get("make") or ""
        md = vehicle.get("model") or ""
        veh_line = f"{yr} {mk} {md}".strip() or "—"
        veh_block = (
            f"<b>Vehicle:</b> {veh_line}<br/>"
            f"<b>Plate:</b> {vehicle.get('plate','') or '—'}"
            f" &nbsp;&nbsp; <b>VIN:</b> {vehicle.get('vin','') or '—'}<br/>"
            f"<b>Mileage:</b> {vehicle.get('mileage') or job.get('odometer_in') or '—'}"
        )
    else:
        veh_block = "<b>Vehicle:</b> —"

    side_tbl = Table(
        [[Paragraph(cust_block, body), Paragraph(veh_block, body)]],
        colWidths=[3.6*inch, 3.7*inch],
    )
    side_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), LIGHT),
        ("BOX", (0,0), (-1,-1), 0.5, GREY),
        ("INNERGRID", (0,0), (-1,-1), 0.25, GREY),
        ("LEFTPADDING", (0,0), (-1,-1), 8),
        ("RIGHTPADDING", (0,0), (-1,-1), 8),
        ("TOPPADDING", (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
    ]))
    story.append(side_tbl)
    story.append(Spacer(1, 12))

    # ---------- Parts / repairs needed (NO prices, NO labor times) ----------
    story.append(Paragraph("PARTS / REPAIRS NEEDED", h2))

    rows = [["", "Description", "Qty"]]
    for l in lines:
        if l.kind == "part":
            # Show description and how many to pull. No cost, no price.
            qty_txt = f"{l.quantity:g}" if l.quantity else ""
            rows.append(["☐", Paragraph(l.description, body), qty_txt])
        else:
            # Labor line: description only — NO labor time/quantity on purpose.
            rows.append(["☐", Paragraph(l.description, body), ""])

    # If the estimate has no line items yet, still print the grid with
    # blank rows so the tech can write in what they did.
    if len(rows) == 1:
        for _ in range(6):
            rows.append(["☐", "", ""])
    else:
        # Always leave a handful of blank lines at the end for the tech to
        # add anything they did that wasn't on the original estimate.
        for _ in range(4):
            rows.append(["☐", "", ""])

    parts_tbl = Table(rows, colWidths=[0.35*inch, 5.85*inch, 1.10*inch],
                      repeatRows=1)
    parts_tbl.setStyle(TableStyle([
        ("BACKGROUND",   (0,0), (-1,0), NAVY),
        ("TEXTCOLOR",    (0,0), (-1,0), colors.white),
        ("FONTNAME",     (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",     (0,0), (-1,0), 10.5),
        ("ALIGN",        (2,0), (2,-1), "RIGHT"),
        ("ALIGN",        (0,0), (0,-1), "CENTER"),
        ("VALIGN",       (0,0), (-1,-1), "MIDDLE"),
        ("FONTNAME",     (0,1), (-1,-1), "Helvetica"),
        ("FONTSIZE",     (0,1), (-1,-1), 11),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, LIGHT]),
        ("LEFTPADDING",  (0,0), (-1,-1), 6),
        ("RIGHTPADDING", (0,0), (-1,-1), 6),
        ("TOPPADDING",   (0,0), (-1,-1), 6),
        ("BOTTOMPADDING",(0,0), (-1,-1), 6),
        ("BOX",          (0,0), (-1,-1), 0.4, GREY),
        ("LINEBELOW",    (0,1), (-1,-2), 0.25, GREY),
    ]))
    story.append(parts_tbl)
    story.append(Spacer(1, 12))

    # ---------- Blank lines for technician notes ----------
    story.append(Paragraph("TECHNICIAN NOTES", h2))
    note_rows = [[""] for _ in range(5)]
    notes_tbl = Table(note_rows, colWidths=[7.3*inch], rowHeights=[0.32*inch]*5)
    notes_tbl.setStyle(TableStyle([
        ("LINEBELOW", (0,0), (-1,-1), 0.4, GREY),
        ("LEFTPADDING", (0,0), (-1,-1), 2),
        ("RIGHTPADDING", (0,0), (-1,-1), 2),
        ("TOPPADDING", (0,0), (-1,-1), 2),
        ("BOTTOMPADDING", (0,0), (-1,-1), 2),
    ]))
    story.append(notes_tbl)
    story.append(Spacer(1, 14))

    # ---------- Sign-off ----------
    sign_tbl = Table([[
        Paragraph("Technician: _______________________________", body),
        Paragraph("Date: _______________", body),
    ]], colWidths=[4.5*inch, 2.8*inch])
    sign_tbl.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "BOTTOM"),
        ("LEFTPADDING", (0,0), (-1,-1), 0),
        ("RIGHTPADDING", (0,0), (-1,-1), 0),
    ]))
    story.append(sign_tbl)

    # Footer: tiny reminder that this is NOT a priced invoice.
    story.append(Spacer(1, 12))
    story.append(HRFlowable(width="100%", thickness=0.3, color=GREY,
                            spaceBefore=2, spaceAfter=2))
    story.append(Paragraph(
        "Internal work order — no pricing, no labor times. "
        "For the customer's priced copy, print the Estimate or Invoice from "
        "the Jobs tab.",
        small,
    ))

    doc.build(story)
