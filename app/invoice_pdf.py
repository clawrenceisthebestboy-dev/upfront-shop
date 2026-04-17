"""Render an estimate/invoice to a letter-size PDF.

Uses ReportLab Platypus. Customer-facing only: prices and tax, no cost or profit.
Includes the shop logo (if configured) and a QR code that links to the shop's
review page.
"""
from __future__ import annotations
import os
from decimal import Decimal
from pathlib import Path
from typing import Dict, List
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, PageBreak,
    Image,
)
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF
from reportlab.platypus import Flowable
from .pricing import LineItem, InvoiceTotals


class _QRFlowable(Flowable):
    """A Platypus-compatible QR code block.
    Renders a QR for ``data`` at the requested box size (in points)."""
    def __init__(self, data: str, size_pts: float = 90.0):
        super().__init__()
        self.data = data
        self.size = size_pts

    def wrap(self, availWidth, availHeight):
        return self.size, self.size

    def draw(self):
        qr = QrCodeWidget(self.data)
        b = qr.getBounds()
        w = b[2] - b[0]; h = b[3] - b[1]
        d = Drawing(self.size, self.size, transform=[self.size/w, 0, 0, self.size/h, 0, 0])
        d.add(qr)
        renderPDF.draw(d, self.canv, 0, 0)


NAVY = colors.HexColor("#0B2545")
GREY = colors.HexColor("#4A4A4A")
LIGHT = colors.HexColor("#F2F4F8")
ACCENT = colors.HexColor("#C5363A")


def _money(v) -> str:
    d = Decimal(str(v))
    neg = d < 0
    s = f"${abs(d):,.2f}"
    return f"({s})" if neg else s


