"""Customers + Vehicles tab."""
from __future__ import annotations
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit, QLabel,
    QFormLayout, QSplitter, QGroupBox, QDialog, QDialogButtonBox, QMessageBox,
    QSpinBox, QTableWidgetItem,
)
from .. import repo
from .widgets import make_table, ro, confirm, warn


class CustomerDialog(QDialog):
    def __init__(self, parent=None, data=None):
        super().__init__(parent)
        self.setWindowTitle("Customer")
        self.setMinimumWidth(420)
        self.fields = {}
        form = QFormLayout(self)
        for label, key in [
            ("First name","first_name"), ("Last name","last_name"),
            ("Phone","phone"), ("Email","email"),
            ("Address 1","address1"), ("Address 2","address2"),
            ("City","city"), ("State","state"), ("ZIP","zip"), ("Notes","notes"),
        ]:
            e = QLineEdit()
            if data: e.setText(str(data.get(key) or ""))
            form.addRow(label, e)
            self.fields[key] = e
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        form.addRow(bb)
        if data: self.fields["_id"] = data.get("id")

    def data(self):
        d = {k: w.text() for k, w in self.fields.items() if k != "_id"}
        if "_id" in self.fields and self.fields.get("_id"): d["id"] = self.fields["_id"]
        return d


class VehicleDialog(QDialog):
    def __init__(self, parent=None, customer_id=None, data=None):
        super().__init__(parent)
        self.setWindowTitle("Vehicle")
        self.setMinimumWidth(420)
        self.customer_id = customer_id
        self.fields = {}
        form = QFormLayout(self)
        for label, key in [
            ("Year","year"), ("Make","make"), ("Model","model"), ("Trim","trim"),
            ("VIN","vin"), ("Plate","plate"), ("Color","color"),
            ("Mileage","mileage"), ("Inspection exp (YYYY-MM)","inspection_exp"),
            ("Notes","notes"),
        ]:
            e = QLineEdit()
            if data: e.setText(str(data.get(key) or ""))
            form.addRow(label, e)
            self.fields[key] = e
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        form.addRow(bb)
        if data: self.fields["_id"] = data.get("id")

    def data(self):
        d = {k: (w.text().strip() or None) for k, w in self.fields.items() if k != "_id"}
        # cast numerics
        for k in ("year","mileage"):
            try: d[k] = int(d[k]) if d.get(k) else None
            except ValueError: d[k] = None
        d["customer_id"] = self.customer_id
        if "_id" in self.fields and self.fields.get("_id"): d["id"] = self.fields["_id"]
        return d


