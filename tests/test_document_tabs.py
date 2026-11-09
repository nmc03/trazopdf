"""Several documents open at once: tabs, independent state, modified marks, closing and recovery."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path

import pytest
import pymupdf as fitz
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from pdf_editor import recovery
from pdf_editor.app import EditorWindow, STYLE

APP = QApplication.instance() or QApplication([])
APP.setStyleSheet(STYLE)


@pytest.fixture
def root(tmp_path, monkeypatch):
    folder = tmp_path / "recovery"
    monkeypatch.setattr(recovery, "recovery_dir", lambda: folder)
    return tmp_path


@pytest.fixture
def window(root):
    window = EditorWindow(QSettings(str(root / "settings.ini"), QSettings.Format.IniFormat))
    window.show()
    APP.processEvents()
    yield window
    window.autosave_timer.stop() if hasattr(window, "autosave_timer") else None
    for tab in window.documents:
        tab.engine.dirty = False
    window.close()
    APP.processEvents()


def write_pdf(path, pages=1, text="Original"):
    with fitz.open() as document:
        for number in range(pages):
            document.new_page().insert_text((72, 72), f"{text} {number + 1}")
        document.save(path)
    return str(path)


def open_two(window, root):
    first = write_pdf(root / "uno.pdf", pages=4, text="Uno")
    second = write_pdf(root / "dos.pdf", pages=2, text="Dos")
    window.open_path(first)
    window.open_path(second)
    APP.processEvents()
    return first, second


def test_tab_bar_is_hidden_without_documents_and_listed_with_them(window, root):
    assert window.stack.currentIndex() == 0
    assert len(window.documents) == 0
    first, second = open_two(window, root)
    assert window.stack.currentIndex() == 1
    assert window.doc_tabs.count() == 2
    assert window.doc_tabs.tabToolTip(0) == str(Path(first).resolve())
    assert window.doc_tabs.tabText(1) == "dos.pdf"
    assert Path(window.engine.path).name == "dos.pdf"


def test_switching_tabs_keeps_the_state_of_each(window, root):
    open_two(window, root)
    window.activate_tab(0)
    window.goto(2)
    window.set_zoom_value(150)
    window.zoom_mode = "manual"
    window.render_page()
    window.activate_tab(1)
    assert Path(window.engine.path).name == "dos.pdf"
    assert window.page == 0
    window.goto(1)
    window.activate_tab(0)
    assert Path(window.engine.path).name == "uno.pdf"
    assert window.page == 2
    assert window.zoom.value() == 150
    assert window.zoom_mode == "manual"
    window.activate_tab(1)
    assert window.page == 1
    assert window.engine.page_count == 2


def test_each_tab_has_its_own_undo_history_and_modified_mark(window, root):
    open_two(window, root)
    window.activate_tab(0)
    window.engine.add_text(0, (50, 50, 350, 100), "Cambio")
    window.refresh()
    APP.processEvents()
    assert window.doc_tabs.tabText(0).startswith("● ")
    assert not window.doc_tabs.tabText(1).startswith("● ")
    assert window.engine.can_undo
    window.activate_tab(1)
    assert not window.engine.dirty
    assert not window.engine.can_undo


def test_opening_an_open_file_activates_its_tab(window, root):
    first, _ = open_two(window, root)
    window.open_path(first)
    assert len(window.documents) == 2
    assert window.doc_tabs.currentIndex() == 0
    assert Path(window.engine.path).name == "uno.pdf"


def test_closing_a_tab_only_asks_about_that_tab(window, root):
    open_two(window, root)
    window.activate_tab(0)
    window.engine.add_text(0, (50, 50, 350, 100), "Cambio")
    window.refresh()
    asked = []
    window.choose = lambda title, text, *a, **k: asked.append(text) or "No guardar"
    window.close_tab(window.documents[1])
    assert asked == []
    assert len(window.documents) == 1
    assert Path(window.engine.path).name == "uno.pdf"
    window.close_tab(window.documents[0])
    assert len(asked) == 1 and "uno.pdf" in asked[0]
    assert window.documents == []
    assert window.stack.currentIndex() == 0
    assert not window.has_doc()


def test_cancel_keeps_the_modified_tab(window, root):
    open_two(window, root)
    window.engine.add_text(0, (50, 50, 350, 100), "Cambio")
    window.refresh()
    window.choose = lambda *a, **k: None
    assert window.close_tab(window.active_tab) is False
    assert len(window.documents) == 2


def test_closing_the_app_walks_the_modified_tabs(window, root):
    open_two(window, root)
    window.activate_tab(0)
    window.engine.add_text(0, (50, 50, 350, 100), "Cambio")
    window.refresh()
    window.activate_tab(1)
    asked = []

    def answer(title, text, *a, **k):
        asked.append(text)
        return None

    window.choose = answer
    window.close()
    APP.processEvents()
    assert len(asked) == 1 and "uno.pdf" in asked[0]
    assert window.isVisible()
    assert len(window.documents) == 2
    window.choose = lambda *a, **k: "No guardar"
    window.close()
    APP.processEvents()
    assert not window.isVisible()


def test_shortcuts_step_and_jump_between_tabs(window, root):
    open_two(window, root)
    window.step_tab(1)
    assert window.doc_tabs.currentIndex() == 0
    window.step_tab(-1)
    assert window.doc_tabs.currentIndex() == 1
    window.jump_to_tab(1)
    assert window.doc_tabs.currentIndex() == 0
    window.jump_to_tab(9)
    assert window.doc_tabs.currentIndex() == 1


def test_recovery_writes_one_copy_per_modified_document(window, root):
    open_two(window, root)
    for index in (0, 1):
        window.activate_tab(index)
        window.engine.add_text(0, (50, 50, 350, 100), f"Cambio {index}")
        window.refresh()
    assert window.autosave_now() is True
    copies = sorted((root / "recovery").glob("*.pdf"))
    assert len(copies) == 2
    assert window.documents[0].recovery_id != window.documents[1].recovery_id
    names = {recovery.orphans()[i]["name"] for i in range(2)}
    assert names == {"uno.pdf", "dos.pdf"}
    window.activate_tab(0)
    window.choose = lambda *a, **k: "No guardar"
    window.close_tab(window.active_tab)
    assert len(list((root / "recovery").glob("*.pdf"))) == 1


def test_new_document_opens_in_its_own_tab(window, root):
    open_two(window, root)
    window.new_file()
    assert len(window.documents) == 3
    assert window.engine.path is None
    assert window.doc_tabs.tabText(2) == "Sin título"
