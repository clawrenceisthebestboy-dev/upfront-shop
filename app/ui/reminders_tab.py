"""Reminders tab — upcoming inspection / oil / custom reminders."""
from __future__ import annotations
import datetime as dt
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox,
    QSpinBox, QDialog, QFormLayout, QLineEdit, QDialogButtonBox, QDateEdit,
    QMessageBox,
)
from PySide6.QtCore import QDate
from .. import repo
from .widgets import make_table, ro, warn, info, confirm


REMINDER_KINDS = ["inspection", "oil", "brakes", "tires", "other"]


class ReminderDialog(QDialog):
    def __init__(self, conn, parent=None, data=None):
        super().__init__(parent)
        self.conn = conn
        self.setWindowTitle("Reminder")
        self.setMinimumWidth(420)
        form = QFormLayout(self)

        self.search = QLineEdit(); self.search.setPlaceholderText("Search customer…")
        self.search.textChanged.connect(self._refresh_customers)
        form.addRow("Customer search", self.search)
        self.cmb_cust = QComboBox(); form.addRow("Customer", self.cmb_cust)
        self.cmb_cust.currentIndexChanged.connect(self._refresh_vehicles)
        self.cmb_veh = QComboBox(); form.addRow("Vehicle (optional)", self.cmb_veh)

        self.cmb_kind = QComboBox()
        self.cmb_kind.addItems(REMINDER_KINDS)
        form.addRow("Kind", self.cmb_kind)

        self.due = QDateEdit()
        self.due.setCalendarPopup(True)
        self.due.setDate(QDate.currentDate().addMonths(1))
        form.addRow("Due date", self.due)

        self.desc = QLineEdit()
        form.addRow("Note", self.desc)

        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        form.addRow(bb)

        self._refresh_customers()

    def _refresh_customers(self):
        self.cmb_cust.blockSignals(True)
        self.cmb_cust.clear()
        self.cmb_cust.addItem("— select —", None)
        for c in repo.list_customers(self.conn, self.search.text().strip()):
            self.cmb_cust.addItem(
                f"{c['last_name']}, {c['first_name']}  ({c['phone'] or ''})", int(c["id"])
            )
        self.cmb_cust.blockSignals(False)
        self._refresh_vehicles()

    def _refresh_vehicles(self):
        self.cmb_veh.clear()
        self.cmb_veh.addItem("— none —", None)
        cid = self.cmb_cust.currentData()
        if not cid: return
        for v in repo.vehicles_for_customer(self.conn, cid):
            label = f"{v['year'] or ''} {v['make'] or ''} {v['model'] or ''} ({v['plate'] or v['vin'] or v['id']})"
            self.cmb_veh.addItem(label.strip(), int(v["id"]))

    def data(self):
        return {
            "customer_id": self.cmb_cust.currentData(),
            "vehicle_id": self.cmb_veh.currentData(),
            "kind": self.cmb_kind.currentText(),
            "due_date": self.due.date().toString("yyyy-MM-dd"),
            "description": self.desc.text().strip(),
        }


class RemindersTab(QWidget):
    def __init__(self, conn):
        super().__init__()
        self.conn = conn
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        v = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Show due within"))
        self.days = QSpinBox(); self.days.setRange(1, 365); self.days.setValue(30); self.days.setSuffix(" days")
        self.days.valueChanged.connect(self.refresh)
        top.addWidget(self.days); top.addStretch()
        b_new = QPushButton("+ New Reminder"); b_new.clicked.connect(self.new_reminder)
        b_done = QPushButton("Mark Done"); b_done.clicked.connect(self.mark_done)
        b_scan = QPushButton("Scan vehicles for inspection exp.")
        b_scan.setToolTip("Create an 'inspection' reminder for every vehicle whose sticker "
                          "expires within the next 60 days and doesn't already have one.")
        b_scan.clicked.connect(self.scan_inspections)
        for b in (b_scan, b_new, b_done): top.addWidget(b)
        v.addLayout(top)

        self.tbl = make_table(["Due","Kind","Customer","Phone","Vehicle","Note"])
        v.addWidget(self.tbl)

    def refresh(self):
        rows = repo.upcoming_reminders(self.conn, within_days=int(self.days.value()))
        self.tbl.setRowCount(0)
        today = dt.date.today()
        for r in rows:
            i = self.tbl.rowCount(); self.tbl.insertRow(i)
            due = r["due_date"] or ""
            veh = " ".join(str(x) for x in [r["year"] or "", r["make"] or "", r["model"] or ""]).strip()
            cells = [
                due,
                (r["kind"] or "").title(),
                f"{r['first_name']} {r['last_name']}",
                r["phone"] or "",
                veh or "—",
                r["description"] or "",
            ]
            for c, v in enumerate(cells):
                it = ro(v)
                if c == 0:
                    it.setData(Qt.UserRole, int(r["id"]))
                    # red flag for overdue
                    try:
                        d = dt.date.fromisoformat(due)
                        if d < today:
                            from PySide6.QtGui import QBrush, QColor
                            it.setForeground(QBrush(QColor("#C5363A")))
                    except Exception:
                        pass
                self.tbl.setItem(i, c, it)

    def _selected_id(self):
        row = self.tbl.currentRow()
        if row < 0: return None
        return int(self.tbl.item(row, 0).data(Qt.UserRole))

    def new_reminder(self):
        d = ReminderDialog(self.conn, self)
        if d.exec() == QDialog.Accepted:
            data = d.data()
            if not data.get("customer_id"):
                warn(self, "Missing", "Pick a customer."); return
            repo.add_reminder(
                self.conn, data["customer_id"], data["vehicle_id"],
                data["kind"], data["due_date"], data["description"],
            )
            self.refresh()

    def mark_done(self):
        rid = self._selected_id()
        if rid is None: return
        if not confirm(self, "Mark done", "Mark this reminder as completed?"): return
        self.conn.execute("UPDATE reminders SET done=1 WHERE id=?", (rid,))
        self.conn.commit()
        self.refresh()

    def scan_inspections(self):
        """Create 'inspection' reminders for vehicles whose sticker expires
        within 60 days and that don't already have an open reminder."""
        today = dt.date.today()
        cutoff = (today + dt.timedelta(days=60)).strftime("%Y-%m")
        rows = self.conn.execute(
            "SELECT v.id AS vid, v.customer_id, v.year, v.make, v.model, v.inspection_exp "
            "FROM vehicles v WHERE v.inspection_exp IS NOT NULL AND v.inspection_exp <= ?",
            (cutoff,),
        ).fetchall()
        added = 0
        for r in rows:
            existing = self.conn.execute(
                "SELECT 1 FROM reminders WHERE vehicle_id=? AND kind='inspection' AND done=0",
                (r["vid"],),
            ).fetchone()
            if existing:
                continue
            exp = r["inspection_exp"]
            # Turn YYYY-MM into a due date of the 1st of that month
            try:
                y, m = (int(x) for x in exp.split("-")[:2])
                due = dt.date(y, m, 1).isoformat()
            except Exception:
                continue
            desc = f"Inspection sticker expires {exp} " \
                   f"({r['year'] or ''} {r['make'] or ''} {r['model'] or ''})".strip()
            repo.add_reminder(self.conn, r["customer_id"], r["vid"],
                              "inspection", due, desc)
            added += 1
        info(self, "Scan complete", f"{added} new inspection reminder(s) created.")
        self.refresh()