def render_invoice_pdf(
    out_path: str | Path,
    shop: Dict[str, str],
    customer: Dict[str, str],
    vehicle: Dict[str, str] | None,
    job: Dict[str, str],
    lines: List[LineItem],
    totals: InvoiceTotals,
    doc_kind: str = "Estimate",       # Estimate / Invoice / Invoice — PAID
    payment_method: str = "unpaid",   # card|cash|check|unpaid
    footer_note: str = "",
) -> None:
    out_path = str(out_path)
    doc = SimpleDocTemplate(
        out_path, pagesize=LETTER,
        leftMargin=0.6*inch, rightMargin=0.6*inch,
        topMargin=0.5*inch, bottomMargin=0.5*inch,
        title=f"{doc_kind} {job.get('number','')}",
    )
    story = []
    ss = getSampleStyleSheet()

    h1 = ParagraphStyle("h1", parent=ss["Heading1"], fontName="Helvetica-Bold",
                        fontSize=22, leading=24, textColor=NAVY, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold",
                        fontSize=11, leading=14, textColor=NAVY, spaceBefore=6, spaceAfter=2)
    body = ParagraphStyle("body", parent=ss["BodyText"], fontName="Helvetica",
                          fontSize=10, leading=13, textColor=colors.black)
    small = ParagraphStyle("small", parent=body, fontSize=8, leading=10, textColor=GREY)
    label = ParagraphStyle("label", parent=body, fontName="Helvetica-Bold",
                           fontSize=9, textColor=NAVY)
    paid_style = ParagraphStyle("paid", parent=h1, fontSize=34, leading=36,
                                textColor=ACCENT, alignment=2)

    # ---------- Header block (logo + shop info + doc label) ----------
    shop_block = (
        f"<b>{shop.get('shop_name','')}</b><br/>"
        f"{shop.get('shop_address1','')}"
        + (f"<br/>{shop.get('shop_address2','')}" if shop.get('shop_address2') else "")
        + f"<br/>{shop.get('shop_city','')}, {shop.get('shop_state','')} {shop.get('shop_zip','')}<br/>"
        f"{shop.get('shop_phone','')}"
        + (f" &nbsp;·&nbsp; {shop.get('shop_email','')}" if shop.get('shop_email') else "")
        + f"<br/>{shop.get('shop_website','')}"
    )
    doc_label = f"{doc_kind.upper()}<br/><font size=9 color='#666'>#{job.get('number','')}</font>"

    # Logo cell (image file on disk, optional)
    logo_path = (shop.get("logo_path") or "").strip()
    logo_flow = None
    if logo_path and os.path.isfile(logo_path):
        try:
            # Fit within a 1.1"x1.1" square while preserving aspect.
            logo_flow = Image(logo_path, width=1.1*inch, height=1.1*inch, kind="proportional")
        except Exception:
            logo_flow = None

    if logo_flow is not None:
        header_tbl = Table(
            [[logo_flow,
              Paragraph(shop_block, body),
              Paragraph(doc_label, ParagraphStyle("dk", parent=h1, alignment=2))]],
            colWidths=[1.25*inch, 2.45*inch, 3.6*inch],
        )
    else:
        header_tbl = Table(
            [[Paragraph(shop_block, body),
              Paragraph(doc_label, ParagraphStyle("dk", parent=h1, alignment=2))]],
            colWidths=[3.7*inch, 3.6*inch],
        )
    header_tbl.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("BOTTOMPADDING", (0,0), (-1,-1), 2),
    ]))
    story.append(header_tbl)
    story.append(HRFlowable(width="100%", thickness=1.2, color=NAVY, spaceBefore=6, spaceAfter=6))

    # ---------- Bill To / Vehicle ----------
    cust_block = (
        f"<b>{customer.get('first_name','')} {customer.get('last_name','')}</b><br/>"
        f"{customer.get('address1','') or ''}<br/>"
        f"{customer.get('city','') or ''}{', ' if customer.get('city') else ''}"
        f"{customer.get('state','') or ''} {customer.get('zip','') or ''}<br/>"
        f"{customer.get('phone','') or ''}<br/>"
        f"{customer.get('email','') or ''}"
    )
    if vehicle:
        veh_line = f"{vehicle.get('year','') or ''} {vehicle.get('make','') or ''} {vehicle.get('model','') or ''}"
        veh_block = (
            f"<b>Vehicle</b><br/>"
            f"{veh_line}<br/>"
            f"VIN: {vehicle.get('vin','') or '—'}<br/>"
            f"Plate: {vehicle.get('plate','') or '—'}<br/>"
            f"Odometer In: {job.get('odometer_in') or '—'}"
        )
    else:
        veh_block = "<b>Vehicle</b><br/>—"

    job_meta = (
        f"<b>Date</b>: {job.get('opened_at','')[:10]}<br/>"
        f"<b>Tech</b>: {job.get('tech','') or '—'}<br/>"
        f"<b>Payment</b>: {payment_method.title()}"
    )

    meta_tbl = Table(
        [[Paragraph(cust_block, body),
          Paragraph(veh_block, body),
          Paragraph(job_meta, body)]],
        colWidths=[2.7*inch, 2.5*inch, 2.1*inch],
    )
    meta_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), LIGHT),
        ("BOX",     (0,0), (-1,-1), 0.5, GREY),
        ("INNERGRID", (0,0), (-1,-1), 0.25, GREY),
        ("LEFTPADDING", (0,0), (-1,-1), 8),
        ("RIGHTPADDING", (0,0), (-1,-1), 8),
        ("TOPPADDING", (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
    ]))
    story.append(meta_tbl)
    story.append(Spacer(1, 10))

    # ---------- Line items ----------
    # Separate Parts and Labor sections for clarity
    parts = [l for l in lines if l.kind == "part"]
    labor = [l for l in lines if l.kind == "labor"]

    def build_table(rows, section_title):
        data = [[section_title, "Qty", "Unit Price", "Line Total"]]
        for l in rows:
            data.append([
                Paragraph(l.description, body),
                f"{l.quantity:g}",
                _money(l.unit_price),
                _money(l.line_total),
            ])
        t = Table(data, colWidths=[4.4*inch, 0.7*inch, 1.1*inch, 1.1*inch], repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), NAVY),
            ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
            ("FONTNAME",   (0,0), (-1,0), "Helvetica-Bold"),
            ("FONTSIZE",   (0,0), (-1,0), 10),
            ("ALIGN",      (1,0), (-1,-1), "RIGHT"),
            ("ALIGN",      (0,0), (0,-1), "LEFT"),
            ("VALIGN",     (0,0), (-1,-1), "MIDDLE"),
            ("FONTNAME",   (0,1), (-1,-1), "Helvetica"),
            ("FONTSIZE",   (0,1), (-1,-1), 10),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, LIGHT]),
            ("LEFTPADDING", (0,0), (-1,-1), 6),
            ("RIGHTPADDING",(0,0), (-1,-1), 6),
            ("TOPPADDING",  (0,0), (-1,-1), 4),
            ("BOTTOMPADDING",(0,0),(-1,-1), 4),
            ("BOX",         (0,0), (-1,-1), 0.4, GREY),
        ]))
        return t

    if parts:
        story.append(build_table(parts, "Parts & Materials"))
        story.append(Spacer(1, 6))
    if labor:
        story.append(build_table(labor, "Labor"))
        story.append(Spacer(1, 6))

    # ---------- Totals ----------
    rows = [
        ["Parts Subtotal", _money(totals.parts_subtotal)],
        ["Labor Subtotal", _money(totals.labor_subtotal)],
        ["Subtotal",       _money(totals.subtotal)],
        [f"Maine Sales Tax (parts only)", _money(totals.tax)],
    ]
    # Non-cash adjustment is ALWAYS disclosed on every invoice/estimate.
    if totals.non_cash_adjustment > 0:
        rows.append(["Non-cash adjustment (3.5%)", _money(totals.non_cash_adjustment)])
    # Cash or check payment earns the matching 3.5% discount.
    if totals.cash_check_discount > 0:
        rows.append(["Cash / check discount (-3.5%)", f"-{_money(totals.cash_check_discount)}"])
    rows.append([f"TOTAL ({payment_method.upper()})", _money(totals.grand_total)])

    tot_tbl = Table(rows, colWidths=[5.0*inch, 2.3*inch])
    style = [
        ("ALIGN",      (0,0), (0,-1), "RIGHT"),
        ("ALIGN",      (1,0), (1,-1), "RIGHT"),
        ("FONTNAME",   (0,0), (-1,-1), "Helvetica"),
        ("FONTSIZE",   (0,0), (-1,-1), 10),
        ("TOPPADDING", (0,0), (-1,-1), 3),
        ("BOTTOMPADDING",(0,0),(-1,-1), 3),
        ("LINEABOVE",  (0,-1), (-1,-1), 1, NAVY),
        ("FONTNAME",   (0,-1), (-1,-1), "Helvetica-Bold"),
        ("FONTSIZE",   (0,-1), (-1,-1), 12),
        ("TEXTCOLOR",  (0,-1), (-1,-1), NAVY),
    ]
    tot_tbl.setStyle(TableStyle(style))
    story.append(tot_tbl)

    # ---------- PAID stamp ----------
    if doc_kind.upper().endswith("PAID"):
        story.append(Spacer(1, 10))
        story.append(Paragraph("PAID", paid_style))

    # ---------- Notes + footer ----------
    story.append(Spacer(1, 14))
    if job.get("notes"):
        story.append(Paragraph("<b>Notes</b>", label))
        story.append(Paragraph(job["notes"].replace("\n","<br/>"), body))
        story.append(Spacer(1, 6))

    story.append(HRFlowable(width="100%", thickness=0.4, color=GREY, spaceBefore=4, spaceAfter=4))
    foot = footer_note or (
        "All listed prices include a 3.5% non-cash adjustment. "
        "Invoices paid in cash or check receive a 3.5% discount. "
        "Maine Sales Tax (5.5%) applied to parts and materials only. "
        "All repairs carry our standard workmanship warranty."
    )

    # Review QR code — optional but recommended. The QR target is whatever
    # shop['review_url'] is set to; the caption is shop['review_cta'].
    review_url = (shop.get("review_url") or "").strip()
    review_cta = (shop.get("review_cta") or "Scan to leave us a review").strip()
    qr_cell = None
    if review_url:
        qr_cap = ParagraphStyle(
            "qrcap", parent=small, alignment=1, fontName="Helvetica-Bold", textColor=NAVY,
        )
        qr_cell = [
            _QRFlowable(review_url, size_pts=1.05*inch),
            Spacer(1, 2),
            Paragraph(review_cta, qr_cap),
            Paragraph(review_url, ParagraphStyle("qrurl", parent=small, alignment=1)),
        ]

    if qr_cell is not None:
        foot_tbl = Table(
            [[Paragraph(foot, small), qr_cell]],
            colWidths=[5.5*inch, 1.8*inch],
        )
        foot_tbl.setStyle(TableStyle([
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("LEFTPADDING", (0,0), (-1,-1), 0),
            ("RIGHTPADDING", (0,0), (-1,-1), 0),
            ("TOPPADDING", (0,0), (-1,-1), 0),
            ("BOTTOMPADDING", (0,0), (-1,-1), 0),
        ]))
        story.append(foot_tbl)
    else:
        story.append(Paragraph(foot, small))

    if doc_kind.lower().startswith("estimate"):
        story.append(Spacer(1, 6))
        story.append(Paragraph(
            "<b>Authorization:</b> I authorize the work described above at the quoted price. "
            "I acknowledge the shop's storage-fee policy for uncompleted vehicles.",
            small))
        story.append(Spacer(1, 18))
        sig_tbl = Table([[
            Paragraph("_____________________________<br/>Customer signature", small),
            Paragraph("_____________________________<br/>Date", small),
        ]], colWidths=[4.0*inch, 2.5*inch])
        story.append(sig_tbl)

    doc.build(story)
