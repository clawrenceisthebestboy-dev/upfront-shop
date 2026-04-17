"""Main window — wires every tab together."""
from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QFont, QIcon
from PySide6.QtWidgets import (
    QMainWindow, QTabWidget, QStatusBar, QLabel, QMessageBox,
)
from .. import db
from ..resources import resource_path
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
"""


class MainWindow(QMainWindow):
    def __init__(self, conn):
        super().__init__()
        self.conn = conn
        self.setWindowTitle(f"Up Front Shop  —  {db.get_setting(conn,'shop_name','Up Front Auto Repair')}")
        # Window icon for the title bar + Windows taskbar preview. QApplication
        # already has an app-wide icon set in main.py; this overrides per-window
        # so dialogs launched from MainWindow inherit a sensible default too.
        icon_path = resource_path("upfront_logo.png")
        if icon_path.is_file():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.resize(1280, 820)
        self.setStyleSheet(APP_STYLESHEET)

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
        self.setCentralWidget(tabs)

        self._build_menu()
        self._build_status_bar()

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
        w = self.centralWidget().widget(idx)
        for method in ("refresh", "_load", "_show_preview"):
            if hasattr(w, method):
                try:
                    getattr(w, method)()
                except Exception:
                    pass
                break

    def _about(self):
        QMessageBox.about(self, "About Up Front Shop",
            "<h3>Up Front Shop</h3>"
            f"<p>Shop management for <b>{db.get_setting(self.conn,'shop_name','Up Front Auto Repair')}</b></p>"
            "<p>Built to replace QuickBooks for day-to-day estimates, invoices, "
            "inventory, time-clock, and monthly P&amp;L reporting.</p>"
            "<p>Cash-paid invoices are printed, marked PAID, then deleted from the "
            "database per shop policy. Keep the printed copy in the safe.</p>"
        )
