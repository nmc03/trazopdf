import time
from datetime import date, timedelta

import pymupdf as fitz
import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QFrame

from pdf_editor import ui_menu
from pdf_editor.ui_menu import recent_thumb_path, relative_day, render_recent_thumb


@pytest.fixture
def window(tmp_path, monkeypatch):
    from pdf_editor.app import EditorWindow
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(ui_menu, "recent_thumb_path", lambda path: tmp_path / "cache" / (str(abs(hash(path))) + ".png") if __import__("pathlib").Path(path).is_file() else None)
    w = EditorWindow(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
    yield w
    w.engine.dirty = False
    w.close()


def make_pdf(path, password=None):
    doc = fitz.open()
    doc.new_page().insert_text((72, 100), "Hola", fontsize=12)
    if password:
        doc.save(str(path), encryption=fitz.PDF_ENCRYPT_AES_256, user_pw=password, owner_pw=password)
    else:
        doc.save(str(path))
    doc.close()


def test_relative_day_labels():
    today = date(2026, 10, 29)
    stamp = lambda d: time.mktime((d.year, d.month, d.day, 12, 0, 0, 0, 0, -1))
    assert relative_day(stamp(today), today) == "hoy"
    assert relative_day(stamp(today - timedelta(days=1)), today) == "ayer"
    assert relative_day(stamp(today - timedelta(days=5)), today) == "24/10/2026"
    assert relative_day(None) == ""


def test_remember_recent_stores_last_use_and_menu_shows_it(window, tmp_path):
    pdf = tmp_path / "docs" / "uno.pdf"
    pdf.parent.mkdir()
    make_pdf(pdf)
    window.remember_recent(str(pdf))
    assert str(pdf.resolve()) in window.recent_used()
    window.fill_recent_menu()
    label = [a.text() for a in window.recent_submenu.actions() if a.text().startswith("uno.pdf")][0]
    assert "hoy" in label and "docs" in label
    window.fill_recents()
    assert window.recents.item(0).data(Qt.ItemDataRole.UserRole + 1) == "hoy"


def test_thumbnail_is_rendered_and_encrypted_or_missing_are_skipped(tmp_path):
    plain, locked = tmp_path / "a.pdf", tmp_path / "b.pdf"
    make_pdf(plain)
    make_pdf(locked, "clave")
    assert render_recent_thumb(str(plain), tmp_path / "t" / "a.png") and (tmp_path / "t" / "a.png").is_file()
    assert not render_recent_thumb(str(locked), tmp_path / "t" / "b.png")
    assert not render_recent_thumb(str(tmp_path / "no.pdf"), tmp_path / "t" / "c.png")
    assert recent_thumb_path(str(tmp_path / "no.pdf")) is None
    assert recent_thumb_path(str(plain)).suffix == ".png"


def test_status_history_keeps_last_20_and_popup_is_not_modal(window):
    bar = window.statusBar()
    for index in range(25):
        bar.showMessage(f"mensaje {index}")
    assert len(bar.history) == 20 and bar.history[-1][1] == "mensaje 24" and bar.history[0][1] == "mensaje 5"
    popup = window.show_message_history()
    assert isinstance(popup, QFrame) and popup.isVisible() and not popup.isModal()
    popup.close()
    entry = [a for a in window.menuBar().actions() if a.text() == "Ver"][0].menu()
    assert "Historial de mensajes" in [a.text() for a in entry.actions()]
