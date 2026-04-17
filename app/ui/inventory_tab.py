"""Inventory + Vendors (combined tab — inventory list and vendor drawer)."""
from __future__ import annotations
from decimal import Decimal
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit, QLabel,
    QFormLayout, QDialog, QDialogButtonBox, QComboBox, QDoubleSpinBox, QSpinBox,
    QTabWidget, QTableWidgetItem,
)
from .. import repo, db
from ..markup import marked_up_price
from .widgets import make_table, ro, warn


class VendorDialog(QDialog):
    def __init__(self, parent=None, data=None):
        super().__init__(parent)
        self.setWindowTitle("Vendor")
        self.setMinimumWidth(380)
        self.fields = {}
        f = QFormLayout(self)
        for label, key in [("Name","name"),("Phone","phone"),("Website","website"),("Notes","notes")]:
            e = QLineEdit()
            if data: e.setText(str(data.get(key) or ""))
            f.addRow(label, e); self.fields[key] = e
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        f.addRow(bb)
        if data: self.fields["_id"] = data.get("id")
    def data(self):
        d = {k: w.text() for k,w in self.fields.items() if k != "_id"}
        if "_id" in self.fields and self.fields.get("_id"): d["id"] = self.fields["_id"]
        return d


class PartDialog(QDialog):
    def __init__(self, conn, parent=None, data=None):
        super().__init__(parent)
        self.setWindowTitle("Part")
        self.setMinimumWidth(460)
        self.conn = conn
        self.fields = {}
        f = QFormLayout(self)

        self.sku = QLineEdit(); f.addRow("SKU", self.sku); self.fields["sku"] = self.sku
        self.desc = QLineEdit(); f.addRow("Description", self.desc); self.fields["description"] = self.desc
        self.cmb_vendor = QComboBox(); self.cmb_vendor.addItem("—", None)
        for v in repo.list_vendors(conn):
            self.cmb_vendor.addItem(v["name"], int(v["id"]))
        f.addRow("Vendor", self.cmb_vendor)

        self.cost = QDoubleSpinBox(); self.cost.setDecimals(2); self.cost.setPrefix("$ ")
        self.cost.setMaximum(1_000_000); self.cost.setSingleStep(1.0)
        self.cost.valueChanged.connect(self._update_suggestions)
        f.addRow("Unit cost (shop cost)", self.cost)

        self.lbl_suggest = QLabel("—")
        self.lbl_suggest.setStyleSheet("color:#4a4a4a; font-style:italic;")
        f.addRow("Suggested sell price", self.lbl_suggest)

        self.on_hand = QSpinBox(); self.on_hand.setMaximum(100_000)
        f.addRow("On hand", self.on_hand)
        self.reorder = QSpinBox(); self.reorder.setMaximum(100_000)
        f.addRow("Reorder point", self.reorder)
        self.location = QLineEdit()
        f.addRow("Location (bin)", self.location); self.fields["location"] = self.location
        self.last_recv = QLineEdit()
        self.last_recv.setPlaceholderText("YYYY-MM-DD")
        f.addRow("Last received", self.last_recv); self.fields["last_received"] = self.last_recv

        self.markup_tiers = db.load_markup_tiers(conn)

        if data:
            self.sku.setText(data.get("sku") or "")
            self.desc.setText(data.get("description") or "")
            vid = data.get("vendor_id")
            if vid:
                idx = self.cmb_vendor.findData(int(vid))
                if idx >= 0: self.cmb_vendor.setCurrentIndex(idx)
            self.cost.setValue(float(data.get("unit_cost") or 0))
            self.on_hand.setValue(int(data.get("on_hand") or 0))
            self.reorder.setValue(int(data.get("reorder_point") or 0))
            self.location.setText(data.get("location") or "")
            self.last_recv.setText(data.get("last_received") or "")
            self._existing_id = data.get("id")
        else:
            self._existing_id = None

        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        f.addRow(bb)
        self._update_suggestions(self.cost.value())

    def _update_suggestions(self, v: float):
        if v <= 0:
            self.lbl_suggest.setText("—"); return
        price = marked_up_price(Decimal(str(v)), self.markup_tiers)
        profit = price - Decimal(str(v))
        self.lbl_suggest.setText(f"${price:,.2f}  (profit ${profit:,.2f})")

    def data(self):
        d = {
            "sku": self.sku.text().strip(),
            "description": self.desc.text().strip(),
            "vendor_id": self.cmb_vendor.currentData(),
            "unit_cost": float(self.cost.value()),
            "on_hand": int(self.on_hand.value()),
            "reorder_point": int(self.reorder.value()),
            "location": self.location.text().strip(),
            "last_received": self.last_recv.text().strip() or None,
        }
        if self._existing_id: d["id"] = self._existing_id
        return d


