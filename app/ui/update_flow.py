"""Qt glue for the auto-updater.

Keeps the UI side (progress dialogs, confirmation prompts, error toasts)
in one place and the protocol/security side in ``app.updater``. Two
entry points:

  * :func:`check_for_updates_manual` — user clicked File → Check for
    updates…. Always surfaces a result (new version, up-to-date, or
    error).

  * :func:`check_for_updates_startup` — quiet check fired shortly after
    launch. Only surfaces a dialog if there IS a new version; swallows
    network / manifest errors silently so a flaky wifi connection
    doesn't nag the shop every morning.

Both paths share ``_confirm_and_install``, which runs the download
with a progress bar, verifies the sha256 (inside
:func:`download_installer`), and hands off to the silent Inno Setup
invocation in :func:`launch_installer_and_exit`. The app exits as
part of that hand-off; Inno re-launches it once the install finishes.
"""
from __future__ import annotations
import datetime as dt

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QMessageBox, QProgressDialog, QWidget,
)

from .. import db
from .. import APP_VERSION
from ..updater import (
    Manifest, UpdateError,
    fetch_manifest, download_installer, launch_installer_and_exit,
    is_newer, summarize_manifest,
)


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def check_for_updates_manual(parent: QWidget, conn) -> None:
    """File → Check for updates…: always tell the user what happened."""
    url = db.get_setting(conn, "update_url", "").strip()
    if not url:
        QMessageBox.information(
            parent, "Updates",
            "No update URL is configured.\n\n"
            "Set one in Settings → Updates, then try again.",
        )
        return

    try:
        m = _fetch_with_busy(parent, url, timeout=10)
    except UpdateError as e:
        QMessageBox.warning(
            parent, "Couldn't check for updates",
            f"{e}\n\n"
            "If this keeps happening, check Settings → Updates for a typo "
            "in the update URL, or that the shop laptop can reach the "
            "internet.",
        )
        return

    _record_last_checked(conn)

    if not is_newer(m.version):
        QMessageBox.information(
            parent, "Up to date",
            f"You're running the latest version (v{APP_VERSION}).",
        )
        return

    _prompt_and_install(parent, m)


def check_for_updates_startup(parent: QWidget, conn) -> None:
    """Quiet post-launch check — only speak up if there's a newer version."""
    if db.get_setting(conn, "update_on_startup", "1") != "1":
        return
    url = db.get_setting(conn, "update_url", "").strip()
    if not url:
        return

    try:
        m = fetch_manifest(url, timeout=6)
    except UpdateError:
        # No popup: the user didn't ask. We'll try again next launch.
        return

    _record_last_checked(conn)

    if not is_newer(m.version):
        return

    _prompt_and_install(parent, m)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _fetch_with_busy(parent: QWidget, url: str, timeout: int) -> Manifest:
    """Wrap the synchronous manifest fetch with a brief busy cursor."""
    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        return fetch_manifest(url, timeout=timeout)
    finally:
        QApplication.restoreOverrideCursor()


def _prompt_and_install(parent: QWidget, m: Manifest) -> None:
    """Show the "new version available" dialog; on Yes, run the installer."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Information)
    box.setWindowTitle("Update available")
    box.setText(summarize_manifest(m))
    box.setInformativeText(
        "Install now?\n\n"
        "The app will close while it installs, then re-open automatically. "
        "Your saved jobs, customers, and invoices are not affected."
    )
    btn_install = box.addButton("Install now", QMessageBox.AcceptRole)
    box.addButton("Later", QMessageBox.RejectRole)
    box.setDefaultButton(btn_install)
    box.exec()
    if box.clickedButton() is not btn_install:
        return

    _download_and_install(parent, m)


def _download_and_install(parent: QWidget, m: Manifest) -> None:
    dlg = QProgressDialog("Preparing download…", "Cancel", 0, 100, parent)
    dlg.setWindowTitle("Installing update")
    dlg.setWindowModality(Qt.WindowModal)
    dlg.setAutoClose(False)
    dlg.setAutoReset(False)
    dlg.setMinimumDuration(0)
    dlg.setValue(0)
    QApplication.processEvents()

    cancelled = {"flag": False}

    def cb(got: int, total: int) -> None:
        if dlg.wasCanceled():
            cancelled["flag"] = True
            # Raising here aborts download_installer cleanly — it deletes the
            # partial temp file and re-raises as UpdateError.
            raise UpdateError("Download cancelled by user.")
        if total > 0:
            pct = int(got * 100 / total)
            mb_got = got / (1024 * 1024)
            mb_tot = total / (1024 * 1024)
            dlg.setMaximum(100)
            dlg.setValue(pct)
            dlg.setLabelText(
                f"Downloading update… {mb_got:.1f} / {mb_tot:.1f} MB"
            )
        else:
            # Server didn't send Content-Length — show an indeterminate bar
            # by leaving max=0 (Qt convention).
            dlg.setMaximum(0)
            dlg.setLabelText(
                f"Downloading update… {got / (1024*1024):.1f} MB"
            )
        QApplication.processEvents()

    try:
        installer = download_installer(
            m.url, m.sha256, progress_cb=cb, timeout=600,
        )
    except UpdateError as e:
        dlg.close()
        if cancelled["flag"]:
            return  # User hit cancel; no need to nag.
        QMessageBox.warning(
            parent, "Download failed",
            f"{e}\n\n"
            "The update was NOT installed. You can try again later from "
            "File → Check for updates…",
        )
        return

    dlg.setLabelText("Launching installer…")
    dlg.setMaximum(100)
    dlg.setValue(100)
    QApplication.processEvents()

    try:
        # user_consent=True — the human explicitly clicked "Install now"
        # above. This is the only place we pass True.
        launch_installer_and_exit(installer, user_consent=True, silent=True)
    except UpdateError as e:
        dlg.close()
        QMessageBox.warning(
            parent, "Installer didn't start",
            f"{e}\n\n"
            f"The downloaded installer is here — you can double-click it "
            f"manually to finish:\n\n{installer}",
        )


def _record_last_checked(conn) -> None:
    """Stamp update_last_checked with now() in ISO format."""
    try:
        db.set_setting(
            conn, "update_last_checked",
            dt.datetime.now().isoformat(timespec="seconds"),
        )
    except Exception:
        # Informational only — never fail an update check because we
        # couldn't write a breadcrumb.
        pass
