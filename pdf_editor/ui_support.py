from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time

from PySide6.QtGui import QImage, QPixmap
from pathlib import Path
import pymupdf as fitz

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))

from . import __version__, doctools, doctools_dialogs, icons, theme
from .lang import _, N_
from .theme import STYLE

PAGE_MARGIN = 32          # blank space around the page inside the scene, in scene units
RAIL_WIDE = 240           # tool rail, expanded
RAIL_COMPACT = 56         # tool rail, icons only
JOB_PREFIXES = ("pdf-editor-job-", "pdf-editor-compare-")   # temporary folders of background jobs
JOB_MAX_AGE = 24 * 3600   # seconds before a leftover job folder is removed at start-up
CANCELLED = object()      # returned by guarded operations when the user backs out

# Icon for every tool, document action and toolbar action (see icons.py).
TOOL_ICONS = {
    "select": "select", "hand": "hand", "edit": "edit", "text": "text", "replace": "replace", "image": "image",
    "link": "link", "highlight": "highlight", "underline": "underline", "strikeout": "strikeout", "note": "note",
    "ink": "ink", "rectangle": "rectangle", "ellipse": "ellipse", "field": "field", "redact": "redact", "crop": "crop",
}
ACTION_ICONS = {
    "open": "open", "new": "new", "save": "save", "saveas": "save", "print": "print", "undo": "undo", "redo": "redo",
    "merge": "merge", "rotate": "rotate", "forms": "forms", "redactions": "redactions", "ocr": "ocr",
    "export": "export", "protect": "protect",
    "headerfooter": "header-footer", "bates": "bates", "redactsearch": "redact-search", "optimize": "optimize",
    "flatten": "flatten", "pagelabels": "page-labels", "insertpage": "insert-page", "stamp": "stamp",
    "check": "check", "comparetext": "compare-text",
}
# Rail groups made of document actions (the tool groups above are modes of the canvas).
RAIL_ACTION_GROUPS = [
    (N_("Documento"), ["merge", "rotate", "forms", "redactions", "ocr", "export", "protect"]),
    (N_("Herramientas"), ["headerfooter", "bates", "redactsearch", "optimize", "flatten", "pagelabels", "insertpage",
                      "stamp", "check", "comparetext"]),
]
THEME_CHOICES = [("system", N_("Sistema"), "monitor"), ("light", N_("Claro"), "sun"), ("dark", N_("Oscuro"), "moon")]


def pixmap_for(pix: fitz.Pixmap) -> QPixmap:
    if pix.n != 3:
        pix = fitz.Pixmap(fitz.csRGB, pix)
    image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888).copy()
    return QPixmap.fromImage(image)


OWNER_FILE = "owner.pid"   # inside a job folder: the PID of the editor instance that created it


def claim_job_folder(folder):
    """Mark a job folder as held by this process so other instances leave it alone."""
    try:
        (Path(folder) / OWNER_FILE).write_text(str(os.getpid()), encoding="ascii")
    except OSError:
        pass


def pid_runs_editor(pid):
    """True when pid is a live process that looks like this program (a Python or TrazoPDF executable)."""
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = wintypes.HANDLE
        handle = kernel.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            size = wintypes.DWORD(1024)
            buffer = ctypes.create_unicode_buffer(1024)
            if not kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return False
            name = Path(buffer.value).name.lower()
        finally:
            kernel.CloseHandle(handle)
        return "python" in name or "pdf" in name
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:
        name = Path(os.readlink(f"/proc/{pid}/exe")).name.lower()
    except OSError:
        return True
    return "python" in name or "pdf" in name


def purge_stale_jobs(folder=None, max_age=JOB_MAX_AGE, now=None):
    """Remove leftover job folders (crashed or killed runs). Returns the count.

    A folder naming its owner (OWNER_FILE) goes as soon as that process is no longer a running editor, whatever
    its age, because it may hold the plain copy of a protected document. Folders without an owner file go once
    they are older than max_age seconds.
    """
    root = Path(folder or tempfile.gettempdir())
    now = time.time() if now is None else now
    removed = 0
    try:
        entries = list(root.iterdir())
    except OSError:
        return 0
    for entry in entries:
        try:
            if not entry.name.startswith(JOB_PREFIXES) or entry.is_symlink() or not entry.is_dir():
                continue
            owner = entry / OWNER_FILE
            if owner.is_file() and not owner.is_symlink():
                try:
                    pid = int(owner.read_text(encoding="ascii").strip())
                except (OSError, ValueError):
                    pid = 0
                if pid and pid_runs_editor(pid):
                    continue
            elif now - entry.stat().st_mtime < max_age:
                continue
            shutil.rmtree(entry)
            removed += 1
        except OSError:
            continue
    return removed


def format_text_comparison(report, name_a, name_b):
    """Plain-text rendering of doctools.compare_text for the report dialog."""
    lines = [_("Comparación de texto"),
             _("Documento actual: {name} ({n} páginas)", name=name_a, n=report['pages_a']),
             _("Otro documento: {name} ({n} páginas)", name=name_b, n=report['pages_b']), "",
             _("«−» es texto que solo está en el documento actual; «+» es texto que solo está en el otro."), ""]
    if not report["changed_pages"]:
        lines.append(_("No hay diferencias de texto."))
        return "\n".join(lines)
    lines.append(_("{changed} de {total} páginas con diferencias · {removed} líneas quitadas · {added} añadidas",
                   changed=len(report['changed_pages']), total=report['total_pages'],
                   removed=report['removed'], added=report['added']))
    for entry in report["pages"]:
        if not entry["changed"]:
            continue
        lines += ["", _("Página {n}", n=entry['page'] + 1)]
        lines += [f"  − {text}" for text in entry["removed"]]
        lines += [f"  + {text}" for text in entry["added"]]
    return "\n".join(lines)