class CustomersTab(QWidget):
    def __init__(self, conn):
        super().__init__()
        self.conn = conn
        self._build_ui()
        self.refresh_customers()

    def _build_ui(self):
        main = QHBoxLayout(self)
        split = QSplitter(Qt.Horizontal)
        main.addWidget(split)

        # Left: customer list
        left = QWidget(); ll = QVBoxLayout(left)
        search_row = QHBoxLayout()
        self.search = QLineEdit(); self.search.setPlaceholderText("Search by name, phone, email…")
        self.search.textChanged.connect(self.refresh_customers)
        search_row.addWidget(self.search)
        ll.addLayout(search_row)
        self.cust_table = make_table(["Last", "First", "Phone", "Email", "City"])
        self.cust_table.itemSelectionChanged.connect(self._on_select_customer)
        ll.addWidget(self.cust_table)
        btns = QHBoxLayout()
        b_new = QPushButton("+ New Customer"); b_new.clicked.connect(self.new_customer)
        b_edit = QPushButton("Edit"); b_edit.clicked.connect(self.edit_customer)
        btns.addWidget(b_new); btns.addWidget(b_edit); btns.addStretch()
        ll.addLayout(btns)
        split.addWidget(left)

        # Right: vehicles for selected customer
        right = QWidget(); rl = QVBoxLayout(right)
        self.veh_header = QLabel("<i>Select a customer to see vehicles</i>")
        rl.addWidget(self.veh_header)
        self.veh_table = make_table(["Year", "Make", "Model", "Plate", "VIN", "Inspection exp"])
        rl.addWidget(self.veh_table)
        vb = QHBoxLayout()
        b_nv = QPushButton("+ New Vehicle"); b_nv.clicked.connect(self.new_vehicle)
        b_ev = QPushButton("Edit Vehicle"); b_ev.clicked.connect(self.edit_vehicle)
        vb.addWidget(b_nv); vb.addWidget(b_ev); vb.addStretch()
        rl.addLayout(vb)
        split.addWidget(right)
        split.setSizes([500, 500])

    def _selected_cid(self):
        row = self.cust_table.currentRow()
        if row < 0: return None
        return int(self.cust_table.item(row, 0).data(Qt.UserRole))

    def _selected_vehicle_id(self):
        row = self.veh_table.currentRow()
        if row < 0: return None
        return int(self.veh_table.item(row, 0).data(Qt.UserRole))

    def refresh_customers(self):
        rows = repo.list_customers(self.conn, self.search.text().strip())
        self.cust_table.setRowCount(0)
        for r in rows:
            i = self.cust_table.rowCount()
            self.cust_table.insertRow(i)
            cells = [r["last_name"], r["first_name"], r["phone"] or "", r["email"] or "", r["city"] or ""]
            for c, v in enumerate(cells):
                it = ro(v)
                if c == 0: it.setData(Qt.UserRole, int(r["id"]))
                self.cust_table.setItem(i, c, it)

    def _on_select_customer(self):
        cid = self._selected_cid()
        if cid is None:
            self.veh_header.setText("<i>Select a customer to see vehicles</i>")
            self.veh_table.setRowCount(0)
            return
        c = repo.get_customer(self.conn, cid)
        self.veh_header.setText(f"<b>Vehicles for {c['first_name']} {c['last_name']}</b>")
        self.refresh_vehicles(cid)

    def refresh_vehicles(self, cid):
        rows = repo.vehicles_for_customer(self.conn, cid)
        self.veh_table.setRowCount(0)
        for r in rows:
            i = self.veh_table.rowCount()
            self.veh_table.insertRow(i)
            cells = [str(r["year"] or ""), r["make"] or "", r["model"] or "",
                     r["plate"] or "", r["vin"] or "", r["inspection_exp"] or ""]
            for c, v in enumerate(cells):
                it = ro(v)
                if c == 0: it.setData(Qt.UserRole, int(r["id"]))
                self.veh_table.setItem(i, c, it)

    def new_customer(self):
        d = CustomerDialog(self)
        if d.exec() == QDialog.Accepted:
            data = d.data()
            if not data.get("last_name"):
                warn(self, "Missing", "Last name is required."); return
            repo.upsert_customer(self.conn, data)
            self.refresh_customers()

    def edit_customer(self):
        cid = self._selected_cid()
        if cid is None: return
        c = dict(repo.get_customer(self.conn, cid))
        d = CustomerDialog(self, data=c)
        if d.exec() == QDialog.Accepted:
            repo.upsert_customer(self.conn, d.data())
            self.refresh_customers()

    def new_vehicle(self):
        cid = self._selected_cid()
        if cid is None:
            warn(self, "No customer", "Select a customer first."); return
        d = VehicleDialog(self, customer_id=cid)
        if d.exec() == QDialog.Accepted:
            repo.upsert_vehicle(self.conn, d.data())
            self.refresh_vehicles(cid)

    def edit_vehicle(self):
        cid = self._selected_cid(); vid = self._selected_vehicle_id()
        if not (cid and vid): return
        row = self.conn.execute("SELECT * FROM vehicles WHERE id=?", (vid,)).fetchone()
        if not row: return
        d = VehicleDialog(self, customer_id=cid, data=dict(row))
        if d.exec() == QDialog.Accepted:
            repo.upsert_vehicle(self.conn, d.data())
            self.refresh_vehicles(cid)
