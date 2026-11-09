from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymupdf as fitz
import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
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
def window(app):
    with tempfile.TemporaryDirectory(prefix="wp-j-", ignore_cleanup_errors=True) as folder:
        settings = QSettings(str(Path(folder) / "settings.ini"), QSettings.Format.IniFormat)
        win = EditorWindow(settings)
        win.resize(1100, 800)
        win.show()
        doc = fitz.open()
        for number in range(30):
            doc.new_page().insert_text((72, 100), f"Page {number + 1} sample text", fontsize=14)
        path = Path(folder) / "thirty.pdf"
        doc.save(path)
        doc.close()
        win.open_path(str(path))
        app.processEvents()
        yield win
        win.engine.dirty = False
        win.close()
        win.engine.close()
        app.processEvents()


def test_switching_tools_does_not_render_the_page(window):
    with patch.object(type(window), "render_page") as render, patch.object(window.engine, "render", wraps=window.engine.render) as raster:
        for mode in ("select", "edit", "text", "hand", "highlight", "select"):
            window.set_mode(mode)
        assert render.call_count == 0
        assert raster.call_count == 0
    assert window.view.mode == "select"


def test_overlays_follow_the_tool(window):
    window.set_mode("edit")
    assert window.view.layer_items
    window.set_mode("hand")
    assert not window.view.layer_items


def test_change_keeps_thumbnail_items_and_current_row(window, app):
    window.goto(4)
    for _ in range(40):
        window.load_thumbnails()
        app.processEvents()
    thumbs = window.thumbnails
    items = [thumbs.item(i) for i in range(thumbs.count())]
    loaded = [i for i, item in enumerate(items) if not item.icon().isNull()]
    assert len(loaded) > 3
    window.change(lambda: window.engine.annotate(4, fitz.Rect(70, 80, 200, 110), "highlight"))
    assert [thumbs.item(i) for i in range(thumbs.count())] == items
    assert thumbs.currentRow() == 4
    for i in loaded:
        if i != 4:
            assert not thumbs.item(i).icon().isNull()
    assert thumbs.item(4).icon().isNull()


def test_change_keeps_scroll_position(window, app):
    window.set_zoom_value(300)
    app.processEvents()
    window.view.verticalScrollBar().setValue(window.view.verticalScrollBar().maximum() // 2)
    window.view.horizontalScrollBar().setValue(window.view.horizontalScrollBar().maximum() // 2)
    before = (window.view.horizontalScrollBar().value(), window.view.verticalScrollBar().value())
    assert before[1] > 0
    window.change(lambda: window.engine.annotate(0, fitz.Rect(70, 80, 200, 110), "highlight"))
    assert (window.view.horizontalScrollBar().value(), window.view.verticalScrollBar().value()) == before


def test_temporary_message_survives_page_change(window, app):
    window.statusBar().showMessage("Guardado: informe.pdf")
    window.goto(3)
    window.render_page()
    assert window.statusBar().currentMessage() == "Guardado: informe.pdf"
    assert "Página 4 de 30" in window.page_status.text()


def test_temporary_message_expires(window):
    window.statusBar().showMessage("Cancelado")
    assert 3000 <= window.statusBar().MESSAGE_MS <= 6000


def test_dragging_with_select_tool_leaves_clipboard_alone(window, app):
    QApplication.clipboard().setText("previo")
    window.set_mode("select")
    chars = [c for c in window.view.chars if c[1] is not None]
    start, end = chars[0][1], chars[-1][1]
    view = window.view
    scale = view.scale_factor
    a = view.mapFromScene(view.page_offset.x() + (start.x0 + .1) * scale, view.page_offset.y() + (start.y0 + start.y1) / 2 * scale)
    b = view.mapFromScene(view.page_offset.x() + (end.x1 - .1) * scale, view.page_offset.y() + (end.y0 + end.y1) / 2 * scale)
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, a)
    QTest.mouseMove(view.viewport(), b)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, b)
    assert view.selected_text
    assert QApplication.clipboard().text() == "previo"
    window.perform_selection("select", fitz.Rect(60, 80, 300, 110), fitz.Point(60, 80), False, [])
    assert QApplication.clipboard().text() == "previo"
    QTest.keyClick(view.viewport(), Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert QApplication.clipboard().text() == view.selected_text
