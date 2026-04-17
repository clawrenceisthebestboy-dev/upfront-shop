"""Job/estimate/invoice editor window — line items + totals + actions."""
from __future__ import annotations
import datetime as dt
from decimal import Decimal
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QComboBox,
    QPushButton, QLineEdit, QTableWidget, QTableWidgetItem, QMessageBox,
    QDoubleSpinBox, QCheckBox, QSpinBox, QHeaderView, QAbstractItemView,
    QSizePolicy, QGroupBox, QFileDialog, QPlainTextEdit, QWidget,
)

from .. import db, repo
from ..pricing import LineItem, compute_totals
from ..markup import marked_up_price
from ..invoice_pdf import render_invoice_pdf
from ..work_order_pdf import render_work_order_pdf
from ..printer import print_pdf, output_dir
from .widgets import confirm, warn, info


PAYMENT_METHODS = ["unpaid", "card", "cash", "check"]
D = Decimal


class JobEditor(QDialog):
    def __init__(self, conn, job_id: int, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.job_id = job_id
        self.setWindowTitle("Job")
        self.resize(1100, 720)
        self._settings = {r["key"]: r["value"] for r in conn.execute("SELECT * FROM settings")}
        self._markup_tiers = db.load_markup_tiers(conn)
        self._build_ui()
        self._load()

    # -------------- UI --------------

    def _build_ui(self):
        v = QVBoxLayout(self)

        # Header
        hdr = QHBoxLayout()
        self.lbl_number = QLabel()
        self.lbl_number.setFont(QFont("Arial", 18, QFont.Bold))
        hdr.addWidget(self.lbl_number); hdr.addStretch()
        self.cmb_status = QComboBox(); self.cmb_status.addItems(["estimate","invoice","paid"])
        self.cmb_pay = QComboBox(); self.cmb_pay.addItems(PAYMENT_METHODS)
        hdr.addWidget(QLabel("Status:")); hdr.addWidget(self.cmb_status)
        hdr.addWidget(QLabel("Payment:")); hdr.addWidget(self.cmb_pay)
        v.addLayout(hdr)

        # Meta
        meta = QFormLayout()
        self.lbl_customer = QLabel("—")
        self.cmb_vehicle = QComboBox()
        self.tech_edit = QLineEdit()
        self.odo_in = QSpinBox(); self.odo_in.setMaximum(2_000_000)
        self.odo_out = QSpinBox(); self.odo_out.setMaximum(2_000_000)
        meta.addRow("Customer", self.lbl_customer)
        meta.addRow("Vehicle", self.cmb_vehicle)
        meta.addRow("Tech", self.tech_edit)
        row = QHBoxLayout()
        row.addWidget(QLabel("Odometer in")); row.addWidget(self.odo_in)
        row.addSpacing(20)
        row.addWidget(QLabel("out")); row.addWidget(self.odo_out); row.addStretch()
        w = QWidget(); w.setLayout(row)
        meta.addRow("Odometer", w)
        v.addLayout(meta)

        # Line items
        box = QGroupBox("Line items (parts & labor)")
        bv = QVBoxLayout(box)
        self.tbl = QTableWidget(0, 8)
        self.tbl.setHorizontalHeaderLabels([
            "Type", "Description", "Qty", "Cost (internal)", "Unit Price", "Taxable",
            "Line Total", "",
        ])
        self.tbl.horizontalHeader().setStretchLastSection(False)
        self.tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        for col in (0,2,3,4,5,6,7):
            self.tbl.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl.cellChanged.connect(self._on_cell_changed)
        bv.addWidget(self.tbl)

        btns = QHBoxLayout()
        b_part = QPushButton("+ Add Part")
        b_part.clicked.connect(lambda: self._add_row("part"))
        b_part_inv = QPushButton("+ From Inventory")
        b_part_inv.clicked.connect(self._add_from_inventory)
        b_lab = QPushButton("+ Add Labor")
        b_lab.clicked.connect(lambda: self._add_row("labor"))
        b_del = QPushButton("Remove Row")
        b_del.clicked.connect(self._remove_row)
        b_remark = QPushButton("Re-apply Markup to Parts")
        b_remark.setToolTip(
            "Recalculate customer-facing prices on every part line using the\n"
            "current tiered markup table. Overrides any manual edits."
        )
        b_remark.clicked.connect(self._reapply_markup)
        b_reset_labor = QPushButton("Reset Labor to Default Rate")
        b_reset_labor.setToolTip(
            "Set every labor line to the shop's current default labor rate\n"
            "from Settings. You can still edit individual labor lines."
        )
        b_reset_labor.clicked.connect(self._reset_labor_rate)
        for b in (b_part, b_part_inv, b_lab, b_del, b_remark, b_reset_labor): btns.addWidget(b)
        btns.addStretch()
        bv.addLayout(btns)
        v.addWidget(box, 1)

        # Notes
        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setPlaceholderText("Notes (customer-facing — shown on printed invoice)")
        self.notes_edit.setFixedHeight(60)
        v.addWidget(self.notes_edit)

        # Totals
        tot_box = QGroupBox("Totals")
        tg = QFormLayout(tot_box)
        self.lbl_parts_sub = QLabel("$0.00")
        self.lbl_labor_sub = QLabel("$0.00")
        self.lbl_sub = QLabel("$0.00")
        self.lbl_tax = QLabel("$0.00")
        self.lbl_surcharge = QLabel("$0.00")
        self.lbl_discount = QLabel("$0.00")
        self.lbl_grand = QLabel("$0.00"); self.lbl_grand.setFont(QFont("Arial", 14, QFont.Bold))
        self.lbl_profit = QLabel("$0.00 parts profit (internal)")
        self.lbl_profit.setStyleSheet("color:#4a4a4a; font-style:italic;")
        tg.addRow("Parts subtotal", self.lbl_parts_sub)
        tg.addRow("Labor subtotal", self.lbl_labor_sub)
        tg.addRow("Subtotal", self.lbl_sub)
        tg.addRow("Maine Sales Tax", self.lbl_tax)
        tg.addRow("Non-cash adjustment (+3.5%)", self.lbl_surcharge)
        tg.addRow("Cash / check discount (-3.5%)", self.lbl_discount)
        tg.addRow("GRAND TOTAL", self.lbl_grand)
        tg.addRow("", self.lbl_profit)
        v.addWidget(tot_box)

        # Actions
        ab = QHBoxLayout()
        self.btn_save = QPushButton("Save")
        self.btn_save.clicked.connect(self._save)
        self.btn_print_est = QPushButton("Print Estimate")
        self.btn_print_est.clicked.connect(lambda: self._print("Estimate"))
        self.btn_print_wo = QPushButton("Print Work Order")
        self.btn_print_wo.setToolTip(
            "Print a tech-facing work order for this job.\n"
            "No pricing, no labor times — just what needs to be done."
        )
        self.btn_print_wo.clicked.connect(self._print_work_order)
        self.btn_convert = QPushButton("Convert to Invoice")
        self.btn_convert.clicked.connect(self._convert_to_invoice)
        self.btn_print_inv = QPushButton("Print Invoice")
        self.btn_print_inv.clicked.connect(lambda: self._print("Invoice"))
        self.btn_close_cash = QPushButton("Mark PAID (Cash) → Print & Delete")
        self.btn_close_cash.setStyleSheet("background:#C5363A; color:white; font-weight:bold;")
        self.btn_close_cash.clicked.connect(self._close_cash)
        self.btn_close_card = QPushButton("Mark PAID (Card/Check)")
        self.btn_close_card.clicked.connect(self._close_card)
        for b in (self.btn_save, self.btn_print_est, self.btn_print_wo, self.btn_convert,
                  self.btn_print_inv, self.btn_close_card, self.btn_close_cash):
            ab.addWidget(b)
        ab.addStretch()
        v.addLayout(ab)

        self.cmb_pay.currentIndexChanged.connect(self._recalc)

    # -------------- Data --------------

    def _load(self):
        # Re-read settings and markup tiers so any Settings-tab changes
        # take effect on the next estimate/invoice without restarting.
        self._settings = {r["key"]: r["value"] for r in self.conn.execute("SELECT * FROM settings")}
        self._markup_tiers = db.load_markup_tiers(self.conn)
        j = repo.get_job(self.conn, self.job_id)
        c = repo.get_customer(self.conn, j["customer_id"])
        self.lbl_number.setText(f"{j['status'].title()} {j['number']}")
        self.lbl_customer.setText(f"{c['first_name']} {c['last_name']}  |  {c['phone'] or ''}")
        self.cmb_status.setCurrentText(j["status"] if j["status"] in ("estimate","invoice","paid") else "estimate")
        self.cmb_pay.setCurrentText(j["payment_method"] or "unpaid")
        self.tech_edit.setText(j["tech"] or "")
        self.odo_in.setValue(j["odometer_in"] or 0)
        self.odo_out.setValue(j["odometer_out"] or 0)
        self.notes_edit.setPlainText(j["notes"] or "")
        # populate vehicle dropdown
        self.cmb_vehicle.clear()
        self.cmb_vehicle.addItem("— none —", None)
        for v in repo.vehicles_for_customer(self.conn, j["customer_id"]):
            label = f"{v['year'] or ''} {v['make'] or ''} {v['model'] or ''} ({v['plate'] or v['vin'] or v['id']})"
            self.cmb_vehicle.addItem(label.strip(), int(v["id"]))
        if j["vehicle_id"]:
            idx = self.cmb_vehicle.findData(j["vehicle_id"])
            if idx >= 0: self.cmb_vehicle.setCurrentIndex(idx)
        # lines
        self.tbl.blockSignals(True)
        self.tbl.setRowCount(0)
        for l in repo.load_lines(self.conn, self.job_id):
            self._append_row(l)
        self.tbl.blockSignals(False)
        self._recalc()

    def _append_row(self, l: LineItem):
        r = self.tbl.rowCount()
        self.tbl.insertRow(r)

        cmb = QComboBox(); cmb.addItems(["part","labor"])
        cmb.setCurrentText(l.kind)
        cmb.currentTextChanged.connect(self._recalc)
        self.tbl.setCellWidget(r, 0, cmb)

        desc = QTableWidgetItem(l.description)
        desc.setFlags(desc.flags() | Qt.ItemIsEditable)
        self.tbl.setItem(r, 1, desc)

        qty = QDoubleSpinBox(); qty.setDecimals(2); qty.setMaximum(999); qty.setMinimum(0.01); qty.setValue(float(l.quantity))
        qty.valueChanged.connect(self._recalc)
        self.tbl.setCellWidget(r, 2, qty)

        cost = QDoubleSpinBox(); cost.setDecimals(2); cost.setMaximum(1_000_000); cost.setPrefix("$ "); cost.setValue(float(l.unit_cost))
        cost.valueChanged.connect(lambda v, row=r: self._cost_changed(row, v))
        self.tbl.setCellWidget(r, 3, cost)

        price = QDoubleSpinBox(); price.setDecimals(2); price.setMaximum(1_000_000); price.setPrefix("$ "); price.setValue(float(l.unit_price))
        price.valueChanged.connect(self._recalc)
        self.tbl.setCellWidget(r, 4, price)

        tax = QCheckBox(); tax.setChecked(l.taxable); tax.stateChanged.connect(self._recalc)
        self.tbl.setCellWidget(r, 5, tax)

        line_tot = QTableWidgetItem("$0.00")
        line_tot.setFlags(line_tot.flags() & ~Qt.ItemIsEditable)
        line_tot.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.tbl.setItem(r, 6, line_tot)

        # hidden part_id in col 7
        pid = QTableWidgetItem(str(l.part_id) if l.part_id else "")
        pid.setFlags(pid.flags() & ~Qt.ItemIsEditable)
        self.tbl.setItem(r, 7, pid)

    def _cost_changed(self, row: int, new_cost: float):
        """When internal cost is edited, auto-suggest the customer-facing price
        via the tiered markup table. Shop can still override it."""
        kind = self.tbl.cellWidget(row, 0).currentText()
        if kind == "part" and new_cost > 0:
            price = float(marked_up_price(D(str(new_cost)), self._markup_tiers))
            self.tbl.cellWidget(row, 4).setValue(price)
        self._recalc()

    def _on_cell_changed(self, row, col):
        # description edits don't require recalc but harmless
        self._recalc()

    def _add_row(self, kind: str):
        default_price = 0.0
        if kind == "labor":
            default_price = float(self._settings.get("default_labor_rate","125.00"))
            l = LineItem(kind="labor", description="Labor",
                         quantity=D("1"), unit_cost=D("0"),
                         unit_price=D(str(default_price)), taxable=False)
        else:
            l = LineItem(kind="part", description="", quantity=D("1"),
                         unit_cost=D("0"), unit_price=D("0"), taxable=True)
        self._append_row(l)
        self._recalc()

    def _add_from_inventory(self):
        rows = repo.list_inventory(self.conn, "")
        if not rows:
            warn(self, "Empty", "No inventory yet — add parts on the Inventory tab."); return
        dlg = QDialog(self); dlg.setWindowTitle("Pick part"); dlg.resize(600, 400)
        lv = QVBoxLayout(dlg)
        t = QTableWidget(0, 4); t.setHorizontalHeaderLabels(["SKU","Description","Vendor","On hand"])
        t.verticalHeader().setVisible(False)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        lv.addWidget(t)
        for r in rows:
            i = t.rowCount(); t.insertRow(i)
            cells = [r["sku"] or "", r["description"], r["vendor_name"] or "", str(r["on_hand"])]
            for c, v in enumerate(cells):
                it = QTableWidgetItem(v)
                if c == 0: it.setData(Qt.UserRole, int(r["id"]))
                t.setItem(i, c, it)
        bb = QHBoxLayout()
        ok = QPushButton("Add"); cancel = QPushButton("Cancel")
        bb.addStretch(); bb.addWidget(cancel); bb.addWidget(ok)
        lv.addLayout(bb)
        def _ok():
            row = t.currentRow()
            if row < 0: return
            pid = int(t.item(row, 0).data(Qt.UserRole))
            part = self.conn.execute("SELECT * FROM inventory WHERE id=?", (pid,)).fetchone()
            cost = D(str(part["unit_cost"]))
            price = marked_up_price(cost, self._markup_tiers)
            l = LineItem(kind="part", description=part["description"],
                         quantity=D("1"), unit_cost=cost, unit_price=price,
                         taxable=True, part_id=pid)
            self._append_row(l)
            dlg.accept()
        ok.clicked.connect(_ok); cancel.clicked.connect(dlg.reject)
        dlg.exec()
        self._recalc()

    def _remove_row(self):
        row = self.tbl.currentRow()
        if row < 0: return
        self.tbl.removeRow(row)
        self._recalc()

    def _reapply_markup(self):
        """Pull the latest markup tiers from the DB (in case Settings changed),
        then force every part line's Unit Price to the marked-up value."""
        self._markup_tiers = db.load_markup_tiers(self.conn)
        changed = 0
        for r in range(self.tbl.rowCount()):
            if self.tbl.cellWidget(r, 0).currentText() != "part":
                continue
            cost_w = self.tbl.cellWidget(r, 3)
            price_w = self.tbl.cellWidget(r, 4)
            cost = D(str(cost_w.value()))
            if cost <= 0: continue
            new_price = float(marked_up_price(cost, self._markup_tiers))
            price_w.setValue(new_price)
            changed += 1
        self._recalc()
        info(self, "Markup applied",
             f"Re-applied tiered markup to {changed} part line(s).")

    def _reset_labor_rate(self):
        """Set every labor line's Unit Price to the current default labor rate
        from Settings. The shop can still override per line afterward."""
        rate = float(db.get_setting(self.conn, "default_labor_rate", "125.00"))
        self._settings["default_labor_rate"] = str(rate)
        changed = 0
        for r in range(self.tbl.rowCount()):
            if self.tbl.cellWidget(r, 0).currentText() != "labor":
                continue
            self.tbl.cellWidget(r, 4).setValue(rate)
            changed += 1
        self._recalc()
        info(self, "Labor rate reset",
             f"Set {changed} labor line(s) to ${rate:,.2f}/hr (default labor rate).")

    def _collect_lines(self) -> list[LineItem]:
        lines = []
        for r in range(self.tbl.rowCount()):
            kind = self.tbl.cellWidget(r, 0).currentText()
            desc_item = self.tbl.item(r, 1)
            desc = desc_item.text() if desc_item else ""
            qty = D(str(self.tbl.cellWidget(r, 2).value()))
            cost = D(str(self.tbl.cellWidget(r, 3).value()))
            price = D(str(self.tbl.cellWidget(r, 4).value()))
            taxable = self.tbl.cellWidget(r, 5).isChecked()
            pid_item = self.tbl.item(r, 7)
            pid = int(pid_item.text()) if pid_item and pid_item.text() else None
            lines.append(LineItem(kind=kind, description=desc, quantity=qty,
                                  unit_cost=cost, unit_price=price, taxable=taxable,
                                  part_id=pid))
        return lines

    def _recalc(self):
        lines = self._collect_lines()
        j = repo.get_job(self.conn, self.job_id)
        method = self.cmb_pay.currentText()
        tax_rate = D(str(j["tax_rate"]))
        t = compute_totals(lines, payment_method=method, tax_rate=tax_rate)
        for r, l in enumerate(lines):
            item = self.tbl.item(r, 6)
            if item: item.setText(f"${l.line_total:,.2f}")
        self.lbl_parts_sub.setText(f"${t.parts_subtotal:,.2f}")
        self.lbl_labor_sub.setText(f"${t.labor_subtotal:,.2f}")
        self.lbl_sub.setText(f"${t.subtotal:,.2f}")
        self.lbl_tax.setText(f"${t.tax:,.2f}")
        self.lbl_surcharge.setText(f"${t.non_cash_adjustment:,.2f}")
        self.lbl_discount.setText(f"${t.cash_check_discount:,.2f}")
        self.lbl_grand.setText(f"${t.grand_total:,.2f}")
        self.lbl_profit.setText(
            f"Internal: parts cost ${t.parts_cost:,.2f} | parts profit ${t.parts_profit:,.2f} | labor ${t.labor_revenue:,.2f}"
        )

    # -------------- Actions --------------

    def _save(self) -> bool:
        lines = self._collect_lines()
        # validate
        for l in lines:
            if not l.description.strip():
                warn(self, "Empty", "Every line needs a description."); return False
        repo.save_lines(self.conn, self.job_id, lines)
        vid = self.cmb_vehicle.currentData()
        repo.update_job(self.conn, self.job_id,
            status=self.cmb_status.currentText(),
            payment_method=self.cmb_pay.currentText(),
            tech=self.tech_edit.text().strip(),
            vehicle_id=vid,
            odometer_in=self.odo_in.value() or None,
            odometer_out=self.odo_out.value() or None,
            notes=self.notes_edit.toPlainText().strip(),
        )
        return True

    def _snapshot(self, doc_kind: str):
        """Write a PDF and return its path."""
        if not self._save(): return None
        j = dict(repo.get_job(self.conn, self.job_id))
        c = dict(repo.get_customer(self.conn, j["customer_id"]))
        v_row = self.conn.execute("SELECT * FROM vehicles WHERE id=?", (j["vehicle_id"],)).fetchone() if j["vehicle_id"] else None
        v = dict(v_row) if v_row else None
        lines = repo.load_lines(self.conn, self.job_id)
        method = j["payment_method"] or "unpaid"
        t = compute_totals(lines, payment_method=method, tax_rate=D(str(j["tax_rate"])))
        out = output_dir() / f"{doc_kind.replace(' ','_').lower()}_{j['number']}_{dt.date.today().isoformat()}.pdf"
        render_invoice_pdf(
            str(out),
            shop={k: self._settings.get(k,"") for k in self._settings},
            customer=c, vehicle=v, job=j, lines=lines, totals=t,
            doc_kind=doc_kind, payment_method=method,
            footer_note=self._settings.get("invoice_footer",""),
        )
        return out

    def _print(self, kind: str):
        out = self._snapshot(kind)
        if not out: return
        printer = self._settings.get("printer_name") or None
        ok = print_pdf(out, printer)
        if ok:
            info(self, "Printing", f"Sent to printer: {printer or '(system default)'}\n\nFile: {out}")
        else:
            warn(self, "Printing", f"Could not print automatically.\nOpen and print manually: {out}")

    def _print_work_order(self):
        """Render + print a tech-facing work order for this job.

        Work orders intentionally carry no pricing and no labor times.
        They're print-only (the PDF is written to the same output dir
        the customer invoices land in, but nothing is persisted to the
        database — consistent with the Work Orders tab behavior)."""
        if not self._save():
            return
        job = dict(repo.get_job(self.conn, self.job_id))
        customer = dict(repo.get_customer(self.conn, job["customer_id"]))
        vehicle = None
        if job["vehicle_id"]:
            row = self.conn.execute(
                "SELECT * FROM vehicles WHERE id=?", (job["vehicle_id"],),
            ).fetchone()
            vehicle = dict(row) if row else None
        lines = repo.load_lines(self.conn, self.job_id)
        out = output_dir() / (
            f"work_order_{job['number']}_{dt.date.today().isoformat()}.pdf"
        )
        try:
            render_work_order_pdf(
                str(out),
                shop={k: self._settings.get(k, "") for k in self._settings},
                customer=customer, vehicle=vehicle,
                job=job, lines=lines,
            )
        except Exception as e:
            warn(self, "Work order", f"Couldn't render work order: {e}")
            return
        printer = self._settings.get("printer_name") or None
        ok = print_pdf(out, printer)
        if ok:
            info(self, "Work order printing",
                 f"Sent to printer: {printer or '(system default)'}\n\nFile: {out}")
        else:
            warn(self, "Work order",
                 f"Could not print automatically.\nOpen and print manually: {out}")

    def _convert_to_invoice(self):
        if not self._save(): return
        j = repo.get_job(self.conn, self.job_id)
        if j["number"].startswith("E-"):
            new_num = db.next_job_number(self.conn, "I")
            repo.update_job(self.conn, self.job_id,
                status="invoice",
                number=new_num,
                invoiced_at=dt.datetime.now().isoformat(sep=" ", timespec="seconds"),
            )
            self._load()
            info(self, "Converted", f"Estimate converted. Invoice #: {new_num}")

    def _close_card(self):
        """Mark invoice paid (card or check) — keep in DB."""
        if not self._save(): return
        method = self.cmb_pay.currentText()
        if method not in ("card","check"):
            if not confirm(self, "Payment method?",
                           "Payment is not set to card or check. Use 'Mark PAID' anyway?"):
                return
        j = repo.get_job(self.conn, self.job_id)
        lines = repo.load_lines(self.conn, self.job_id)
        t = compute_totals(lines, payment_method=method, tax_rate=D(str(j["tax_rate"])))
        repo.update_job(self.conn, self.job_id,
            status="paid",
            paid_at=dt.datetime.now().isoformat(sep=" ", timespec="seconds"),
            paid_total=float(t.grand_total),
        )
        # Decrement inventory for any linked parts
        for l in lines:
            if l.part_id:
                repo.decrement_inventory(self.conn, l.part_id, float(l.quantity))
        out = self._snapshot("Invoice — PAID")
        info(self, "Paid", f"Invoice marked paid. PDF: {out}")
        self._load()

    def _close_cash(self):
        """CASH close: print PAID invoice, decrement inventory, then HARD DELETE job."""
        if not self._save(): return
        if not confirm(self, "Cash close",
            "This will print the invoice marked PAID and then permanently delete this job "
            "from the database. Your printed copy is the only record afterward.\n\nContinue?"):
            return
        # Force payment method to cash for the print-out
        self.cmb_pay.setCurrentText("cash"); self._save()
        lines = repo.load_lines(self.conn, self.job_id)
        # decrement inventory
        for l in lines:
            if l.part_id:
                repo.decrement_inventory(self.conn, l.part_id, float(l.quantity))
        out = self._snapshot("Invoice — PAID")
        # print
        printer = self._settings.get("printer_name") or None
        printed = print_pdf(out, printer)
        # hard delete
        repo.delete_job(self.conn, self.job_id)
        msg = f"Invoice printed and PDF saved to {out}\n\nJob deleted from database."
        if not printed:
            msg += "\n\n(Automatic print failed — please print the PDF manually.)"
        info(self, "Cash close", msg)
        self.accept()
