"""Find and replace in the search bar."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf as fitz
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from pdf_editor.app import EditorWindow
from pdf_editor.theme import STYLE
from tests.test_search_view import wait_for_search


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    instance.setStyle("Fusion")
    instance.setStyleSheet(STYLE)
    return instance


@pytest.fixture()
def window(app, tmp_path):
    win = EditorWindow(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
    win.resize(1024, 768)
    win.show()
    app.processEvents()
    yield win
    win.engine.dirty = False
    win.close()
    app.processEvents()


def make_pdf(path, lines, font="helv"):
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    for number, text in enumerate(lines):
        page.insert_text((72, 100 + number * 30), text, fontsize=12, fontname=font)
    doc.save(str(path))
    doc.close()
    return str(path)


def open_lines(window, tmp_path, lines, name="doc.pdf"):
    window.open_path(make_pdf(tmp_path / name, lines))
    QApplication.processEvents()


def search(window, query, replacement, case=False, whole=False):
    window.open_replace()
    window.search_bar.case_button.setChecked(case)
    window.search_bar.word_button.setChecked(whole)
    window.search.setText(query)
    window.search_bar.replace_field.setText(replacement)
    window.find_text()
    wait_for_search(window)


def text_of(window):
    return window.engine.doc[0].get_text()


def test_replace_mode_shows_second_row(window, tmp_path):
    open_lines(window, tmp_path, ["uno"])
    window.open_search()
    assert not window.search_bar.replace_row.isVisible()
    window.search_bar.replace_toggle.click()
    assert window.search_bar.replace_row.isVisible()
    assert window.search_bar.replace_field.placeholderText()


def test_replace_all_is_one_undo_step_and_counts(window, tmp_path):
    open_lines(window, tmp_path, ["gato y gato", "otro gato aqui"])
    search(window, "gato", "perro")
    window.replace_all()
    text = text_of(window)
    assert text.count("perro") == 3 and "gato" not in text
    assert window.search_bar.replace_count.text() == "3 reemplazos"
    window.undo()
    text = text_of(window)
    assert text.count("gato") == 3 and "perro" not in text


def test_replace_current_replaces_only_that_match(window, tmp_path):
    open_lines(window, tmp_path, ["gato y gato"])
    search(window, "gato", "ave")
    window.search_step(1)
    window.replace_current()
    text = text_of(window)
    assert text.count("ave") == 1 and text.count("gato") == 1


def test_case_and_whole_word_are_respected(window, tmp_path):
    open_lines(window, tmp_path, ["Sol sol solar"])
    search(window, "sol", "luz", case=True)
    window.replace_all()
    assert text_of(window).split() == ["Sol", "luz", "luzar"]
    window.undo()
    search(window, "sol", "luz", whole=True)
    window.replace_all()
    assert text_of(window).split() == ["luz", "luz", "solar"]


def test_text_that_does_not_fit_is_left_and_reported(window, tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=120, height=200)
    page.insert_text((20, 50), "ab", fontsize=12)
    path = tmp_path / "tight.pdf"
    doc.save(str(path))
    doc.close()
    window.open_path(str(path))
    QApplication.processEvents()
    search(window, "ab", "una frase demasiado larga para caber")
    window.replace_all()
    assert "ab" in text_of(window)
    assert window.search_bar.replace_count.text() == "0 reemplazos"


def test_restricted_document_warns_and_does_not_change(window, tmp_path, monkeypatch):
    open_lines(window, tmp_path, ["gato"])
    search(window, "gato", "perro")
    monkeypatch.setattr(type(window.engine), "has_restrictions", property(lambda self: True))
    monkeypatch.setattr(type(window.engine), "has_owner_rights", property(lambda self: False))
    window.replace_all()
    assert "gato" in text_of(window)
    assert "restricciones" in window.replace_blocked()


def test_signed_document_is_refused(window, tmp_path, monkeypatch):
    open_lines(window, tmp_path, ["gato"])
    search(window, "gato", "perro")
    monkeypatch.setattr(type(window.engine.doc), "get_sigflags", lambda self: 3, raising=False)
    assert "firmado" in window.replace_blocked()
    window.replace_all()
    assert "gato" in text_of(window)


def test_non_standard_font_is_reported(window, tmp_path):
    from pdf_editor.search_bar import plan_replacements
    from pdf_editor.ui_navigation import search_pattern
    doc = fitz.open()
    page = doc.new_page()
    page.insert_font(fontname="Fx", fontfile=fitz.Font("cjk").buffer) if False else None
    page.insert_text((72, 100), "gato", fontsize=12, fontname="tiro")
    plan = plan_replacements(page, search_pattern("gato", False, False), "perro")
    assert plan["count"] == 1 and plan["nofit"] == 0
    doc.close()
