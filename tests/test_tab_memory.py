"""Each document tab remembers its side tab and thumbnail selection, and tabs can be reordered."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf as fitz
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from pdf_editor import recovery
from pdf_editor.app import EditorWindow, STYLE

APP = QApplication.instance() or QApplication([])
APP.setStyleSheet(STYLE)


@pytest.fixture
def window(tmp_path, monkeypatch):
    monkeypatch.setattr(recovery, "recovery_dir", lambda: tmp_path / "recovery")
    window = EditorWindow(QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    window.show()
    APP.processEvents()
    yield window
    for tab in window.documents:
        tab.engine.dirty = False
    window.close()
    APP.processEvents()


def make(path, pages):
    with fitz.open() as document:
        for number in range(pages):
            document.new_page().insert_text((72, 72), f"Page {number + 1}")
        document.save(path)
    return str(path)


def open_two(window, tmp_path):
    window.open_path(make(tmp_path / "a.pdf", 4))
    window.open_path(make(tmp_path / "b.pdf", 3))
    APP.processEvents()


def test_switching_tabs_restores_side_panel_and_selection(window, tmp_path):
    open_two(window, tmp_path)
    window.activate_tab(0)
    APP.processEvents()
    window.left_tabs.setCurrentIndex(window.side_tab_keys.index("links"))
    window.thumbnails.clearSelection()
    for row in (1, 2):
        window.thumbnails.item(row).setSelected(True)
    window.activate_tab(1)
    APP.processEvents()
    assert window.side_tab_keys[window.left_tabs.currentIndex()] == "pages"
    window.left_tabs.setCurrentIndex(window.side_tab_keys.index("bookmarks"))
    window.thumbnails.item(0).setSelected(True)
    window.activate_tab(0)
    APP.processEvents()
    assert window.side_tab_keys[window.left_tabs.currentIndex()] == "links"
    assert window.selected_pages() == [1, 2]
    window.activate_tab(1)
    APP.processEvents()
    assert window.side_tab_keys[window.left_tabs.currentIndex()] == "bookmarks"
    assert 0 in window.selected_pages()


def test_dragging_a_tab_reorders_documents(window, tmp_path):
    open_two(window, tmp_path)
    first, second = window.documents
    window.doc_tabs.moveTab(0, 1)
    APP.processEvents()
    assert window.documents == [second, first]
    assert window.doc_tabs.tabText(0).endswith("b.pdf")
    assert window.active_tab is second