class InventoryTab(QWidget):
    def __init__(self, conn):
        super().__init__()
        self.conn = conn
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        main = QVBoxLayout(self)
        tabs = QTabWidget()
        main.addWidget(tabs)

        # Parts sub-tab
        parts = QWidget(); pv = QVBoxLayout(parts)
        top = QHBoxLayout()
        self.search = QLineEdit(); self.search.setPlaceholderText("Search by description or SKU…")
        self.search.textChanged.connect(self.refresh)
        top.addWidget(self.search)
        b_new = QPushButton("+ New Part"); b_new.clicked.connect(self.new_part)
        b_edit = QPushButton("Edit"); b_edit.clicked.connect(self.edit_part)
        top.addStretch(); top.addWidget(b_new); top.addWidget(b_edit)
        pv.addLayout(top)
        self.tbl = make_table(["SKU","Description","Vendor","Cost","Sell (auto)","Profit","On hand","Reorder"])
        pv.addWidget(self.tbl)
        tabs.addTab(parts, "Parts / Materials")

        # Vendors sub-tab
        vendors = QWidget(); vv = QVBoxLayout(vendors)
        vtop = QHBoxLayout()
        b_nv = QPushButton("+ New Vendor"); b_nv.clicked.connect(self.new_vendor)
        b_ev = QPushButton("Edit Vendor"); b_ev.clicked.connect(self.edit_vendor)
        vtop.addStretch(); vtop.addWidget(b_nv); vtop.addWidget(b_ev)
        vv.addLayout(vtop)
        self.vtbl = make_table(["Name","Phone","Website","Notes"])
        vv.addWidget(self.vtbl)
        tabs.addTab(vendors, "Vendors")

    def refresh(self):
        tiers = db.load_markup_tiers(self.conn)
        rows = repo.list_inventory(self.conn, self.search.text().strip())
        self.tbl.setRowCount(0)
        for r in rows:
            i = self.tbl.rowCount(); self.tbl.insertRow(i)
            cost = Decimal(str(r["unit_cost"]))
            sell = marked_up_price(cost, tiers)
            profit = sell - cost
            cells = [
                r["sku"] or "", r["description"], r["vendor_name"] or "",
                f"${cost:,.2f}", f"${sell:,.2f}", f"${profit:,.2f}",
                str(r["on_hand"]),
                f"{r['reorder_point']}{' ⚠' if r['on_hand'] < r['reorder_point'] else ''}",
            ]
            for c, v in enumerate(cells):
                it = ro(v)
                if c == 0: it.setData(Qt.UserRole, int(r["id"]))
                self.tbl.setItem(i, c, it)
        # vendors
        vrows = repo.list_vendors(self.conn)
        self.vtbl.setRowCount(0)
        for r in vrows:
            i = self.vtbl.rowCount(); self.vtbl.insertRow(i)
            cells = [r["name"], r["phone"] or "", r["website"] or "", r["notes"] or ""]
            for c, v in enumerate(cells):
                it = ro(v)
                if c == 0: it.setData(Qt.UserRole, int(r["id"]))
                self.vtbl.setItem(i, c, it)

    def _selected_part(self):
        row = self.tbl.currentRow()
        if row < 0: return None
        return int(self.tbl.item(row, 0).data(Qt.UserRole))
    def _selected_vendor(self):
        row = self.vtbl.currentRow()
        if row < 0: return None
        return int(self.vtbl.item(row, 0).data(Qt.UserRole))

    def new_part(self):
        d = PartDialog(self.conn, self)
        if d.exec() == QDialog.Accepted:
            repo.upsert_part(self.conn, d.data()); self.refresh()
    def edit_part(self):
        pid = self._selected_part()
        if pid is None: return
        row = self.conn.execute("SELECT * FROM inventory WHERE id=?", (pid,)).fetchone()
        if not row: return
        d = PartDialog(self.conn, self, data=dict(row))
        if d.exec() == QDialog.Accepted:
            repo.upsert_part(self.conn, d.data()); self.refresh()
    def new_vendor(self):
        d = VendorDialog(self)
        if d.exec() == QDialog.Accepted:
            data = d.data()
            if not data.get("name"):
                warn(self, "Missing", "Vendor name required."); return
            repo.upsert_vendor(self.conn, data); self.refresh()
    def edit_vendor(self):
        vid = self._selected_vendor()
        if vid is None: return
        row = self.conn.execute("SELECT * FROM vendors WHERE id=?", (vid,)).fetchone()
        if not row: return
        d = VendorDialog(self, data=dict(row))
        if d.exec() == QDialog.Accepted:
            repo.upsert_vendor(self.conn, d.data()); self.refresh()
