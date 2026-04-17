"""Reports tab — monthly P&L generator."""
from __future__ import annotations
import datetime as dt
from decimal import Decimal
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox,
    QSpinBox, QDoubleSpinBox, QFormLayout, QGroupBox, QTextEdit,
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
        self._show_preview()

    def _build_ui(self):
        v = QVBoxLayout(self)

        box = QGroupBox("Monthly Profit & Loss")
        form = QFormLayout(box)

        today = dt.date.today()
        row = QHBoxLayout()
        self.cmb_month = QComboBox()
        for i, m in enumerate(MONTHS, 1):
            self.cmb_month.addItem(m, i)
        self.cmb_month.setCurrentIndex(today.month - 1)
        self.spn_year = QSpinBox(); self.spn_year.setRange(2020, 2100)
        self.spn_year.setValue(today.year)
        row.addWidget(self.cmb_month); row.addWidget(self.spn_year); row.addStretch()
        form.addRow("Period", row)

        self.cash = QDoubleSpinBox()
        self.cash.setDecimals(2); self.cash.setMaximum(1_000_000)
        self.cash.setPrefix("$ ")
        form.addRow("Cash sales (external, manually totaled)", self.cash)

        btns = QHBoxLayout()
        b_prev = QPushButton("Preview"); b_prev.clicked.connect(self._show_preview)
        b_gen = QPushButton("Generate PDF"); b_gen.clicked.connect(self.generate_pdf)
        b_gen.setStyleSheet("background:#0B2545; color:white; font-weight:bold; padding:6px;")
        b_print = QPushButton("Generate && Print"); b_print.clicked.connect(self.generate_and_print)
        btns.addWidget(b_prev); btns.addStretch(); btns.addWidget(b_gen); btns.addWidget(b_print)
        form.addRow(btns)
        v.addWidget(box)

        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setStyleSheet(
            "QTextEdit { background:#F2F4F8; border:1px solid #0B2545; padding:8px; }"
        )
        v.addWidget(self.preview, 1)

        hint = QLabel(
            "<i>Reminder: cash-paid invoices are deleted from the app per shop "
            "policy (printed copy kept in the safe). Enter your monthly total of "
            "those cash sales above before generating.</i>"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#4a4a4a;")
        v.addWidget(hint)

    def _params(self):
        year = int(self.spn_year.value())
        month = int(self.cmb_month.currentData())
        cash = Decimal(str(self.cash.value()))
        return year, month, cash

    def _show_preview(self):
        year, month, cash = self._params()
        try:
            pl = reports.compute_month_pl(self.conn, year, month, cash)
        except Exception as e:
            self.preview.setPlainText(f"Preview error: {e}")
            return
        self.preview.setHtml(self._html_preview(year, month, pl))

    def _html_preview(self, year, month, pl):
        def m(v):
            d = Decimal(str(v))
            s = f"${abs(d):,.2f}"
            return f"<span style='color:#C5363A'>({s})</span>" if d < 0 else s
        period = dt.date(year, month, 1).strftime("%B %Y")
        return f"""
        <h2 style="color:#0B2545; margin-bottom:4px;">Profit &amp; Loss — {period}</h2>
        <p style="color:#4a4a4a; margin-top:0;">Preview (PDF will have full formatting)</p>

        <h3 style="color:#0B2545;">Revenue</h3>
        <table cellpadding="3" width="100%">
          <tr><td>Parts &amp; materials revenue</td><td align="right">{m(pl['parts_revenue'])}</td></tr>
          <tr><td>Labor revenue</td><td align="right">{m(pl['labor_revenue'])}</td></tr>
          <tr><td>Cash sales (manual)</td><td align="right">{m(pl['external_cash_sales'])}</td></tr>
          <tr><td><b>Gross revenue</b></td><td align="right"><b>{m(pl['gross_revenue'])}</b></td></tr>
          <tr><td>Less cash / check discounts given</td><td align="right">-{m(pl['cash_discounts_given'])}</td></tr>
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
          <tr><td>Non-cash adjustment collected</td><td align="right">{m(pl['card_surcharge_collected'])}</td></tr>
          <tr><td>Open A/R (unpaid invoices)</td><td align="right">{m(pl['open_ar'])}</td></tr>
          <tr><td>Invoices / paid this month</td><td align="right">{pl['invoice_count']} / {pl['paid_count']}</td></tr>
        </table>
        """

    def _shop_info(self):
        keys = ["shop_name","shop_address1","shop_address2","shop_city",
                "shop_state","shop_zip","shop_phone","shop_email","shop_website"]
        return {k: db.get_setting(self.conn, k, "") for k in keys}

    def generate_pdf(self) -> Path | None:
        year, month, cash = self._params()
        try:
            pl = reports.compute_month_pl(self.conn, year, month, cash)
        except Exception as e:
            warn(self, "P&L", f"Failed to compute: {e}"); return None
        out = printer.output_dir() / f"PL_{year}_{month:02d}.pdf"
        reports.render_pl_pdf(out, self._shop_info(), pl, year, month)
        info(self, "P&L ready", f"Saved to:\n{out}")
        return out

    def generate_and_print(self):
        out = self.generate_pdf()
        if not out: return
        printer_name = db.get_setting(self.conn, "printer_name", "") or None
        ok = printer.print_pdf(out, printer_name=printer_name)
        if not ok:
            warn(self, "Print failed", "PDF was generated but couldn't be sent to the printer.")
