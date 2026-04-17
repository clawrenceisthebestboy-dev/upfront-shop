"""Windows printer glue.

The simplest, most reliable path on Windows is to generate a PDF (via ReportLab)
and then hand it off to the Windows print subsystem via Shell "print" verb or
via a PDF-aware app (SumatraPDF / Edge / Acrobat).

We try strategies in this order:
  1) SumatraPDF silent print (bundled fallback if present on PATH)
  2) Windows shell verb 'printto' with the chosen printer
  3) Windows shell verb 'print' to system default printer

On non-Windows, we no-op print and just open the PDF so dev/test works.
"""
from __future__ import annotations
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional


def list_printers() -> List[str]:
    """Return printer names known to Windows. Empty list off-Windows."""
    if os.name != "nt":
        return []
    try:
        import win32print  # type: ignore
        # PRINTER_ENUM_LOCAL = 2, PRINTER_ENUM_CONNECTIONS = 4
        infos = win32print.EnumPrinters(2 | 4)
        return sorted({info[2] for info in infos})
    except Exception:
        return []


def default_printer() -> Optional[str]:
    if os.name != "nt":
        return None
    try:
        import win32print  # type: ignore
        return win32print.GetDefaultPrinter()
    except Exception:
        return None


def print_pdf(pdf_path: str | Path, printer_name: Optional[str] = None) -> bool:
    """Send a PDF to the printer. Returns True on apparent success."""
    pdf_path = str(Path(pdf_path).resolve())

    if os.name != "nt":
        # Dev/test: just open it so the user can eyeball it.
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", pdf_path])
            else:
                subprocess.Popen(["xdg-open", pdf_path])
        except Exception:
            pass
        return True

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
        print(f"Print failed: {e}", file=sys.stderr)
        return False


def output_dir() -> Path:
    """Where invoice PDFs are written before printing."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", str(Path.home()))) / "UpFrontShop" / "invoices"
    else:
        base = Path.home() / ".upfront-shop" / "invoices"
    base.mkdir(parents=True, exist_ok=True)
    return base
