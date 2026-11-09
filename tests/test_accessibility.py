import pymupdf as fitz
import pytest
from PySide6.QtWidgets import QApplication

from pdf_editor import accessibility as acc
from pdf_editor.engine import PDFEngine


@pytest.fixture
def engine():
    QApplication.instance() or QApplication([])
    e = PDFEngine()
    e.doc[0].insert_text((72, 100), "Hola mundo", fontsize=12)
    yield e
    e.dirty = False
    e.close()


def by_key(results):
    return {r["key"]: r for r in results}


def test_missing_title_and_language_are_two_errors_then_zero(engine, tmp_path):
    engine.save(tmp_path / "informe-anual.pdf")
    results = acc.check(engine.doc)
    assert acc.error_count(results) == 2
    acc.fix_title(engine)
    acc.fix_language(engine, "es")
    assert acc.error_count(acc.check(engine.doc)) == 0
    out = tmp_path / "out.pdf"
    engine.save(out)
    doc = fitz.open(out)
    assert doc.metadata["title"] == "informe anual"
    assert acc.language(doc) == "es"
    doc.close()


def test_fixes_go_through_undo(engine):
    acc.fix_language(engine, "en")
    assert acc.language(engine.doc) == "en"
    engine.undo()
    assert acc.language(engine.doc) == ""


def test_page_without_text_is_detected(engine):
    page = engine.doc.new_page()
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 20, 20), False)
    pix.set_rect(pix.irect, (200, 0, 0))
    page.insert_image(fitz.Rect(50, 50, 150, 150), pixmap=pix)
    item = by_key(acc.check(engine.doc))["text"]
    assert item["status"] == acc.WARNING and "2" in item["detail"]


def test_long_document_without_bookmarks_warns(engine):
    for _ in range(acc.LONG_DOCUMENT_PAGES):
        engine.doc.new_page()
    assert by_key(acc.check(engine.doc))["bookmarks"]["status"] == acc.WARNING
    engine.doc.set_toc([[1, "Inicio", 1]])
    assert by_key(acc.check(engine.doc))["bookmarks"]["status"] == acc.OK


def test_report_text_lists_every_item(engine):
    text = acc.report_text(acc.check(engine.doc), "a.pdf")
    assert "[Error] Título del documento" in text and "Errores: 2" in text


def test_menu_entry_opens_dialog(tmp_path):
    from PySide6.QtCore import QSettings
    from pdf_editor.app import EditorWindow
    QApplication.instance() or QApplication([])
    w = EditorWindow(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
    w.engine.new()
    action = w.actions["accessibility"]
    assert action.text() == "Comprobar accesibilidad…" and not action.shortcuts()
    dialog = __import__("pdf_editor.accessibility_dialog", fromlist=["x"]).open_accessibility(w)
    assert dialog.table.rowCount() == 6
    dialog.fix("language")
    assert acc.language(w.engine.doc) == "es"
    dialog.close()
    w.engine.dirty = False
    w.close()
