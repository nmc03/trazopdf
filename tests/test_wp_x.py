"""Detectar campos: líneas y casillas de un PDF plano se convierten en campos en un solo paso de deshacer."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from pdf_editor import autofields
from pdf_editor.app import EditorWindow
from pdf_editor.engine import PDFEngine


def flat_pdf(path):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Nombre:", fontsize=11)
    page.draw_line((130, 102), (330, 102), width=0.8)
    page.insert_text((72, 140), "Correo:", fontsize=11)
    page.draw_line((130, 142), (330, 142), width=0.8)
    page.draw_rect(fitz.Rect(72, 170, 84, 182), width=0.8)
    page.insert_text((92, 180), "Acepto", fontsize=11)
    page.insert_text((72, 220), "Texto subrayado normal", fontsize=11)
    page.draw_line((72, 223), (190, 223), width=0.8)
    doc.save(path)
    doc.close()


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_detect_finds_lines_and_boxes(tmp_path):
    path = str(tmp_path / "flat.pdf")
    flat_pdf(path)
    doc = fitz.open(path)
    found = autofields.detect(doc[0])
    by_name = {c["name"]: c for c in found}
    assert set(by_name) == {"Nombre", "Correo", "Acepto"}
    assert by_name["Nombre"]["kind"] == "text"
    assert by_name["Acepto"]["kind"] == "checkbox"


def test_engine_creates_all_in_one_undo(tmp_path):
    path = str(tmp_path / "flat.pdf")
    flat_pdf(path)
    engine = PDFEngine()
    engine.open(path)
    specs = [(c["page"], c["rect"], c["name"], c["kind"]) for c in autofields.detect(engine.doc[0])]
    assert engine.add_fields(specs) == 3
    assert {f["name"] for f in engine.forms()} == {"Nombre", "Correo", "Acepto"}
    engine.undo()
    assert engine.forms() == []


def test_panel_discard_and_create(app, tmp_path):
    path = str(tmp_path / "flat.pdf")
    flat_pdf(path)
    w = EditorWindow(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
    try:
        w.engine.open(path)
        w.refresh()
        panel = autofields.open_detector(w)
        assert panel is not None and len(panel.candidates) == 3
        assert panel.create_button.text() == "Crear 3 campos"
        panel.list.item(0).setCheckState(autofields.Qt.CheckState.Unchecked)
        assert panel.create_button.text() == "Crear 2 campos"
        assert panel.items
        panel.create_button.click()
        assert len(w.engine.forms()) == 2
        assert getattr(w, "detector", None) is None
        w.engine.undo()
        assert w.engine.forms() == []
    finally:
        w.engine.dirty = False
        w.close()
        app.processEvents()
