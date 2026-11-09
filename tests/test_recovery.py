"""Recovery copies, .bak backups, save copies, revert, cancellable jobs and the save-state indicator."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import pymupdf as fitz
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QProgressDialog

from pdf_editor import recovery
from pdf_editor.app import EditorWindow, STYLE
from pdf_editor.engine import PDFEngine
from pdf_editor.toast import banner_for
from pdf_editor.ui_support import CANCELLED

APP = QApplication.instance() or QApplication([])
APP.setStyleSheet(STYLE)
MARK = "Texto de recuperación"


@pytest.fixture
def root(tmp_path, monkeypatch):
    folder = tmp_path / "recovery"
    monkeypatch.setattr(recovery, "recovery_dir", lambda: folder)
    return tmp_path


@pytest.fixture
def make_window(root):
    windows = []

    def make(name="settings.ini"):
        window = EditorWindow(QSettings(str(root / name), QSettings.Format.IniFormat))
        window.show()
        windows.append(window)
        return window

    yield make
    for window in windows:
        for timer in (getattr(window, "autosave_timer", None), getattr(window, "state_timer", None)):
            if timer is not None:
                timer.stop()
        window.engine.dirty = False
        window.close()
        APP.processEvents()


def write_pdf(path, text="Original"):
    with fitz.open() as document:
        document.new_page().insert_text((72, 72), text)
        document.save(path)
    return Path(path)


def open_edited(window, root, name="doc.pdf"):
    original = write_pdf(root / name)
    window.open_path(str(original))
    window.engine.add_text(0, (50, 50, 350, 100), MARK)
    window.refresh()
    assert window.engine.dirty
    return original


def test_autosave_writes_copy_and_leaves_original_alone(make_window, root):
    window = make_window()
    original = open_edited(window, root)
    before = original.read_bytes()
    assert window.autosave_now() is True
    copies = list((root / "recovery").glob("*.pdf"))
    assert len(copies) == 1
    assert (root / "recovery" / copies[0].with_suffix(".json").name).is_file()
    with fitz.open(copies[0]) as saved:
        assert MARK in saved[0].get_text()
    assert original.read_bytes() == before
    assert "Autoguardado a las" in window.save_state_text()


def test_autosave_skips_clean_documents(make_window, root):
    window = make_window()
    window.new_file()
    assert window.autosave_now() is False
    assert not (root / "recovery").exists()


def test_saving_or_discarding_removes_the_copy(make_window, root):
    window = make_window()
    open_edited(window, root)
    window.autosave_now()
    assert any((root / "recovery").glob("*.pdf"))
    window.save()
    assert not any((root / "recovery").glob("*.pdf"))
    window.engine.add_text(0, (50, 150, 350, 200), "Otro")
    window.refresh()
    window.autosave_now()
    assert any((root / "recovery").glob("*.pdf"))
    with_discard = {"answer": "No guardar"}
    window.choose = lambda *a, **k: with_discard["answer"]
    assert window.confirm_discard() is True
    assert not any((root / "recovery").glob("*.pdf"))


def test_crash_leaves_copy_that_recovers_with_original_path(make_window, root):
    first = make_window("first.ini")
    first.start_recovery()
    original = open_edited(first, root)
    first.autosave_now()
    first.autosave_timer.stop()
    # The first window is never closed: that is the simulated crash.
    second = make_window("second.ini")
    entries = recovery.orphans()
    assert len(entries) == 1
    assert entries[0]["original"] == str(original.resolve())
    second.recovery_queue = entries
    assert second.recover_entry(entries[0]) is True
    assert second.has_doc()
    assert second.engine.dirty is True
    assert second.engine.path == str(original.resolve())
    assert MARK in second.engine.text(0)
    with fitz.open(original) as untouched:
        assert MARK not in untouched[0].get_text()


def test_discarding_a_recovery_entry_deletes_it(make_window, root):
    first = make_window("first.ini")
    first.start_recovery()
    open_edited(first, root)
    first.autosave_now()
    first.autosave_timer.stop()
    entry = recovery.orphans()[0]
    second = make_window("second.ini")
    second.recovery_queue = [entry]
    second.resolve_recovery(entry, False)
    assert recovery.orphans() == []


def test_protected_document_is_never_copied_in_clear(make_window, root):
    source = PDFEngine()
    source.doc[0].insert_text((72, 72), "Secreto")
    locked = root / "locked.pdf"
    source.protect(locked, "abrir", "propietario")
    source.close()
    window = make_window()
    window.engine.open(str(locked), "abrir")
    window.engine.add_text(0, (50, 50, 350, 100), MARK)
    window.refresh()
    # Only the open password is known: a copy would need encrypting with credentials we lack.
    assert recovery.recovery_bytes(window.engine) is None
    assert window.autosave_now() is False
    assert not (root / "recovery").exists() or not any((root / "recovery").glob("*.pdf"))
    assert window.autosave_warned is True
    assert window.engine.unlock_owner("propietario")
    data = recovery.recovery_bytes(window.engine)
    assert data is not None
    with fitz.open(stream=data, filetype="pdf") as copy:
        assert copy.needs_pass
    assert b"Secreto" not in data and MARK.encode() not in data


def test_backup_is_made_once_per_session_and_never_overwritten(make_window, root):
    window = make_window()
    original = open_edited(window, root)
    previous = original.read_bytes()
    window.save()
    backup = root / "doc.pdf.bak"
    assert backup.read_bytes() == previous
    window.engine.add_text(0, (50, 150, 350, 200), "Segundo")
    window.refresh()
    window.save()
    assert backup.read_bytes() == previous
    assert len(list(root.glob("doc.pdf*.bak"))) == 1


def test_existing_backup_gets_a_dated_name(root):
    target = write_pdf(root / "x.pdf")
    (root / "x.pdf.bak").write_bytes(b"antigua")
    created = recovery.make_backup(target)
    assert created != root / "x.pdf.bak"
    assert created.name.startswith("x.pdf.") and created.name.endswith(".bak")
    assert (root / "x.pdf.bak").read_bytes() == b"antigua"


def test_backup_can_be_turned_off(make_window, root):
    window = make_window()
    window.settings.setValue("backupOnSave", False)
    open_edited(window, root)
    window.save()
    assert not (root / "doc.pdf.bak").exists()


def test_save_copy_keeps_open_document_and_path(make_window, root, monkeypatch):
    window = make_window()
    original = open_edited(window, root)
    copy_target = root / "copia.pdf"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(copy_target), "PDF"))
    assert window.save_copy() is True
    with fitz.open(copy_target) as saved:
        assert MARK in saved[0].get_text()
    assert window.engine.path == str(original.resolve())
    assert window.engine.dirty is True


def test_save_copy_refuses_the_open_file(make_window, root, monkeypatch):
    window = make_window()
    original = open_edited(window, root)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(original), "PDF"))
    with pytest.raises(ValueError):
        window.save_copy()
    assert window.engine.dirty is True


def test_revert_reloads_saved_version_after_confirmation(make_window, root, monkeypatch):
    window = make_window()
    open_edited(window, root)
    window.save()
    window.engine.add_text(0, (50, 150, 350, 200), "Cambio no guardado")
    window.refresh()
    monkeypatch.setattr(window, "choose", lambda *a, **k: "Revertir")
    assert window.revert_document() is True
    assert window.engine.dirty is False
    assert "Cambio no guardado" not in window.engine.text(0)
    assert MARK in window.engine.text(0)


def test_revert_cancelled_keeps_changes(make_window, root, monkeypatch):
    window = make_window()
    open_edited(window, root)
    window.save()
    window.engine.add_text(0, (50, 150, 350, 200), "Cambio")
    window.refresh()
    monkeypatch.setattr(window, "choose", lambda *a, **k: None)
    assert window.revert_document() is False
    assert window.engine.dirty is True
    assert "Cambio" in window.engine.text(0)


def test_busy_returns_value_and_cancel_removes_partial_output(make_window, root):
    window = make_window()
    partial = root / "partial.pdf"
    finished = root / "finished.pdf"
    assert window.busy("Prueba", lambda: 42) == 42

    def work():
        PDFEngine._atomic_write(partial, b"%PDF-1.4 a medias")
        PDFEngine._atomic_write(finished, b"%PDF-1.4 completo")
        for _ in range(1000):
            time.sleep(0.01)

    def press_cancel():
        for dialog in window.findChildren(QProgressDialog):
            dialog.canceled.emit()

    QTimer.singleShot(300, press_cancel)
    started = time.monotonic()
    result = window.busy("Dividiendo", work)
    assert result is CANCELLED
    assert time.monotonic() - started < 8
    assert not partial.exists()
    assert not finished.exists()
    assert banner_for(window).label.text() == "Operación cancelada"


def test_busy_error_removes_files_it_created_and_reraises(make_window, root):
    window = make_window()
    made = root / "made.pdf"

    def work():
        PDFEngine._atomic_write(made, b"%PDF-1.4")
        raise ValueError("fallo a propósito")

    with pytest.raises(ValueError, match="fallo a propósito"):
        window.busy("Fallo", work)
    assert not made.exists()


def test_save_state_indicator_follows_document(make_window, root):
    window = make_window()
    window.start_recovery()
    window.autosave_timer.stop()
    window.state_timer.stop()
    original = open_edited(window, root)
    window.update_save_state()
    assert window.save_state_label.text() == "Sin guardar"
    window.save()
    window.update_save_state()
    assert window.save_state_label.text() == "Guardado"
    assert original.is_file()


def test_missing_recent_file_is_announced_and_can_be_dropped(make_window, root):
    window = make_window()
    gone = root / "no-existe.pdf"
    window.settings.setValue("recent", [str(gone.resolve())])
    window.open_path(str(gone))
    assert banner_for(window).label.text() == "No se encuentra no-existe.pdf"
    window.forget_recent(str(gone.resolve()))
    assert str(gone.resolve()) not in window.settings.value("recent", [], type=list)


def test_old_copies_are_purged(root):
    folder = root / "recovery"
    folder.mkdir(parents=True)
    identifier = "a" * 32
    (folder / f"{identifier}.pdf").write_bytes(b"%PDF")
    (folder / f"{identifier}.json").write_text('{"original": null, "name": "viejo.pdf"}', encoding="utf-8")
    old = (datetime.now() - timedelta(days=31)).timestamp()
    os.utime(folder / f"{identifier}.pdf", (old, old))
    assert recovery.orphans() == []
    assert not (folder / f"{identifier}.pdf").exists()
    assert not (folder / f"{identifier}.json").exists()
