"""Recovery copies of unsaved documents, and the .bak copies made before a file is overwritten."""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QStandardPaths

from . import __version__
from .engine import PDFEngine
from .lang import _

MAX_AGE = timedelta(days=30)
IDENTIFIER = re.compile(r"[0-9a-f]{32}")


def recovery_dir():
    return Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)) / "recovery"


def recovery_bytes(engine):
    """Bytes of a recovery copy of the open document, or None when it must not be written.

    A protected document is copied only with its own credentials. If either one is
    unknown the copy would be clear text, so nothing is written.
    """
    if engine.is_protected:
        security = engine._security
        if security["user"] is None or security["owner"] is None:
            return None
    return engine.copy_bytes(allow_pending_redactions=True)


def write_copy(identifier, data, *, original, name, protected):
    if not IDENTIFIER.fullmatch(identifier):
        raise ValueError(_("Identificador de recuperación no válido."))
    folder = recovery_dir()
    folder.mkdir(parents=True, exist_ok=True)
    meta = {"original": original, "name": name, "saved_at": datetime.now().isoformat(timespec="seconds"),
            "engine": __version__, "protected": bool(protected)}
    PDFEngine._atomic_write(folder / f"{identifier}.pdf", data)
    PDFEngine._atomic_write(folder / f"{identifier}.json", json.dumps(meta, ensure_ascii=False).encode("utf-8"))


def discard(identifier):
    """Delete a recovery copy. Missing or invalid identifiers are ignored."""
    if not identifier or not IDENTIFIER.fullmatch(identifier):
        return
    for suffix in (".pdf", ".json"):
        try:
            (recovery_dir() / (identifier + suffix)).unlink()
        except OSError:
            pass


def orphans(now=None):
    """Recovery copies left by earlier sessions, newest first. Copies older than MAX_AGE are purged."""
    folder = recovery_dir()
    if not folder.is_dir():
        return []
    now = time.time() if now is None else now
    found = []
    for meta_path in folder.glob("*.json"):
        identifier = meta_path.stem
        pdf_path = meta_path.with_suffix(".pdf")
        if not IDENTIFIER.fullmatch(identifier):
            continue
        if not pdf_path.is_file():
            discard(identifier)
            continue
        if now - os.path.getmtime(pdf_path) > MAX_AGE.total_seconds():
            discard(identifier)
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = {}
        found.append({**meta, "id": identifier, "pdf": str(pdf_path)})
    found.sort(key=lambda entry: str(entry.get("saved_at", "")), reverse=True)
    return found


def backup_path(path, now=None):
    """Name for a .bak copy of path that never replaces an earlier backup."""
    path = Path(path)
    first = path.with_name(path.name + ".bak")
    if not first.exists():
        return first
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    candidate = path.with_name(f"{path.name}.{stamp}.bak")
    counter = 2
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.{stamp}-{counter}.bak")
        counter += 1
    return candidate


def make_backup(path):
    """Copy the file about to be overwritten. Returns the backup path, or None when there is no file yet."""
    path = Path(path)
    if not path.is_file():
        return None
    target = backup_path(path)
    shutil.copy2(path, target)
    return target
