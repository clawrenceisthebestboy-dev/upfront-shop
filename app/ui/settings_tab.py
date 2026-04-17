"""Settings tab — shop info, rates, printer, markup tier editor."""
from __future__ import annotations
import shutil
from pathlib import Path
from decimal import Decimal
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QLabel,
    QDoubleSpinBox, QComboBox, QPushButton, QTabWidget, QGroupBox,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView,
    QFileDialog, QCheckBox,
)
from .. import db, printer
from .. import APP_VERSION
from .widgets import info, warn, confirm


class SettingsTab(QWidget):
    def __init__(self, conn):
        super().__init__()
        self.conn = conn
        self._build_ui()
        self._load()

    def _build_ui(self):
        v = QVBoxLayout(self)
        tabs = QTabWidget()
        v.addWidget(tabs)

        # ----- Shop info -----
        shop = QWidget(); sv = QVBoxLayout(shop)
        shop_box = QGroupBox("Shop information (appears on estimates and invoices)")
        sf = QFormLayout(shop_box)
        self.shop_name     = QLineEdit(); sf.addRow("Shop name", self.shop_name)
        self.shop_address1 = QLineEdit(); sf.addRow("Address 1", self.shop_address1)
        self.shop_address2 = QLineEdit(); sf.addRow("Address 2", self.shop_address2)
        row = QHBoxLayout()
        self.shop_city = QLineEdit(); self.shop_state = QLineEdit(); self.shop_zip = QLineEdit()
        self.shop_state.setMaxLength(2); self.shop_state.setFixedWidth(50)
        self.shop_zip.setFixedWidth(100)
        row.addWidget(self.shop_city, 3); row.addWidget(self.shop_state, 0); row.addWidget(self.shop_zip, 1)
        w = QWidget(); w.setLayout(row); sf.addRow("City / State / ZIP", w)
        self.shop_phone    = QLineEdit(); sf.addRow("Phone", self.shop_phone)
        self.shop_email    = QLineEdit(); sf.addRow("Email", self.shop_email)
        self.shop_website  = QLineEdit(); sf.addRow("Website", self.shop_website)
        self.invoice_footer = QLineEdit(); sf.addRow("Invoice footer", self.invoice_footer)
        sv.addWidget(shop_box)
        sv.addStretch()
        tabs.addTab(shop, "Shop Info")

        # ----- Branding (logo + QR review code) -----
        brand = QWidget(); bv = QVBoxLayout(brand)
        logo_box = QGroupBox("Shop logo (prints top-left of every estimate and invoice)")
        lf = QFormLayout(logo_box)
        self.logo_preview = QLabel("—")
        self.logo_preview.setFixedSize(140, 140)
        self.logo_preview.setAlignment(Qt.AlignCenter)
        self.logo_preview.setStyleSheet("background:#F2F4F8; border:1px solid #B3BCC9;")
        self.logo_path_edit = QLineEdit()
        self.logo_path_edit.setReadOnly(True)
        b_pick = QPushButton("Choose image…"); b_pick.clicked.connect(self._pick_logo)
        b_clr = QPushButton("Clear"); b_clr.clicked.connect(self._clear_logo)
        lrow = QHBoxLayout(); lrow.addWidget(self.logo_path_edit, 1)
        lrow.addWidget(b_pick); lrow.addWidget(b_clr)
        lwrap = QWidget(); lwrap.setLayout(lrow)
        lf.addRow("File", lwrap)
        lf.addRow("Preview", self.logo_preview)
        bv.addWidget(logo_box)

        qr_box = QGroupBox("QR code for customer reviews (printed at the bottom of every invoice)")
        qf = QFormLayout(qr_box)
        self.review_url = QLineEdit()
        self.review_url.setPlaceholderText("https://upfrontautorepair207.com")
        qf.addRow("QR target URL", self.review_url)
        self.review_cta = QLineEdit()
        self.review_cta.setPlaceholderText("Scan to leave us a review")
        qf.addRow("QR caption", self.review_cta)
        qr_hint = QLabel(
            "<i>Tip: point this at a Google review link (e.g. "
            "<code>https://g.page/r/&lt;your-place-id&gt;/review</code>) so every "
            "customer's scan drops them straight on the review form. Leave as the "
            "site URL if you'd rather people land on your website first.</i>"
        )
        qr_hint.setWordWrap(True); qr_hint.setStyleSheet("color:#4a4a4a;")
        qf.addRow(qr_hint)
        bv.addWidget(qr_box)
        bv.addStretch()
        tabs.addTab(brand, "Branding / QR")

        # ----- Rates & defaults -----
        rates = QWidget(); rv = QVBoxLayout(rates)
        r_box = QGroupBox("Rates & defaults  (these apply to NEW lines; any invoice can still override)")
        rf = QFormLayout(r_box)

        self.tax_rate = self._pct_spin()
        rf.addRow("Maine sales tax (%)", self.tax_rate)
        self.card_rate = self._pct_spin()
        rf.addRow("Non-cash adjustment (%)  — always added", self.card_rate)
        self.cash_rate = self._pct_spin()
        rf.addRow("Cash / check discount (%)  — cancels the adjustment", self.cash_rate)

        self.labor_rate = QDoubleSpinBox()
        self.labor_rate.setDecimals(2); self.labor_rate.setMaximum(2000)
        self.labor_rate.setPrefix("$ "); self.labor_rate.setSuffix(" / hr")
        rf.addRow("Default labor rate", self.labor_rate)

        self.inspection_fee = QDoubleSpinBox()
        self.inspection_fee.setDecimals(2); self.inspection_fee.setMaximum(500)
        self.inspection_fee.setPrefix("$ ")
        rf.addRow("Maine inspection fee", self.inspection_fee)
        rv.addWidget(r_box)

        note = QLabel(
            "<i>Labor rate and any part's final price are fully editable on every "
            "individual estimate or invoice. This is only the default the app "
            "fills in when you add a new line.</i>"
        )
        note.setWordWrap(True); note.setStyleSheet("color:#4a4a4a;")
        rv.addWidget(note)
        rv.addStretch()
        tabs.addTab(rates, "Rates & Defaults")

        # ----- Printer -----
        prt = QWidget(); pv = QVBoxLayout(prt)
        p_box = QGroupBox("Receipt / invoice printer")
        pf = QFormLayout(p_box)
        row = QHBoxLayout()
        self.cmb_printer = QComboBox()
        b_refresh = QPushButton("Refresh list"); b_refresh.clicked.connect(self._refresh_printers)
        row.addWidget(self.cmb_printer, 1); row.addWidget(b_refresh)
        w = QWidget(); w.setLayout(row)
        pf.addRow("Printer", w)
        pv.addWidget(p_box)

        note_p = QLabel(
            "<i>Pick a WiFi / network printer the shop laptop can already see in "
            "Windows. Leave this on <b>(system default)</b> to just use whatever "
            "printer is set as default in Windows.</i>"
        )
        note_p.setWordWrap(True); note_p.setStyleSheet("color:#4a4a4a;")
        pv.addWidget(note_p)
        pv.addStretch()
        tabs.addTab(prt, "Printer")

        # ----- Markup tiers -----
        mk = QWidget(); mv = QVBoxLayout(mk)
        mv.addWidget(QLabel(
            "<b>Parts markup — customer-facing.</b> Each row is a cost band. "
            "Enter the <b>target profit %</b> you want on that band (e.g. 63.6 for "
            "63.6%). The app applies that profit % on every estimate and invoice."
        ))
        self.tier_tbl = QTableWidget(0, 2)
        self.tier_tbl.setHorizontalHeaderLabels([
            "Cost band (up to …)", "Profit %"
        ])
        self.tier_tbl.verticalHeader().setVisible(False)
        self.tier_tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tier_tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tier_tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        mv.addWidget(self.tier_tbl)

        trow = QHBoxLayout()
        b_add = QPushButton("Add tier"); b_add.clicked.connect(self._tier_add)
        b_del = QPushButton("Remove selected"); b_del.clicked.connect(self._tier_del)
        b_reset = QPushButton("Reset to shop default"); b_reset.clicked.connect(self._tier_reset)
        trow.addWidget(b_add); trow.addWidget(b_del); trow.addStretch(); trow.addWidget(b_reset)
        mv.addLayout(trow)
        tabs.addTab(mk, "Parts Markup")

        # ----- Updates -----
        upd = QWidget(); uv = QVBoxLayout(upd)
        upd_box = QGroupBox(
            "Automatic updates  —  pull new versions over the internet"
        )
        uf = QFormLayout(upd_box)
        self.update_url = QLineEdit()
        self.update_url.setPlaceholderText(
            "https://upfrontautorepair207.com/upfront-shop/latest.json"
        )
        uf.addRow("Update manifest URL", self.update_url)
        self.update_on_startup = QCheckBox(
            "Check for updates automatically when the app starts"
        )
        uf.addRow("", self.update_on_startup)
        self.update_last_lbl = QLabel("—")
        self.update_last_lbl.setStyleSheet("color:#4a4a4a;")
        uf.addRow("Last checked", self.update_last_lbl)
        self.installed_version_lbl = QLabel(f"v{APP_VERSION}")
        self.installed_version_lbl.setStyleSheet(
            "color:#0B2545; font-weight:bold;"
        )
        uf.addRow("Installed version", self.installed_version_lbl)

        check_row = QHBoxLayout()
        check_row.addStretch()
        self.btn_check_now = QPushButton("Check for updates now")
        self.btn_check_now.clicked.connect(self._check_updates_now)
        check_row.addWidget(self.btn_check_now)
        uf.addRow("", self._wrap_row(check_row))

        uv.addWidget(upd_box)

        hint = QLabel(
            "<i>Leave the URL blank to disable remote updates entirely. "
            "Updates are cryptographically signed — the app refuses any "
            "installer whose signature doesn't match the built-in key, "
            "even if the web host is compromised.</i>"
        )
        hint.setWordWrap(True); hint.setStyleSheet("color:#4a4a4a;")
        uv.addWidget(hint)
        uv.addStretch()
        tabs.addTab(upd, "Updates")

        # Save/Reload row
        row = QHBoxLayout()
        row.addStretch()
        b_reload = QPushButton("Reload"); b_reload.clicked.connect(self._load)
        b_save = QPushButton("Save changes"); b_save.clicked.connect(self._save)
        b_save.setStyleSheet("background:#0B2545; color:white; font-weight:bold; padding:8px;")
        row.addWidget(b_reload); row.addWidget(b_save)
        v.addLayout(row)

    @staticmethod
    def _pct_spin() -> QDoubleSpinBox:
        s = QDoubleSpinBox()
        s.setDecimals(3); s.setMaximum(100); s.setSingleStep(0.1); s.setSuffix(" %")
        return s

    @staticmethod
    def _wrap_row(layout: QHBoxLayout) -> QWidget:
        w = QWidget(); w.setLayout(layout)
        return w

    def _check_updates_now(self):
        """Run the manual update check without waiting for a save."""
        # Persist whatever the user has typed into the URL field right now so
        # the updater reads the fresh value on this click (otherwise it would
        # use whatever was last saved).
        db.set_setting(self.conn, "update_url",
                        self.update_url.text().strip())
        db.set_setting(
            self.conn, "update_on_startup",
            "1" if self.update_on_startup.isChecked() else "0",
        )
        # Lazy import to avoid any import cycle with main_window.
        from .update_flow import check_for_updates_manual
        check_for_updates_manual(self, self.conn)
        self._refresh_last_checked()

    def _refresh_last_checked(self):
        ts = db.get_setting(self.conn, "update_last_checked", "")
        self.update_last_lbl.setText(ts or "—")

    # -------------- load / save --------------

    def _load(self):
        g = lambda k, d="": db.get_setting(self.conn, k, d)
        self.shop_name.setText(g("shop_name"))
        self.shop_address1.setText(g("shop_address1"))
        self.shop_address2.setText(g("shop_address2"))
        self.shop_city.setText(g("shop_city"))
        self.shop_state.setText(g("shop_state"))
        self.shop_zip.setText(g("shop_zip"))
        self.shop_phone.setText(g("shop_phone"))
        self.shop_email.setText(g("shop_email"))
        self.shop_website.setText(g("shop_website"))
        self.invoice_footer.setText(g("invoice_footer"))
        self.tax_rate.setValue(float(g("tax_rate", "0.055")) * 100)
        # Prefer the new keys; fall back to legacy keys for older installs.
        self.card_rate.setValue(
            float(g("non_cash_adjustment_rate", g("card_surcharge_rate", "0.035"))) * 100
        )
        self.cash_rate.setValue(
            float(g("cash_check_discount_rate", g("cash_discount_rate", "0.035"))) * 100
        )
        self.labor_rate.setValue(float(g("default_labor_rate", "125.00")))
        self.inspection_fee.setValue(float(g("inspection_fee", "18.50")))
        self.logo_path_edit.setText(g("logo_path", ""))
        self.review_url.setText(g("review_url", ""))
        self.review_cta.setText(g("review_cta", "Scan to leave us a review"))
        self.update_url.setText(g(
            "update_url",
            "https://upfrontautorepair207.com/upfront-shop/latest.json",
        ))
        self.update_on_startup.setChecked(g("update_on_startup", "1") == "1")
        self._refresh_last_checked()
        self._refresh_logo_preview()
        self._refresh_printers()
        self._load_tiers()

    def _refresh_logo_preview(self):
        p = self.logo_path_edit.text().strip()
        if not p or not Path(p).is_file():
            self.logo_preview.setText("(no logo)")
            self.logo_preview.setPixmap(QPixmap())
            return
        pm = QPixmap(p)
        if pm.isNull():
            self.logo_preview.setText("(can't read image)")
            return
        scaled = pm.scaled(self.logo_preview.width()-8, self.logo_preview.height()-8,
                           Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.logo_preview.setPixmap(scaled)

    def _pick_logo(self):
        p, _ = QFileDialog.getOpenFileName(
            self, "Choose shop logo", "",
            "Images (*.png *.jpg *.jpeg *.gif *.bmp)"
        )
        if not p: return
        # Copy it into %APPDATA%\UpFrontShop\assets\ so it survives even if
        # the user deletes the original from their Downloads folder.
        dest_dir = db.default_db_path().parent / "assets"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"logo{Path(p).suffix.lower()}"
        try:
            shutil.copyfile(p, dest)
        except Exception as e:
            warn(self, "Logo", f"Could not copy file: {e}")
            return
        self.logo_path_edit.setText(str(dest))
        self._refresh_logo_preview()

    def _clear_logo(self):
        self.logo_path_edit.setText("")
        self._refresh_logo_preview()

    def _refresh_printers(self):
        current = db.get_setting(self.conn, "printer_name", "")
        self.cmb_printer.clear()
        self.cmb_printer.addItem("(system default)", "")
        for name in printer.list_printers():
            self.cmb_printer.addItem(name, name)
        default = printer.default_printer()
        if default:
            self.cmb_printer.setItemText(0, f"(system default: {default})")
        idx = self.cmb_printer.findData(current)
        self.cmb_printer.setCurrentIndex(idx if idx >= 0 else 0)

    def _load_tiers(self):
        self.tier_tbl.blockSignals(True)
        self.tier_tbl.setRowCount(0)
        rows = self.conn.execute(
            "SELECT * FROM markup_tiers ORDER BY sort_order"
        ).fetchall()
        for r in rows:
            self._tier_append_row(r["upper_bound"], r["multiplier"])
        self.tier_tbl.blockSignals(False)

    def _tier_append_row(self, upper, mult):
        r = self.tier_tbl.rowCount()
        self.tier_tbl.insertRow(r)
        # col 0: upper bound (blank = "and up")
        bound_txt = "" if upper is None else f"{float(upper):.2f}"
        b = QTableWidgetItem(bound_txt)
        self.tier_tbl.setItem(r, 0, b)
        # col 1: profit % — the editable field
        pct = self._mult_to_pct(mult)
        p = QTableWidgetItem(f"{pct:.1f}")
        p.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.tier_tbl.setItem(r, 1, p)

    @staticmethod
    def _mult_to_pct(mult) -> float:
        """Convert the DB-stored tier value to the target profit % shown in
        the UI. Internal helper only — the multiplier is never displayed."""
        try:
            m = float(mult)
            if m <= 0: return 0.0
            return (m - 1) / m * 100
        except Exception:
            return 0.0

    @staticmethod
    def _pct_to_mult(pct) -> float:
        """Convert the UI profit % back to the value stored in the DB tier
        row. Internal helper only — kept so we don't have to touch the DB
        schema. profit% = (mult - 1)/mult   =>   mult = 1 / (1 - profit%)"""
        p = float(pct) / 100.0
        if p < 0: p = 0.0
        if p >= 0.999:  # sanity cap to avoid divide-by-zero / silly values
            p = 0.999
        return 1.0 / (1.0 - p)

    def _tier_add(self):
        self.tier_tbl.blockSignals(True)
        # new tier defaults to 50% profit
        self._tier_append_row(None, 2.00)
        self.tier_tbl.blockSignals(False)

    def _tier_del(self):
        r = self.tier_tbl.currentRow()
        if r < 0: return
        self.tier_tbl.removeRow(r)

    def _tier_reset(self):
        if not confirm(self, "Reset markup tiers",
                       "Replace the current markup tiers with the shop default table "
                       "(9 bands from 75% profit on the cheapest parts down to "
                       "41% profit on the most expensive)?"):
            return
        self.conn.execute("DELETE FROM markup_tiers")
        self.conn.executemany(
            "INSERT INTO markup_tiers(sort_order, upper_bound, multiplier) VALUES (?,?,?)",
            db.DEFAULT_MARKUP,
        )
        self.conn.commit()
        self._load_tiers()
        info(self, "Reset", "Markup tiers restored to shop default.")

    def _save(self):
        # Shop info
        pairs = [
            ("shop_name", self.shop_name.text().strip()),
            ("shop_address1", self.shop_address1.text().strip()),
            ("shop_address2", self.shop_address2.text().strip()),
            ("shop_city", self.shop_city.text().strip()),
            ("shop_state", self.shop_state.text().strip()),
            ("shop_zip", self.shop_zip.text().strip()),
            ("shop_phone", self.shop_phone.text().strip()),
            ("shop_email", self.shop_email.text().strip()),
            ("shop_website", self.shop_website.text().strip()),
            ("invoice_footer", self.invoice_footer.text()),
            ("tax_rate", f"{self.tax_rate.value()/100:.4f}"),
            # Write both new and legacy keys so reads from either still work.
            ("non_cash_adjustment_rate", f"{self.card_rate.value()/100:.4f}"),
            ("cash_check_discount_rate", f"{self.cash_rate.value()/100:.4f}"),
            ("card_surcharge_rate", f"{self.card_rate.value()/100:.4f}"),
            ("cash_discount_rate", f"{self.cash_rate.value()/100:.4f}"),
            ("default_labor_rate", f"{self.labor_rate.value():.2f}"),
            ("inspection_fee", f"{self.inspection_fee.value():.2f}"),
            ("printer_name", self.cmb_printer.currentData() or ""),
            ("logo_path", self.logo_path_edit.text().strip()),
            ("review_url", self.review_url.text().strip()),
            ("review_cta", self.review_cta.text().strip() or "Scan to leave us a review"),
            ("update_url", self.update_url.text().strip()),
            ("update_on_startup",
             "1" if self.update_on_startup.isChecked() else "0"),
        ]
        for k, v in pairs:
            db.set_setting(self.conn, k, v)
        # Markup tiers
        if not self._save_tiers():
            return
        info(self, "Saved", "Settings saved.\n\nLabor rate and parts markup "
             "changes take effect on your next estimate or invoice (or click "
             "'Re-apply Markup to Parts' inside an open job).")

    def _save_tiers(self) -> bool:
        rows = []
        for r in range(self.tier_tbl.rowCount()):
            bt = (self.tier_tbl.item(r, 0).text() or "").strip() if self.tier_tbl.item(r, 0) else ""
            pt = (self.tier_tbl.item(r, 1).text() or "").strip() if self.tier_tbl.item(r, 1) else ""
            # strip any trailing '%' the user typed
            pt_clean = pt.rstrip("%").strip()
            try:
                pct = float(pt_clean)
            except ValueError:
                warn(self, "Markup tiers", f"Row {r+1}: profit % '{pt}' is not a number.")
                return False
            if pct < 0 or pct >= 100:
                warn(self, "Markup tiers",
                     f"Row {r+1}: profit % must be between 0 and 99.9.")
                return False
            mult = self._pct_to_mult(pct)
            if bt == "":
                upper = None
            else:
                try: upper = float(bt)
                except ValueError:
                    warn(self, "Markup tiers", f"Row {r+1}: cost band '{bt}' is not a number.")
                    return False
            rows.append((r + 1, upper, mult))
        if not rows:
            warn(self, "Markup tiers", "You need at least one tier."); return False
        # Must have exactly one open-ended tier (upper=None) at the end
        open_rows = [i for i, (_, u, _) in enumerate(rows) if u is None]
        if len(open_rows) != 1 or open_rows[0] != len(rows) - 1:
            warn(self, "Markup tiers",
                 "Exactly one row must have a blank cost band — the 'and up' tier — "
                 "and it must be the last row.")
            return False
        self.conn.execute("DELETE FROM markup_tiers")
        self.conn.executemany(
            "INSERT INTO markup_tiers(sort_order, upper_bound, multiplier) VALUES (?,?,?)",
            rows,
        )
        self.conn.commit()
        return True
