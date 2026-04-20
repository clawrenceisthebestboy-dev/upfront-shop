"""Jobs tab: active estimates & invoices; create new, open editor."""
from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QComboBox, QLabel,
    QLineEdit, QDialog, QFormLayout, QDialogButtonBox, QMessageBox,
    QCheckBox, QPlainTextEdit,
)
from .. import repo, db
from .widgets import make_table, ro, confirm, warn, info
from .job_editor import JobEditor


class DeleteJobDialog(QDialog):
    """Confirm-and-reason dialog for manual invoice/estimate deletion.

    Used for returns, refunds, and corrections. If the job is paid,
    the restock checkbox defaults to on so shelf counts come back.
    """
    def __init__(self, job_row, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Delete {job_row['number']}")
        self.setMinimumWidth(440)
        form = QFormLayout(self)

        status = job_row["status"] or ""
        was_paid = status in ("paid", "archived")

        lead = QLabel(
            f"<b>{job_row['number']}</b> — current status: <b>{status}</b>. "
            "This will permanently remove the record. If the job was paid, "
            "use this for returns and refunds."
        )
        lead.setWordWrap(True)
        form.addRow(lead)

        self.cmb_reason = QComboBox()
        self.cmb_reason.addItems([
            "Refund / return",
            "Invoice issued in error",
            "Duplicate invoice",
            "Customer dispute — voided",
            "Other",
        ])
        form.addRow("Reason", self.cmb_reason)

        self.txt_note = QPlainTextEdit()
        self.txt_note.setPlaceholderText("Optional note (part returned, check voided, etc.)")
        self.txt_note.setFixedHeight(70)
        form.addRow("Note", self.txt_note)

        self.chk_restock = QCheckBox("Put parts back into inventory on-hand")
        self.chk_restock.setChecked(was_paid)
        self.chk_restock.setEnabled(True)
        form.addRow(self.chk_restock)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Delete permanently")
        bb.button(QDialogButtonBox.Ok).setStyleSheet(
            "background:#C5363A; color:white; font-weight:bold; padding:6px;"
        )
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        form.addRow(bb)

    def reason_text(self) -> str:
        base = self.cmb_reason.currentText()
        note = self.txt_note.toPlainText().strip()
        return f"{base} — {note}" if note else base

    def restock(self) -> bool:
        return self.chk_restock.isChecked()


class NewJobDialog(QDialog):
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.setWindowTitle("New Estimate")
        self.setMinimumWidth(420)
        form = QFormLayout(self)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Type to search customer…")
        self.search.textChanged.connect(self._refresh_customers)
        form.addRow("Customer search", self.search)

        self.cmb_customer = QComboBox()
        form.addRow("Customer", self.cmb_customer)
        self.cmb_customer.currentIndexChanged.connect(self._refresh_vehicles)

        self.cmb_vehicle = QComboBox()
        form.addRow("Vehicle", self.cmb_vehicle)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        form.addRow(bb)

        self._refresh_customers()

    def _refresh_customers(self):
        self.cmb_customer.blockSignals(True)
        self.cmb_customer.clear()
        self.cmb_customer.addItem("— select —", None)
        for c in repo.list_customers(self.conn, self.search.text().strip()):
            self.cmb_customer.addItem(f"{c['last_name']}, {c['first_name']}  ({c['phone'] or ''})", int(c["id"]))
        self.cmb_customer.blockSignals(False)
        self._refresh_vehicles()

    def _refresh_vehicles(self):
        self.cmb_vehicle.clear()
        self.cmb_vehicle.addItem("— none —", None)
        cid = self.cmb_customer.currentData()
        if not cid: return
        for v in repo.vehicles_for_customer(self.conn, cid):
            label = f"{v['year'] or ''} {v['make'] or ''} {v['model'] or ''} ({v['plate'] or v['vin'] or v['id']})"
            self.cmb_vehicle.addItem(label.strip(), int(v["id"]))

    def result_data(self):
        return self.cmb_customer.currentData(), self.cmb_vehicle.currentData()


class JobsTab(QWidget):
    def __init__(self, conn):
        super().__init__()
        self.conn = conn
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        v = QVBoxLayout(self)
        top = QHBoxLayout()
        self.filter = QComboBox()
        self.filter.addItems(["Active (estimate + invoice)","Estimates","Invoices","Paid","All"])
        self.filter.currentIndexChanged.connect(self.refresh)
        top.addWidget(QLabel("Show:")); top.addWidget(self.filter); top.addStretch()
        b_new = QPushButton("+ New Estimate"); b_new.clicked.connect(self.new_job)
        b_open = QPushButton("Open"); b_open.clicked.connect(self.open_job)
        b_del = QPushButton("Delete"); b_del.clicked.connect(self.delete_job)
        for b in (b_new, b_open, b_del): top.addWidget(b)
        v.addLayout(top)

        self.tbl = make_table(["Number","Status","Customer","Vehicle","Payment","Opened","Paid","Total"])
        self.tbl.cellDoubleClicked.connect(lambda r,c: self.open_job())
        v.addWidget(self.tbl)

    def _status_filter(self):
        idx = self.filter.currentIndex()
        return [
            ("estimate","invoice"),
            ("estimate",),
            ("invoice",),
            ("paid",),
            ("estimate","invoice","paid","archived"),
        ][idx]

    def refresh(self):
        statuses = self._status_filter()
        rows = repo.list_jobs(self.conn, statuses)
        self.tbl.setRowCount(0)
        for r in rows:
            i = self.tbl.rowCount()
            self.tbl.insertRow(i)
            veh = " ".join(str(x) for x in [r["year"] or "", r["make"] or "", r["model"] or ""]).strip()
            cells = [
                r["number"], r["status"],
                f"{r['first_name']} {r['last_name']}",
                veh or "—",
                r["payment_method"] or "—",
                (r["opened_at"] or "")[:16],
                (r["paid_at"] or "")[:16] if r["paid_at"] else "—",
                f"${r['paid_total']:,.2f}" if r["paid_total"] else "—",
            ]
            for c, vv in enumerate(cells):
                it = ro(vv)
                if c == 0: it.setData(Qt.UserRole, int(r["id"]))
                self.tbl.setItem(i, c, it)

    def _selected_id(self):
        row = self.tbl.currentRow()
        if row < 0: return None
        return int(self.tbl.item(row, 0).data(Qt.UserRole))

    def new_job(self):
        d = NewJobDialog(self.conn, self)
        if d.exec() == QDialog.Accepted:
            cid, vid = d.result_data()
            if not cid:
                warn(self, "Missing", "Pick a customer."); return
            tax_rate = float(db.get_setting(self.conn, "tax_rate", "0.055"))
            jid = repo.create_job(self.conn, cid, vid, tax_rate)
            JobEditor(self.conn, jid, self).exec()
            self.refresh()

    def open_job(self):
        jid = self._selected_id()
        if jid is None: return
        JobEditor(self.conn, jid, self).exec()
        self.refresh()

    def delete_job(self):
        jid = self._selected_id()
        if jid is None:
            warn(self, "Nothing selected", "Select a job first."); return
        j = repo.get_job(self.conn, jid)
        if j is None:
            warn(self, "Not found", "That job no longer exists."); self.refresh(); return

        d = DeleteJobDialog(j, self)
        if d.exec() != QDialog.Accepted:
            return
        try:
            report = repo.delete_job_with_reason(
                self.conn, jid,
                reason=d.reason_text(),
                restock=d.restock(),
            )
        except Exception as e:
            warn(self, "Delete failed", str(e)); return

        restocked = report["restocked"]
        msg = f"{report['number']} deleted."
        if restocked:
            total_qty = sum(q for _, q in restocked)
            msg += f"\n{total_qty} part unit(s) returned to inventory across {len(restocked)} SKU(s)."
        else:
            msg += "\nNo inventory changes."
        info(self, "Deleted", msg)
        self.refresh()
