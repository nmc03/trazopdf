from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymupdf as fitz
import pytest
from PySide6.QtCore import QPointF, QSettings
from PySide6.QtWidgets import QApplication

from pdf_editor.app import EditorWindow
from pdf_editor.engine import PDFEngine
from pdf_editor.theme import STYLE


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    instance.setStyle("Fusion")
    instance.setStyleSheet(STYLE)
    return instance


@pytest.fixture()
def window(app):
    with tempfile.TemporaryDirectory(prefix="wp-m-", ignore_cleanup_errors=True) as folder:
        settings = QSettings(str(Path(folder) / "settings.ini"), QSettings.Format.IniFormat)
        win = EditorWindow(settings)
        win.resize(1024, 768)
        win.show()
        app.processEvents()
        win.new_file()
        app.processEvents()
        yield win
        win.engine.dirty = False
        win.close()
        win.engine.close()


@pytest.fixture()
def engine():
    eng = PDFEngine()
    doc = fitz.open()
    doc.new_page()
    eng.doc = doc
    yield eng
    doc.close()


_pages = []


def annots(eng):
    page = eng.doc[0]
    _pages[:] = [page]
    return list(page.annots() or ())


def test_line_arrow_and_freetext_are_read_back_with_the_author(engine):
    engine.author = "Marta"
    line = engine.add_line(0, (50, 50), (200, 120), color=(1, 0, 0), width=3)
    arrow = engine.add_line(0, (50, 150), (200, 150), arrow=True)
    text = engine.add_freetext(0, (50, 200, 250, 260), "Revisar esto")
    found = {a.xref: a for a in annots(engine)}
    assert found[line].type[1] == "Line" and found[line].line_ends[1] == fitz.PDF_ANNOT_LE_NONE
    assert found[arrow].type[1] == "Line" and found[arrow].line_ends[1] != fitz.PDF_ANNOT_LE_NONE
    assert found[text].type[1] == "FreeText" and found[text].info["content"] == "Revisar esto"
    assert {a.info["title"] for a in found.values()} == {"Marta"}
    listed = {a["xref"]: a for a in engine.annotations(0)}
    assert listed[arrow]["arrow"] and not listed[line]["arrow"] and listed[text]["type"] == "FreeText"


def test_every_new_annotation_gets_the_system_user_by_default(engine):
    import getpass
    engine.annotate(0, (10, 10, 80, 60), "rectangle")
    engine.add_ink(0, [(10, 100), (60, 130)])
    assert {a.info["title"] for a in annots(engine)} == {getpass.getuser()}


def test_reply_is_linked_to_its_note_and_state_is_kept(engine):
    note = engine.annotate(0, (100, 100, 120, 120), "note", "Pregunta")
    reply = engine.add_reply(0, note, "Respuesta")
    page = engine.doc[0]
    assert page.load_annot(reply).irt_xref == note
    assert engine.annotation_replies(0, note) == {"replies": [{"xref": reply, "author": engine.author, "content": "Respuesta"}], "state": "None"}
    engine.set_annotation_state(0, note, "Accepted")
    engine.set_annotation_state(0, note, "Completed")
    assert engine.annotation_replies(0, note)["state"] == "Completed"
    engine.set_annotation_state(0, note, "None")
    assert engine.annotation_replies(0, note)["state"] == "None"
    assert [a["xref"] for a in engine.annotations(0)] == [note]
    with pytest.raises(ValueError):
        engine.set_annotation_state(0, note, "Otro")


def test_line_needs_a_real_drag(engine):
    with pytest.raises(ValueError):
        engine.add_line(0, (10, 10), (10, 11))


def test_tools_create_annotations_from_the_canvas(window):
    view = window.view
    window.set_mode("line")
    view.last_drag = (fitz.Point(60, 60), fitz.Point(220, 140))
    window.perform_selection("line", fitz.Rect(60, 60, 220, 140), fitz.Point(60, 60), False, [])
    window.set_mode("arrow")
    view.last_drag = (fitz.Point(60, 200), fitz.Point(220, 200))
    window.perform_selection("arrow", fitz.Rect(60, 200, 220, 200.1), fitz.Point(60, 200), False, [])
    window.set_mode("freetext")
    window.perform_selection("freetext", fitz.Rect(60, 300, 60, 300), fitz.Point(60, 300), True, [])
    kinds = sorted(a.type[1] for a in annots(window.engine))
    assert kinds == ["FreeText", "Line", "Line"]
    assert view.note_popover is not None
    view.note_popover.edit.setPlainText("Hola")
    view.note_popover.finish()
    text = next(a for a in annots(window.engine) if a.type[1] == "FreeText")
    assert text.info["content"] == "Hola"
    assert window.mode_buttons["line"].isChecked() is False and "freetext" in window.mode_buttons


def test_author_can_be_changed_and_is_remembered(window):
    window.set_annotation_author("Ana")
    window.engine.add_line(0, (10, 10), (90, 90))
    assert annots(window.engine)[0].info["title"] == "Ana"
    assert window.settings.value("annotationAuthor") == "Ana"


def test_rail_has_only_modes_and_fits_without_scroll(window, app):
    rail = window.rail
    app.processEvents()
    from PySide6.QtTest import QTest
    QTest.qWait(100)         # deja terminar el diseño inicial (en Windows tarda algo más)
    app.processEvents()
    for key in ("line", "arrow", "freetext"):
        assert window.mode_buttons[key].isVisibleTo(window) and not window.mode_buttons[key].icon().isNull()
    assert all(not b.isVisibleTo(window) for b in window.doc_buttons.values())
    assert not rail.verticalScrollBar().isVisible()
    assert rail.verticalScrollBar().maximum() == 0
