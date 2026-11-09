"""Continuous and two-page views: selection across pages, form fields on any visible page, auto-field overlay."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf as fitz
import pytest
from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from pdf_editor import autofields
from pdf_editor.app import EditorWindow
from pdf_editor.theme import STYLE

FIELD_RECT = (72, 150, 260, 172)


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    instance.setStyle("Fusion")
    instance.setStyleSheet(STYLE)
    return instance


@pytest.fixture()
def window(app, tmp_path):
    win = EditorWindow(QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    win.resize(1024, 900)
    win.show()
    app.processEvents()
    path = tmp_path / "three.pdf"
    doc = fitz.open()
    for text in ("Alpha first page", "Bravo second page", "Charlie third page"):
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 100), text, fontsize=12)
    widget = fitz.Widget()
    widget.field_name = "nombre"
    widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    widget.rect = fitz.Rect(*FIELD_RECT)
    widget.field_value = ""
    doc[1].add_widget(widget)
    doc.save(str(path))
    doc.close()
    win.open_path(str(path))
    app.processEvents()
    win.fit_locked_until = 0.0
    yield win
    win.view.cancel_editor()
    win.engine.dirty = False
    win.close()
    app.processEvents()


def go_continuous(window, layout="continuous", zoom=40):
    window.view_actions[layout].trigger()
    window.zoom.setValue(zoom)
    QApplication.processEvents()
    for _ in range(3):
        QTest.qWait(40)
        window.continuous_view_moved()
        QApplication.processEvents()


def viewport_point(window, page, x, y):
    view = window.view
    return view.mapFromScene(view.scene_point(fitz.Point(x, y), page))


def drag(window, start, end):
    viewport = window.view.viewport()
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    middle = QPoint((start.x() + end.x()) // 2, (start.y() + end.y()) // 2)
    QTest.mouseMove(viewport, middle)
    QTest.mouseMove(viewport, end)
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
    QApplication.processEvents()


def test_drag_from_page_one_to_two_selects_text_of_both(window):
    go_continuous(window)
    window.set_mode("select")
    drag(window, viewport_point(window, 0, 60, 98), viewport_point(window, 1, 200, 98))
    text = window.view.selected_text
    assert "Alpha" in text and "Bravo" in text and "Charlie" not in text
    window.view.format_action("copy")
    assert "Alpha" in QGuiApplication.clipboard().text() and "Bravo" in QGuiApplication.clipboard().text()


def test_selection_survives_the_current_page_changing(window):
    go_continuous(window)
    window.set_mode("select")
    drag(window, viewport_point(window, 0, 60, 98), viewport_point(window, 1, 200, 98))
    window.view.set_current_page(1)
    assert "Alpha" in window.view.selected_text and "Bravo" in window.view.selected_text


def test_field_on_page_two_is_filled_without_changing_page(window):
    go_continuous(window)
    window.set_mode("select")
    assert window.page == 0
    QTest.mouseClick(window.view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, viewport_point(window, 1, 100, 160))
    QApplication.processEvents()
    editor = window.view.editor
    assert editor is not None and editor.field[0] == 1
    editor.setPlainText("Ada Lovelace")
    assert window.view.commit_editor()
    QApplication.processEvents()
    assert window.page == 0
    values = {f["name"]: f["value"] for f in window.engine.forms()}
    assert values["nombre"] == "Ada Lovelace"


def test_two_page_view_fills_field_of_the_companion_page(window):
    window.view_actions["double"].trigger()
    window.zoom.setValue(40)
    QApplication.processEvents()
    window.set_mode("select")
    window.goto(0)
    QApplication.processEvents()
    assert window.view.companion_rects
    QTest.mouseClick(window.view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, viewport_point(window, 1, 100, 160))
    QApplication.processEvents()
    assert window.page == 0
    assert window.view.editor is not None and window.view.editor.field[0] == 1


def test_overlay_of_candidates_is_painted_on_page_two(window):
    go_continuous(window)
    region = window.view.mapFromScene(window.view.scene_rect((72, 300, 300, 340), 1)).boundingRect()
    before = window.view.viewport().grab(region).toImage()
    candidates = [{"page": 1, "rect": (72, 300, 300, 340), "kind": "text", "name": "Campo 1", "accepted": True}]
    panel = autofields.DetectorPanel(window, candidates)
    window.detector = panel
    QApplication.processEvents()
    after = window.view.viewport().grab(region).toImage()
    assert panel.items
    assert before != after
    panel.close_panel()
