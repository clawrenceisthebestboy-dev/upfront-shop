"""Main window — wires every tab together, with a branded header banner."""
from __future__ import annotations
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QMainWindow, QTabWidget, QStatusBar, QLabel, QMessageBox,
    QWidget, QVBoxLayout, QHBoxLayout, QFrame,
)
from .. import db
from .jobs_tab import JobsTab
from .customers_tab import CustomersTab
from .inventory_tab import InventoryTab
from .timeclock_tab import TimeClockTab
from .reports_tab import ReportsTab
from .reminders_tab import RemindersTab
from .settings_tab import SettingsTab


APP_STYLESHEET = """
QMainWindow { background: #F2F4F8; }
QTabBar::tab {
    padding: 8px 16px; font-weight: bold;
    background: #E4E8EF; color: #0B2545;
    border: 1px solid #B3BCC9;
    border-top-left-radius: 4px; border-top-right-radius: 4px;
}
QTabBar::tab:selected { background: #0B2545; color: white; }
QTabBar::tab:hover:!selected { background: #D1D8E2; }
QGroupBox {
    font-weight: bold; color: #0B2545;
    border: 1px solid #B3BCC9; border-radius: 6px;
    margin-top: 10px; padding-top: 10px;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
QPushButton { padding: 5px 10px; }
#HeaderBanner { background: white; border-bottom: 2px solid #0B2545; }
#HeaderShopName { color: #0B2545; font-weight: bold; font-size: 22px; }
#HeaderTagline  { color: #C5363A; font-weight: bold; letter-spacing: 2px; font-size: 11px; }
#HeaderContact  { color: #0B2545; font-size: 12px; }
"""


