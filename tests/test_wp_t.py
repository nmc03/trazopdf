"""Layers (optional content): panel, visibility, canvas refresh and remembering on save."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf as fitz
import pytest
from PySide6.QtCore import QSettings, Qt
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
def window(app, tmp_path):
    win = EditorWindow(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
    win.resize(1024, 768)
    win.show()
    app.processEvents()
    yield win
    win.engine.dirty = False
    win.close()
    app.processEvents()


def make_layered(path):
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    red = doc.add_ocg("Fondo")
    blue = doc.add_ocg("Notas")
    page.draw_rect(fitz.Rect(20, 20, 80, 80), color=None, fill=(1, 0, 0), oc=red)
    page.draw_rect(fitz.Rect(120, 20, 180, 80), color=None, fill=(0, 0, 1), oc=blue)
    doc.save(str(path))
    doc.close()
    return path


def make_plain(path):
    doc = fitz.open()
    doc.new_page()
    doc.save(str(path))
    doc.close()
    return path


def pixel(engine, x, y):
    return engine.render(0, 1).pixel(x, y)


def test_engine_hides_layer_without_marking_dirty(tmp_path):
    engine = PDFEngine()
    engine.open(make_layered(tmp_path / "l.pdf"))
    assert [row["text"] for row in engine.layers()] == ["Fondo", "Notas"]
    assert pixel(engine, 50, 50) == (255, 0, 0)
    engine.set_layer_visible(0, False)
    assert pixel(engine, 50, 50) == (255, 255, 255)
    assert pixel(engine, 150, 50) == (0, 0, 255)
    assert not engine.dirty and not engine._undo


def test_save_keeps_original_state_unless_asked(tmp_path):
    engine = PDFEngine()
    engine.open(make_layered(tmp_path / "l.pdf"))
    engine.layers()
    engine.set_layer_visible(0, False)
    engine.save(str(tmp_path / "a.pdf"))
    assert fitz.open(str(tmp_path / "a.pdf")).layer_ui_configs()[0]["on"] == 1
    assert pixel(engine, 50, 50) == (255, 255, 255)
    engine.remember_layers(True)
    engine.save(str(tmp_path / "b.pdf"))
    assert fitz.open(str(tmp_path / "b.pdf")).layer_ui_configs()[0]["on"] == 0
    engine.remember_layers(False)
    engine.save(str(tmp_path / "c.pdf"))
    assert fitz.open(str(tmp_path / "c.pdf")).layer_ui_configs()[0]["on"] == 1


def test_choice_survives_undo(tmp_path):
    engine = PDFEngine()
    engine.open(make_layered(tmp_path / "l.pdf"))
    engine.layers()
    engine.set_layer_visible(1, False)
    engine.checkpoint()
    engine.undo()
    assert [row["on"] for row in engine.layers()] == [1, 0]


def test_panel_toggle_refreshes_canvas(app, window, tmp_path):
    window.open_path(str(make_layered(tmp_path / "l.pdf"))) if hasattr(window, "open_path") else window.engine.open(str(make_layered(tmp_path / "l.pdf")))
    window.refresh()
    window.left_tabs.setCurrentWidget(window.layers_panel)
    app.processEvents()
    tree = window.layers_panel.tree
    assert tree.topLevelItemCount() == 2
    assert tree.topLevelItem(0).checkState(0) == Qt.CheckState.Checked
    shots = []
    original = window.render_page
    window.render_page = lambda: (shots.append(1), original())[1]
    tree.topLevelItem(0).setCheckState(0, Qt.CheckState.Unchecked)
    assert shots and pixel(window.engine, 50, 50) == (255, 255, 255)
    assert not window.engine.dirty


def test_panel_without_layers_says_so(app, window, tmp_path):
    window.engine.open(str(make_plain(tmp_path / "p.pdf")))
    window.refresh()
    window.left_tabs.setCurrentWidget(window.layers_panel)
    window.refresh_side_panel(True)
    app.processEvents()
    panel = window.layers_panel
    assert panel.stack.currentWidget() is panel.empty
    assert panel.empty.text() == "Este documento no tiene capas"
