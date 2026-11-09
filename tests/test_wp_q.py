from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymupdf as fitz
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from pdf_editor import icons
from pdf_editor.app import EditorWindow
from pdf_editor.theme import STYLE
from pdf_editor.ui_rail import MODE_ICONS


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    instance.setStyle("Fusion")
    instance.setStyleSheet(STYLE)
    return instance


@pytest.fixture()
def window(app):
    with tempfile.TemporaryDirectory(prefix="wp-q-", ignore_cleanup_errors=True) as folder:
        settings = QSettings(str(Path(folder) / "settings.ini"), QSettings.Format.IniFormat)
        win = EditorWindow(settings)
        win.resize(1100, 760)
        win.show()
        app.processEvents()
        win.new_file()
        app.processEvents()
        yield win
        win.engine.dirty = False
        win.close()
        win.engine.close()


def show(window, key):
    window.left_tabs.setCurrentWidget(window.side_panels[key])
    window.refresh_side_panel(True)


def test_comment_thread_reply_and_state(window):
    window.engine.annotate(0, fitz.Rect(50, 50, 150, 80), "note", "Revisar esto")
    show(window, "comments")
    assert "Revisar esto" in window.comment_list.item(0).text()
    window.reply_edit.setText("Hecho")
    window.side_comment_reply()
    assert "Hecho" in window.comment_list.item(0).text()
    assert window.reply_edit.text() == ""
    window.comment_state.setCurrentIndex(window.comment_state.findData("Accepted"))
    window.side_comment_state()
    assert "Estado: Aceptado" in window.comment_list.item(0).text()
    assert window.comment_list.count() == 1
    assert window.comment_state.currentData() == "Accepted"


def test_comment_click_goes_to_annotation(window):
    window.engine.annotate(0, fitz.Rect(50, 50, 150, 80), "note", "Aquí")
    show(window, "comments")
    window.side_comment_go()
    assert window.page == 0
    assert window.view.selected_annot is not None


def test_author_field_sets_author_without_dialog(window):
    show(window, "comments")
    window.author_edit.setText("Ana")
    window.author_edit.editingFinished.emit()
    assert window.engine.author == "Ana"
    assert window.settings.value("annotationAuthor") == "Ana"


def test_fields_and_properties_tabs(window):
    window.engine.add_field(0, fitz.Rect(60, 60, 200, 90), "nombre")
    show(window, "fields")
    assert "nombre" in window.field_list.item(0).text()
    window.side_field_go()
    assert window.page == 0
    show(window, "properties")
    texts = [window.property_list.item(i).text() for i in range(window.property_list.count())]
    assert any(t.startswith("Páginas") for t in texts)
    assert not window.property_list.item(0).flags() & window.property_list.item(0).flags().ItemIsEditable


def test_new_tool_icons_are_distinct(app):
    names = ("line", "arrow", "freetext")
    assert [MODE_ICONS[m] for m in names] == list(names)
    sources = {icons._GLYPHS[n] for n in names}
    assert len(sources) == 3 and icons._GLYPHS["ink"] not in sources and icons._GLYPHS["text"] not in sources
    for name in names:
        assert not icons.tinted_icon(name, "#000000").isNull()
