"""Reports tab — daily and monthly P&L generators.

Both reports cover credit-card and check transactions only; that's the
designed scope of this program's reporting.
"""
from __future__ import annotations
import datetime as dt
from decimal import Decimal
from pathlib import Path
from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox,
    QSpinBox, QFormLayout, QGroupBox, QTextEdit, QDateEdit,
)
from .. import db, reports, printer
from .widgets import warn, info


MONTHS = [
    "January","February","March","April","May","June",
    "July","August","September","October","November","December",
]


class ReportsTab(QWidget):
    def __init__(self, conn):
        super().__init__()
        self.conn = conn
        self._build_ui()
        # Default view: today's daily report
        self._show_day_preview()

    # ---------- UI ----------
    def _build_ui(self):
        v = QVBoxLayout(self)

        today = dt.date.today()

        # ---- Daily box ----
        day_box = QGroupBox("Daily Profit & Loss")
        day_form = QFormLayout(day_box)

        self.day_edit = QDateEdit()
        self.day_edit.setCalendarPopup(True)
        self.day_edit.setDisplayFormat("yyyy-MM-dd")
        self.day_edit.setDate(QDate(today.year, today.month, today.day))
        day_form.addRow("Date", self.day_edit)

        day_btns = QHBoxLayout()
        b_prev_d = QPushButton("Preview"); b_prev_d.clicked.connect(self._show_day_preview)
        b_gen_d  = QPushButton("Generate PDF"); b_gen_d.clicked.connect(self.generate_day_pdf)
        b_gen_d.setStyleSheet("background:#0B2545; color:white; font-weight:bold; padding:6px;")
        b_print_d = QPushButton("Generate && Print"); b_print_d.clicked.connect(self.generate_day_and_print)
        day_btns.addWidget(b_prev_d); day_btns.addStretch()
        day_btns.addWidget(b_gen_d); day_btns.addWidget(b_print_d)
        day_form.addRow(day_btns)
        v.addWidget(day_box)

        # ---- Monthly box ----
        mon_box = QGroupBox("Monthly Profit & Loss")
        mon_form = QFormLayout(mon_box)

        row = QHBoxLayout()
        self.cmb_month = QComboBox()
        for i, m in enumerate(MONTHS, 1):
            self.cmb_month.addItem(m, i)
        self.cmb_month.setCurrentIndex(today.month - 1)
        self.spn_year = QSpinBox(); self.spn_year.setRange(2020, 2100)
        self.spn_year.setValue(today.year)
        row.addWidget(self.cmb_month); row.addWidget(self.spn_year); row.addStretch()
        mon_form.addRow("Period", row)

        mon_btns = QHBoxLayout()
        b_prev_m = QPushButton("Preview"); b_prev_m.clicked.connect(self._show_month_preview)
        b_gen_m  = QPushButton("Generate PDF"); b_gen_m.clicked.connect(self.generate_month_pdf)
        b_gen_m.setStyleSheet("background:#0B2545; color:white; font-weight:bold; padding:6px;")
        b_print_m = QPushButton("Generate && Print"); b_print_m.clicked.connect(self.generate_month_and_print)
        mon_btns.addWidget(b_prev_m); mon_btns.addStretch()
        mon_btns.addWidget(b_gen_m); mon_btns.addWidget(b_print_m)
        mon_form.addRow(mon_btns)
        v.addWidget(mon_box)

        # ---- Shared preview pane ----
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setStyleSheet(
            "QTextEdit { background:#F2F4F8; border:1px solid #0B2545; padding:8px; }"
        )
        v.addWidget(self.preview, 1)

        hint = QLabel(
            "<i>Scope: credit-card and check transactions only.</i>"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#4a4a4a;")
        v.addWidget(hint)

    # ---------- Parameter helpers ----------
    def _month_params(self):
        year = int(self.spn_year.value())
        month = int(self.cmb_month.currentData())
        return year, month

    def _day_params(self) -> dt.date:
        qd = self.day_edit.date()
        return dt.date(qd.year(), qd.month(), qd.day())

    # ---------- Preview ----------
    def _show_month_preview(self):
        year, month = self._month_params()
        try:
            pl = reports.compute_month_pl(self.conn, year, month)
        except Exception as e:
            self.preview.setPlainText(f"Preview error: {e}")
            return
        period = dt.date(year, month, 1).strftime("%B %Y")
        self.preview.setHtml(self._html_preview(period, pl, period_noun="month"))

    def _show_day_preview(self):
        day = self._day_params()
        try:
            pl = reports.compute_day_pl(self.conn, day)
        except Exception as e:
            self.preview.setPlainText(f"Preview error: {e}")
            return
        period = day.strftime("%A, %B %-d, %Y")
        self.preview.setHtml(self._html_preview(period, pl, period_noun="day"))

    def _html_preview(self, period_label: str, pl, period_noun: str):
        def m(v):
            d = Decimal(str(v))
            s = f"${abs(d):,.2f}"
            return f"<span style='color:#C5363A'>({s})</span>" if d < 0 else s
        return f"""
        <h2 style="color:#0B2545; margin-bottom:4px;">Profit &amp; Loss — {period_label}</h2>
        <p style="color:#4a4a4a; margin-top:0;">Preview (PDF will have full formatting)</p>

        <h3 style="color:#0B2545;">Revenue</h3>
        <table cellpadding="3" width="100%">
          <tr><td>Parts &amp; materials revenue</td><td align="right">{m(pl['parts_revenue'])}</td></tr>
          <tr><td>Labor revenue</td><td align="right">{m(pl['labor_revenue'])}</td></tr>
          <tr><td><b>Gross revenue</b></td><td align="right"><b>{m(pl['gross_revenue'])}</b></td></tr>
          <tr><td>Less check discounts given</td><td align="right">-{m(pl['check_discounts_given'])}</td></tr>
          <tr><td><b>Net revenue</b></td><td align="right"><b>{m(pl['net_revenue'])}</b></td></tr>
        </table>

        <h3 style="color:#0B2545;">Parts &amp; Materials — Profitability</h3>
        <table cellpadding="3" width="100%" style="background:#F2F4F8;">
          <tr><td>Parts revenue</td><td align="right">{m(pl['parts_revenue'])}</td></tr>
          <tr><td>Parts cost</td><td align="right">{m(pl['parts_cost'])}</td></tr>
          <tr><td><b>Parts profit</b></td><td align="right"><b>{m(pl['parts_profit'])}</b></td></tr>
          <tr><td>Parts margin</td><td align="right">{pl['parts_margin_pct']:.1f}%</td></tr>
        </table>

        <h3 style="color:#0B2545;">Labor — Profitability</h3>
        <table cellpadding="3" width="100%" style="background:#F2F4F8;">
          <tr><td>Labor revenue</td><td align="right">{m(pl['labor_revenue'])}</td></tr>
          <tr><td>Technician wages (timeclock)</td><td align="right">{m(pl['wage_cost'])}</td></tr>
          <tr><td><b>Labor profit</b></td><td align="right"><b>{m(pl['labor_profit'])}</b></td></tr>
          <tr><td>Labor margin</td><td align="right">{pl['labor_margin_pct']:.1f}%</td></tr>
        </table>

        <h3 style="color:#0B2545;">Combined</h3>
        <table cellpadding="3" width="100%">
          <tr><td>Parts profit + labor profit</td><td align="right">{m(pl['parts_profit'] + pl['labor_profit'])}</td></tr>
          <tr><td>Less card processor fees (est.)</td><td align="right">-{m(pl['processor_fee_est'])}</td></tr>
          <tr><td><b>GROSS PROFIT</b></td><td align="right"><b>{m(pl['gross_profit'])}</b></td></tr>
          <tr><td>Blended gross margin</td><td align="right">{pl['gross_margin_pct']:.1f}%</td></tr>
        </table>

        <h3 style="color:#0B2545;">Other</h3>
        <table cellpadding="3" width="100%">
          <tr><td>Sales tax collected (remit to ME)</td><td align="right">{m(pl['tax_collected'])}</td></tr>
          <tr><td>Card processing adjustment collected</td><td align="right">{m(pl['card_surcharge_collected'])}</td></tr>
          <tr><td>Open A/R (unpaid invoices)</td><td align="right">{m(pl['open_ar'])}</td></tr>
          <tr><td>Invoices / paid this {period_noun}</td><td align="right">{pl['invoice_count']} / {pl['paid_count']}</td></tr>
        </table>
        """

    # ---------- Shop info ----------
    def _shop_info(self):
        keys = ["shop_name","shop_address1","shop_address2","shop_city",
                "shop_state","shop_zip","shop_phone","shop_email","shop_website"]
        i = {k: db.get_setting(self.conn, k, "") for k in keys}
        i["logo_path"] = db.resolve_logo_path(self.conn)
        return i

    # ---------- Monthly PDF ----------
    def generate_month_pdf(self) -> Path | None:
        year, month = self._month_params()
        try:
            pl = reports.compute_month_pl(self.conn, year, month)
        except Exception as e:
            warn(self, "P&L", f"Failed to compute: {e}"); return None
        out = printer.output_dir() / f"PL_{year}_{month:02d}.pdf"
        reports.render_pl_pdf(out, self._shop_info(), pl, year, month)
        info(self, "P&L ready", f"Saved to:\n{out}")
        return out

    def generate_month_and_print(self):
        out = self.generate_month_pdf()
        if not out: return
        self._print(out)

    # ---------- Daily PDF ----------
    def generate_day_pdf(self) -> Path | None:
        day = self._day_params()
        try:
            pl = reports.compute_day_pl(self.conn, day)
        except Exception as e:
            warn(self, "P&L", f"Failed to compute: {e}"); return None
        slug = day.strftime("%Y-%m-%d")
        period_label = day.strftime("%A, %B %-d, %Y")
        out = printer.output_dir() / f"PL_{slug}.pdf"
        reports.render_pl_pdf(out, self._shop_info(), pl,
                              period_label=period_label, file_slug=slug)
        info(self, "P&L ready", f"Saved to:\n{out}")
        return out

    def generate_day_and_print(self):
        out = self.generate_day_pdf()
        if not out: return
        self._print(out)

    # ---------- Print helper ----------
    def _print(self, out: Path):
        printer_name = db.get_setting(self.conn, "printer_name", "") or None
        ok = printer.print_pdf(out, printer_name=printer_name)
        if not ok:
            warn(self, "Print failed", "PDF was generated but couldn't be sent to the printer.")
