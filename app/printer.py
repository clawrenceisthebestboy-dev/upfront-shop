"""Printer glue — Windows, macOS, Linux.

The simplest, most reliable path on any OS is to generate a PDF (via ReportLab)
and hand it off to the system print subsystem.

Windows strategies (in order):
  1) SumatraPDF silent print (if present on PATH)
  2) Windows shell verb 'printto' with the chosen printer
  3) Windows shell verb 'print' to system default printer

macOS strategy:
  1) `lpr -P <printer>` (CUPS). Printer list comes from `lpstat -p -d`.

Linux strategy:
  1) `lpr -P <printer>` (CUPS). Same approach as macOS.

If printing fails on non-Windows, we fall back to opening the PDF so the user
can trigger Print from Preview (Cmd+P).
"""
from __future__ import annotations
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional


# ----- printer discovery -------------------------------------------------

def _list_cups_printers() -> List[str]:
    """Parse `lpstat -p` to return CUPS printer names. Works on macOS + Linux."""
    if not shutil.which("lpstat"):
        return []
    try:
        out = subprocess.check_output(
            ["lpstat", "-p"], stderr=subprocess.DEVNULL, timeout=5
        ).decode("utf-8", errors="replace")
    except Exception:
        return []
    names: List[str] = []
    for line in out.splitlines():
        # Lines look like: "printer Brother_MFC_L2710DW is idle.  enabled since ..."
        m = re.match(r"^\s*printer\s+(\S+)\s+is\s+", line)
        if m:
            names.append(m.group(1))
    return sorted(set(names))


def _default_cups_printer() -> Optional[str]:
    if not shutil.which("lpstat"):
        return None
    try:
        out = subprocess.check_output(
            ["lpstat", "-d"], stderr=subprocess.DEVNULL, timeout=5
        ).decode("utf-8", errors="replace").strip()
    except Exception:
        return None
    # "system default destination: Brother_MFC_L2710DW"  or  "no system default destination"
    m = re.search(r"system default destination:\s*(\S+)", out)
    return m.group(1) if m else None


def list_printers() -> List[str]:
    """Return all printer names visible to the OS."""
    if os.name == "nt":
        try:
            import win32print  # type: ignore
            # PRINTER_ENUM_LOCAL = 2, PRINTER_ENUM_CONNECTIONS = 4
            infos = win32print.EnumPrinters(2 | 4)
            return sorted({info[2] for info in infos})
        except Exception:
            return []
    # macOS + Linux: CUPS
    return _list_cups_printers()


def default_printer() -> Optional[str]:
    if os.name == "nt":
        try:
            import win32print  # type: ignore
            return win32print.GetDefaultPrinter()
        except Exception:
            return None
    return _default_cups_printer()


# ----- printing ----------------------------------------------------------

def _open_for_manual_print(pdf_path: str) -> None:
    """Fallback: open the PDF so the user can Cmd+P / Ctrl+P it themselves."""
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", pdf_path])
        else:
            subprocess.Popen(["xdg-open", pdf_path])
    except Exception:
        pass


def _print_via_lpr(pdf_path: str, printer_name: Optional[str]) -> bool:
    """CUPS path for macOS / Linux."""
    lpr = shutil.which("lpr")
    if not lpr:
        return False
    args = [lpr]
    if printer_name:
        args += ["-P", printer_name]
    args.append(pdf_path)
    try:
        subprocess.run(args, check=True, timeout=60)
        return True
    except Exception as e:
        print(f"lpr print failed: {e}", file=sys.stderr)
        return False


def print_pdf(pdf_path: str | Path, printer_name: Optional[str] = None) -> bool:
    """Send a PDF to the printer. Returns True on apparent success."""
    pdf_path = str(Path(pdf_path).resolve())

    if os.name == "nt":
        # Strategy 1: SumatraPDF silent
        sumatra = shutil.which("SumatraPDF.exe") or shutil.which("SumatraPDF-3.5.2-64.exe")
        if sumatra:
            args = [sumatra, "-silent", "-print-to",
                    printer_name or (default_printer() or ""),
                    pdf_path]
            args = [a for a in args if a]
            try:
                subprocess.run(args, check=True, timeout=60)
                return True
            except Exception:
                pass

        # Strategy 2/3: Windows shell verb
        try:
            import win32api  # type: ignore
            if printer_name:
                win32api.ShellExecute(0, "printto", pdf_path, f'"{printer_name}"', ".", 0)
            else:
                win32api.ShellExecute(0, "print", pdf_path, None, ".", 0)
            return True
        except Exception as e:
            print(f"Windows print failed: {e}", file=sys.stderr)
            return False

    # macOS + Linux: try CUPS first, then fall back to opening the PDF.
    if _print_via_lpr(pdf_path, printer_name):
        return True
    _open_for_manual_print(pdf_path)
    # Return True because we showed the user the PDF — they can still print it.
    return True


def output_dir() -> Path:
    """Where invoice PDFs are written before printing."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", str(Path.home()))) / "UpFrontShop" / "invoices"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "UpFrontShop" / "invoices"
    else:
        base = Path.home() / ".upfront-shop" / "invoices"
    base.mkdir(parents=True, exist_ok=True)
    return base