class MainWindow(QMainWindow):
    def __init__(self, conn):
        super().__init__()
        self.conn = conn
        self.setWindowTitle(f"Up Front Shop  —  {db.get_setting(conn,'shop_name','Up Front Auto Repair')}")
        self.resize(1280, 860)
        self.setStyleSheet(APP_STYLESHEET)

        # Window icon from the same resolver the PDF uses
        logo_path = db.resolve_logo_path(conn)
        if logo_path:
            self.setWindowIcon(QIcon(logo_path))

        # -------- Central widget: header banner + tabs --------
        central = QWidget()
        cv = QVBoxLayout(central)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)
        cv.addWidget(self._build_header(logo_path))

        tabs = QTabWidget()
        tabs.setMovable(False)
        self.tab_jobs = JobsTab(conn)
        self.tab_customers = CustomersTab(conn)
        self.tab_inventory = InventoryTab(conn)
        self.tab_timeclock = TimeClockTab(conn)
        self.tab_reports = ReportsTab(conn)
        self.tab_reminders = RemindersTab(conn)
        self.tab_settings = SettingsTab(conn)
        tabs.addTab(self.tab_jobs, "Jobs / Invoices")
        tabs.addTab(self.tab_customers, "Customers")
        tabs.addTab(self.tab_inventory, "Inventory / Vendors")
        tabs.addTab(self.tab_timeclock, "Time Clock")
        tabs.addTab(self.tab_reports, "Reports")
        tabs.addTab(self.tab_reminders, "Reminders")
        tabs.addTab(self.tab_settings, "Settings")
        tabs.currentChanged.connect(self._on_tab_changed)
        self._tabs = tabs
        cv.addWidget(tabs, 1)

        self.setCentralWidget(central)

        self._build_menu()
        self._build_status_bar()

    # -------- Header banner (logo + shop name + phone) --------

    def _build_header(self, logo_path: str) -> QFrame:
        banner = QFrame()
        banner.setObjectName("HeaderBanner")
        banner.setMinimumHeight(90)
        banner.setMaximumHeight(110)
        h = QHBoxLayout(banner)
        h.setContentsMargins(14, 8, 14, 8)
        h.setSpacing(14)

        # Logo image on the left
        logo_lbl = QLabel()
        logo_lbl.setFixedSize(88, 88)
        logo_lbl.setAlignment(Qt.AlignCenter)
        if logo_path and Path(logo_path).is_file():
            pm = QPixmap(logo_path)
            if not pm.isNull():
                logo_lbl.setPixmap(
                    pm.scaled(88, 88, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
        h.addWidget(logo_lbl)

        # Shop name + tagline + phone in the middle
        mid = QVBoxLayout()
        mid.setSpacing(2)
        shop_name = db.get_setting(self.conn, "shop_name", "Up Front Auto Repair")
        name_lbl = QLabel(shop_name)
        name_lbl.setObjectName("HeaderShopName")
        mid.addWidget(name_lbl)
        tag_lbl = QLabel("INTEGRITY & QUALITY")
        tag_lbl.setObjectName("HeaderTagline")
        mid.addWidget(tag_lbl)
        mid.addStretch()
        h.addLayout(mid, 1)

        # Phone + address on the right
        right = QVBoxLayout()
        right.setSpacing(2)
        right.setAlignment(Qt.AlignRight)
        phone = db.get_setting(self.conn, "shop_phone", "")
        if phone:
            ph_lbl = QLabel(phone)
            ph_lbl.setObjectName("HeaderContact")
            ph_lbl.setAlignment(Qt.AlignRight)
            ph_font = QFont(); ph_font.setPointSize(14); ph_font.setBold(True)
            ph_lbl.setFont(ph_font)
            right.addWidget(ph_lbl)
        addr_parts = [
            db.get_setting(self.conn, "shop_address1", ""),
            f"{db.get_setting(self.conn, 'shop_city','')}, "
            f"{db.get_setting(self.conn, 'shop_state','')} "
            f"{db.get_setting(self.conn, 'shop_zip','')}".strip(", ").strip(),
        ]
        for a in addr_parts:
            if a and a.strip(", ").strip():
                lbl = QLabel(a)
                lbl.setObjectName("HeaderContact")
                lbl.setAlignment(Qt.AlignRight)
                right.addWidget(lbl)
        right.addStretch()
        h.addLayout(right)

        return banner

    def refresh_header(self):
        """Rebuild the header after a logo/shop-info change in Settings."""
        central = self.centralWidget()
        if central is None: return
        # Remove the old banner (first widget in the layout)
        layout = central.layout()
        old = layout.itemAt(0).widget()
        if old is not None:
            layout.removeWidget(old); old.setParent(None)
        layout.insertWidget(0, self._build_header(db.resolve_logo_path(self.conn)))

    # -------- Menu & status bar --------

    def _build_menu(self):
        bar = self.menuBar()
        file_m = bar.addMenu("&File")
        act_about = QAction("&About…", self); act_about.triggered.connect(self._about)
        act_quit = QAction("E&xit", self); act_quit.triggered.connect(self.close)
        file_m.addAction(act_about); file_m.addSeparator(); file_m.addAction(act_quit)

    def _build_status_bar(self):
        sb = QStatusBar(); self.setStatusBar(sb)
        path = db.default_db_path()
        sb.addPermanentWidget(QLabel(f"DB: {path}"))

    def _on_tab_changed(self, idx: int):
        # Refresh tabs that depend on current data whenever they become visible
        w = self._tabs.widget(idx)
        for method in ("refresh", "_load", "_show_preview"):
            if hasattr(w, method):
                try:
                    getattr(w, method)()
                except Exception:
                    pass
                break
        # If the settings tab was just closed, our header may be stale.
        if idx != self._tabs.indexOf(self.tab_settings):
            self.refresh_header()

    def _about(self):
        QMessageBox.about(self, "About Up Front Shop",
            "<h3>Up Front Shop</h3>"
            f"<p>Shop management for <b>{db.get_setting(self.conn,'shop_name','Up Front Auto Repair')}</b></p>"
            "<p>Built to replace QuickBooks for day-to-day estimates, invoices, "
            "inventory, time-clock, and monthly P&amp;L reporting.</p>"
            "<p>Cash-paid invoices are printed, marked PAID, then deleted from the "
            "database per shop policy. Keep the printed copy in the safe.</p>"
        )
