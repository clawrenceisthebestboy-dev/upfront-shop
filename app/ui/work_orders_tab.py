"""Work Orders tab.

Lists every OPEN estimate (status='estimate') and lets the shop print a
tech-facing work order for it. Work orders are print-only — they are not
saved to the database, so nothing here touches the schema or the repo
layer except to read.

The actual PDF layout lives in ``app.work_order_pdf``; this file is just
the Qt glue.
"""
from __future__ import annotations
import datetime as dt
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
)

from .. import repo
from ..printer import print_pdf, output_dir
from ..work_order_pdf import render_work_order_pdf
from .widgets import make_table, ro, warn, info


class WorkOrdersTab(QWidget):
    """Sister-tab to Jobs/Invoices, restricted to open estimates and
    geared around printing a no-pricing, no-labor-time bay slip."""

    def __init__(self, conn):
        super().__init__()
        self.conn = conn
        self._settings: dict[str, str] = {}
        self._build_ui()
        self.refresh()

    # ---------------------------- UI ----------------------------

    def _build_ui(self) -> None:
        v = QVBoxLayout(self)

        blurb = QLabel(
            "Open estimates only — pick one to print a tech-facing work order. "
            "Work orders contain no pricing and no labor times; they're meant "
            "to pin up in the bay."
        )
        blurb.setWordWrap(True)
        blurb.setStyleSheet("color:#4a4a4a; padding:2px 2px 8px 2px;")
        v.addWidget(blurb)

        top = QHBoxLayout()
        top.addStretch()
        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_preview = QPushButton("Preview Work Order")
        self.btn_preview.clicked.connect(self.preview_selected)
        self.btn_print = QPushButton("Print Work Order")
        self.btn_print.setStyleSheet(
            "background:#0B2545; color:white; font-weight:bold;"
        )
        self.btn_print.clicked.connect(self.print_selected)
        for b in (self.btn_refresh, self.btn_preview, self.btn_print):
            top.addWidget(b)
        v.addLayout(top)

        self.tbl = make_table(["Estimate #", "Customer", "Vehicle", "Opened"])
        self.tbl.cellDoubleClicked.connect(lambda *_: self.print_selected())
        v.addWidget(self.tbl)

    # ------------------------ Data binding ----------------------

    def refresh(self) -> None:
        """Reload the list of open estimates."""
        # Re-read settings on every refresh so any change in the Settings
        # tab (shop name, phone, logo, …) shows up on the next print.
        self._settings = {
            r["key"]: r["value"] for r in self.conn.execute("SELECT * FROM settings")
        }
        rows = repo.list_jobs(self.conn, ("estimate",))
        self.tbl.setRowCount(0)
        for r in rows:
            i = self.tbl.rowCount()
            self.tbl.insertRow(i)
            veh = " ".join(
                str(x) for x in [r["year"] or "", r["make"] or "", r["model"] or ""]
            ).strip() or "—"
            cust = f"{r['first_name']} {r['last_name']}".strip() or "—"
            cells = [
                r["number"],
                cust,
                veh,
                (r["opened_at"] or "")[:16],
            ]
            for c, val in enumerate(cells):
                it = ro(val)
                if c == 0:
                    it.setData(Qt.UserRole, int(r["id"]))
                self.tbl.setItem(i, c, it)

    # ------------------------- Actions --------------------------

    def _selected_job_id(self) -> int | None:
        row = self.tbl.currentRow()
        if row < 0:
            return None
        return int(self.tbl.item(row, 0).data(Qt.UserRole))

    def _render_current(self) -> Path | None:
        """Build the work-order PDF for the current row and return the path."""
        jid = self._selected_job_id()
        if jid is None:
            warn(self, "Pick an estimate",
                 "Select an estimate from the list first.")
            return None
        job_row = repo.get_job(self.conn, jid)
        if job_row is None:
            warn(self, "Missing", "That estimate no longer exists.")
            return None
        job = dict(job_row)
        cust = dict(repo.get_customer(self.conn, job["customer_id"]))
        veh_row = None
        if job["vehicle_id"]:
            veh_row = self.conn.execute(
                "SELECT * FROM vehicles WHERE id=?", (job["vehicle_id"],)
            ).fetchone()
        vehicle = dict(veh_row) if veh_row else None
        lines = repo.load_lines(self.conn, jid)

        out = output_dir() / (
            f"work_order_{job['number']}_"
            f"{dt.date.today().isoformat()}.pdf"
        )
        try:
            render_work_order_pdf(
                str(out), shop=self._settings, customer=cust,
                vehicle=vehicle, job=job, lines=lines,
            )
        except Exception as e:
            warn(self, "Couldn't render work order",
                 f"ReportLab raised: {e}")
            return None
        return out

    def preview_selected(self) -> None:
        """Build the PDF and open it with the OS viewer — no printing."""
        out = self._render_current()
        if out is None:
            return
        # ``print_pdf`` on non-Windows falls back to opening the PDF, which
        # is exactly what we want for 'preview'. On Windows we open it the
        # same way the customer-invoice preview does, via the shell.
        try:
            import os, subprocess, sys
            if os.name == "nt":
                os.startfile(str(out))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(out)])
            else:
                subprocess.Popen(["xdg-open", str(out)])
        except Exception as e:
            warn(self, "Preview", f"Could not open the PDF: {e}\n\nFile: {out}")
            return
        info(self, "Work order",
             f"Opened preview. PDF saved to:\n{out}\n\n"
             "Nothing was sent to the printer.")

    def print_selected(self) -> None:
        """Build the PDF and push it straight to the configured printer."""
        out = self._render_current()
        if out is None:
            return
        printer = self._settings.get("printer_name") or None
        ok = print_pdf(out, printer)
        if ok:
            info(self, "Work order printing",
                 f"Sent to printer: {printer or '(system default)'}\n\n"
                 f"File: {out}")
        else:
            warn(self, "Work order",
                 f"Could not print automatically.\nOpen and print manually:\n{out}")
