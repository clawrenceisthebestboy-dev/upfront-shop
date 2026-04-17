"""Up Front Shop — Windows entry point.

Launches the Qt app, opens (or creates) the SQLite DB, seeds defaults, and
shows the main window.

Run in dev: ``python main.py``
Packaged:   the PyInstaller build produces ``UpFrontShop.exe`` which calls
this same function.
"""
from __future__ import annotations
import sys
import traceback
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from app import db
from app.resources import resource_path
from app.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Up Front Shop")
    app.setOrganizationName("Up Front Auto Repair")

    # App-level icon: used in the Alt-Tab switcher, the Windows taskbar
    # (when grouped by app), and as a fallback for every child window.
    icon_path = resource_path("upfront_logo.png")
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))

    try:
        conn = db.connect()
        db.init_db(conn)
    except Exception as e:
        tb = traceback.format_exc()
        QMessageBox.critical(None, "Database error",
            f"Failed to open the shop database:\n\n{e}\n\n{tb}")
        return 2

    win = MainWindow(conn)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
