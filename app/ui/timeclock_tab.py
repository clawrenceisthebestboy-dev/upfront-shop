"""Time Clock tab — tech clock in/out, view history."""
from __future__ import annotations
import datetime as dt
from decimal import Decimal
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit,
    QDoubleSpinBox, QComboBox, QGroupBox, QFormLayout,
)
from .. import repo, db
from .widgets import make_table, ro, warn, info


class TimeClockTab(QWidget):
    def __init__(self, conn):
        super().__init__()
        self.conn = conn
        self._build_ui()
        self.refresh()
        # update the "elapsed" column once a minute while open
        self._timer = QTimer(self)
        self._timer.setInterval(60_000)
        self._timer.timeout.connect(self._update_open_entries)
        self._timer.start()

    def _build_ui(self):
        v = QVBoxLayout(self)

        # Clock-in/out box
        box = QGroupBox("Clock In / Out")
        form = QFormLayout(box)
        self.tech = QLineEdit()
        self.tech.setPlaceholderText("e.g. Alex")
        form.addRow("Tech name", self.tech)

        self.rate = QDoubleSpinBox()
        self.rate.setDecimals(2); self.rate.setMaximum(500)
        self.rate.setPrefix("$ "); self.rate.setSuffix(" / hr")
        default_rate = float(db.get_setting(self.conn, "default_labor_rate", "125.00"))
        # wage is NOT the same as the billable labor rate — default to something reasonable
        self.rate.setValue(default_rate * 0.35)
        form.addRow("Hourly wage", self.rate)

        self.cmb_job = QComboBox()
        self._refresh_jobs_combo()
        form.addRow("Linked job (optional)", self.cmb_job)

        btn_row = QHBoxLayout()
        self.b_in = QPushButton("Clock IN")
        self.b_in.setStyleSheet("background:#0B2545; color:white; font-weight:bold; padding:8px;")
        self.b_in.clicked.connect(self.clock_in)
        self.b_out = QPushButton("Clock OUT")
        self.b_out.setStyleSheet("background:#C5363A; color:white; font-weight:bold; padding:8px;")
        self.b_out.clicked.connect(self.clock_out)
        btn_row.addWidget(self.b_in); btn_row.addWidget(self.b_out); btn_row.addStretch()
        form.addRow(btn_row)

        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet("font-style: italic; color:#4a4a4a;")
        form.addRow(self.status_lbl)
        v.addWidget(box)

        # Recent entries table
        self.tbl = make_table(["Tech","Job","Clock In","Clock Out","Hours","Rate","Wages"])
        v.addWidget(self.tbl, 1)

        # Refresh / export row
        row = QHBoxLayout()
        row.addStretch()
        b_ref = QPushButton("Refresh"); b_ref.clicked.connect(self.refresh)
        row.addWidget(b_ref)
        v.addLayout(row)

    def _refresh_jobs_combo(self):
        self.cmb_job.clear()
        self.cmb_job.addItem("— none —", None)
        rows = self.conn.execute(
            "SELECT j.id, j.number, c.first_name, c.last_name "
            "FROM jobs j JOIN customers c ON c.id=j.customer_id "
            "WHERE j.status IN ('estimate','invoice') "
            "ORDER BY j.opened_at DESC LIMIT 50"
        ).fetchall()
        for r in rows:
            self.cmb_job.addItem(
                f"{r['number']}  —  {r['first_name']} {r['last_name']}", int(r["id"])
            )

    def _show_current_status(self):
        tech = self.tech.text().strip()
        if not tech:
            self.status_lbl.setText(""); return
        open_e = repo.open_time_entry(self.conn, tech)
        if open_e:
            self.status_lbl.setText(
                f"● {tech} is clocked IN since {open_e['clock_in']}"
            )
        else:
            self.status_lbl.setText(f"{tech} is clocked OUT.")

    def clock_in(self):
        tech = self.tech.text().strip()
        if not tech:
            warn(self, "Missing", "Enter the tech's name."); return
        open_e = repo.open_time_entry(self.conn, tech)
        if open_e:
            warn(self, "Already clocked in",
                 f"{tech} already has an open entry from {open_e['clock_in']}. "
                 "Clock out first.")
            return
        jid = self.cmb_job.currentData()
        repo.clock_in(self.conn, tech, float(self.rate.value()), jid)
        info(self, "Clocked in", f"{tech} clocked in.")
        self._show_current_status()
        self.refresh()

    def clock_out(self):
        tech = self.tech.text().strip()
        if not tech:
            warn(self, "Missing", "Enter the tech's name."); return
        open_e = repo.open_time_entry(self.conn, tech)
        if not open_e:
            warn(self, "Not clocked in", f"{tech} has no open entry."); return
        repo.clock_out(self.conn, int(open_e["id"]))
        info(self, "Clocked out", f"{tech} clocked out.")
        self._show_current_status()
        self.refresh()

    def refresh(self):
        self._refresh_jobs_combo()
        self._show_current_status()
        rows = self.conn.execute(
            "SELECT t.*, j.number AS job_number "
            "FROM time_entries t LEFT JOIN jobs j ON j.id = t.job_id "
            "ORDER BY t.clock_in DESC LIMIT 100"
        ).fetchall()
        self.tbl.setRowCount(0)
        for r in rows:
            i = self.tbl.rowCount(); self.tbl.insertRow(i)
            hours, wages = self._hours_and_wages(r)
            cells = [
                r["tech"],
                r["job_number"] or "—",
                (r["clock_in"] or "")[:16],
                (r["clock_out"] or "— (open)")[:16] if r["clock_out"] else "— (open)",
                f"{hours:.2f}",
                f"${float(r['hourly_rate']):,.2f}",
                f"${wages:,.2f}",
            ]
            for c, v in enumerate(cells):
                it = ro(v)
                if c == 0: it.setData(Qt.UserRole, int(r["id"]))
                self.tbl.setItem(i, c, it)

    @staticmethod
    def _hours_and_wages(r):
        try:
            start = dt.datetime.fromisoformat(r["clock_in"])
        except Exception:
            return 0.0, 0.0
        end_s = r["clock_out"]
        end = dt.datetime.fromisoformat(end_s) if end_s else dt.datetime.utcnow()
        hours = max((end - start).total_seconds() / 3600.0, 0.0)
        wages = hours * float(r["hourly_rate"] or 0)
        return hours, wages

    def _update_open_entries(self):
        # Cheap update: recompute the Hours/Wages cells for any rows whose
        # Clock Out is "— (open)".
        for i in range(self.tbl.rowCount()):
            item = self.tbl.item(i, 3)
            if item and "(open)" in item.text():
                tid = int(self.tbl.item(i, 0).data(Qt.UserRole))
                r = self.conn.execute(
                    "SELECT * FROM time_entries WHERE id=?", (tid,)
                ).fetchone()
                if not r: continue
                hours, wages = self._hours_and_wages(r)
                self.tbl.item(i, 4).setText(f"{hours:.2f}")
                self.tbl.item(i, 6).setText(f"${wages:,.2f}")
