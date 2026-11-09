"""Drag and drop of files onto the window and the per-file view memory (page, zoom, scroll)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf as fitz
import pytest
from PySide6.QtCore import QMimeData, QPointF, QSettings, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent, QPixmap
from PySide6.QtWidgets import QApplication

from pdf_editor.app import EditorWindow
from pdf_editor.theme import STYLE


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    instance.setStyle("Fusion")
    instance.setStyleSheet(STYLE)
    return instance


@pytest.fixture()
def window(app, tmp_path):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    win = EditorWindow(settings)
    win.resize(1024, 768)
    win.show()
    app.processEvents()
    yield win
    win.engine.dirty = False
    win.close()
    app.processEvents()


def make_pdf(path, count):
    doc = fitz.open()
    for index in range(count):
        doc.new_page(width=612, height=792).insert_text((72, 100), f"page {index}", fontsize=12)
    doc.save(str(path))
    doc.close()
    return str(path)


def make_image(path):
    pixmap = QPixmap(120, 80)
    pixmap.fill(Qt.GlobalColor.red)
    assert pixmap.save(str(path))
    return str(path)


def mime_for(paths):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    return mime


def drop(window, paths):
    mime = mime_for(paths)
    event = QDropEvent(QPointF(100, 100), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    window.dropEvent(event)
    QApplication.processEvents()


def test_overlay_shows_on_drag_enter_and_hides_on_leave_and_drop(window, tmp_path):
    path = make_pdf(tmp_path / "a.pdf", 1)
    mime = mime_for([path])
    window.dragEnterEvent(QDragEnterEvent(window.rect().center(), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    assert window.drop_overlay.isVisible()
    assert window.drop_overlay.text() == "Suelta para abrir"
    window.dragLeaveEvent(QDragLeaveEvent())
    assert not window.drop_overlay.isVisible()
    window.dragEnterEvent(QDragEnterEvent(window.rect().center(), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    drop(window, [path])
    assert not window.drop_overlay.isVisible()
    assert window.engine.page_count == 1


def test_two_pdfs_offer_a_choice_and_merge_sums_pages(window, tmp_path, monkeypatch):
    first, second = make_pdf(tmp_path / "a.pdf", 2), make_pdf(tmp_path / "b.pdf", 3)
    asked = []

    def choose(title, text, buttons, *args, **kwargs):
        asked.append(buttons)
        return "Combinar"

    monkeypatch.setattr(window, "choose", choose)
    drop(window, [first, second])
    assert asked and "Combinar" in asked[0] and "Abrir el primero" in asked[0]
    assert window.engine.page_count == 5
    assert window.engine.path is None


def test_two_pdfs_can_open_only_the_first(window, tmp_path, monkeypatch):
    first, second = make_pdf(tmp_path / "a.pdf", 2), make_pdf(tmp_path / "b.pdf", 3)
    monkeypatch.setattr(window, "choose", lambda *a, **k: "Abrir el primero")
    drop(window, [first, second])
    assert window.engine.page_count == 2
    assert os.path.samefile(window.engine.path, first)


def test_two_pdfs_cancel_changes_nothing(window, tmp_path, monkeypatch):
    first, second = make_pdf(tmp_path / "a.pdf", 2), make_pdf(tmp_path / "b.pdf", 3)
    monkeypatch.setattr(window, "choose", lambda *a, **k: None)
    drop(window, [first, second])
    assert not window.has_doc()


def test_single_pdf_opens_without_asking(window, tmp_path, monkeypatch):
    path = make_pdf(tmp_path / "a.pdf", 2)
    monkeypatch.setattr(window, "choose", lambda *a, **k: pytest.fail("no choice expected"))
    drop(window, [path])
    assert window.engine.page_count == 2


def test_image_dropped_on_a_document_adds_a_page(window, tmp_path):
    window.open_path(make_pdf(tmp_path / "a.pdf", 2))
    QApplication.processEvents()
    drop(window, [make_image(tmp_path / "pic.png")])
    assert window.engine.page_count == 3
    assert window.engine.dirty


def test_image_dropped_without_a_document_creates_one(window, tmp_path):
    drop(window, [make_image(tmp_path / "pic.png")])
    assert window.has_doc() and window.engine.page_count == 1


def open_continuous(window, path):
    window.set_view_layout("continuous")
    window.open_path(path)
    QApplication.processEvents()
    window.fit_locked_until = 0.0


def test_reopening_restores_page_zoom_and_scroll(window, tmp_path):
    first = make_pdf(tmp_path / "first.pdf", 6)
    other = make_pdf(tmp_path / "other.pdf", 1)
    open_continuous(window, first)
    window.set_zoom(150)
    QApplication.processEvents()
    bar = window.view.verticalScrollBar()
    bar.setValue(bar.maximum() // 2)
    QApplication.processEvents()
    window.continuous_view_moved()
    page, zoom, value = window.page, window.zoom.value(), bar.value()
    assert page > 0
    assert zoom == 150 and value > 0
    window.open_path(other)
    QApplication.processEvents()
    assert window.engine.page_count == 1
    window.open_path(first)
    QApplication.processEvents()
    assert window.zoom.value() == zoom
    assert abs(window.view.verticalScrollBar().value() - value) <= 1
    assert window.page == page


def test_view_memory_survives_a_new_window_with_the_same_settings(app, window, tmp_path):
    path = make_pdf(tmp_path / "first.pdf", 6)
    open_continuous(window, path)
    window.set_zoom(130)
    QApplication.processEvents()
    bar = window.view.verticalScrollBar()
    bar.setValue(bar.maximum() // 3)
    QApplication.processEvents()
    zoom, value = window.zoom.value(), bar.value()
    window.close_document()
    other = EditorWindow(window.settings)
    try:
        other.resize(1024, 768)
        other.show()
        app.processEvents()
        other.open_path(path)
        app.processEvents()
        assert other.zoom.value() == zoom
        assert abs(other.view.verticalScrollBar().value() - value) <= 1
    finally:
        other.engine.dirty = False
        other.close()


def test_view_memory_keeps_at_most_fifty_files(window, tmp_path):
    for index in range(53):
        window.settings.setValue("viewMemory", "{}")
    window.open_path(make_pdf(tmp_path / "x.pdf", 1))
    data = {str(tmp_path / f"f{n}.pdf"): {"page": 0, "zoom": 100, "mode": "manual", "scroll": [0, 0]} for n in range(55)}
    import json
    window.settings.setValue("viewMemory", json.dumps(data))
    window.remember_view()
    assert len(window.view_memory()) == 50
