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
    with tempfile.TemporaryDirectory(prefix="wp-v-", ignore_cleanup_errors=True) as folder:
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


def read_back(eng):
    _pages[:] = [eng.doc[0]]
    return {a.xref: a for a in _pages[0].annots() or ()}


def test_real_size_scales_convert_points_to_each_unit(engine):
    for unit, points in (("mm", 72 / 25.4), ("cm", 72 / 2.54), ("pulg", 72), ("pt", 1)):
        assert engine.measure_value([(0, 0), (points * 10, 0)], engine.measure_true_scale(unit), unit) == f"10,00 {unit}"
    assert engine.measure_value([(0, 0), (100, 0), (100, 100), (0, 100)], 0.5, "cm", area=True) == "2 500,00 cm²"


def test_distance_is_saved_as_a_line_with_its_value_as_text(engine):
    xref = engine.add_measurement(0, [(10, 10), (10 + 72, 10)], engine.measure_true_scale("pulg"), "pulg")
    annot = read_back(engine)[xref]
    assert annot.type[1] == "Line" and annot.info["content"] == "1,00 pulg" and annot.info["subject"] == "Medición"
    found = engine.measurements(0)
    assert [(m["kind"], m["label"]) for m in found] == [("distance", "1,00 pulg")]


def test_area_is_saved_as_a_polygon_and_survives_saving(engine, tmp_path):
    scale = 25.4 / 72
    xref = engine.add_measurement(0, [(0, 0), (200, 0), (200, 100), (0, 100)], scale, "mm", area=True)
    assert read_back(engine)[xref].type[1] == "Polygon"
    path = tmp_path / "measured.pdf"
    engine.doc.save(path)
    with fitz.open(path) as reopened:
        page = reopened[0]
        annot = next(iter(page.annots()))
        assert annot.type[1] == "Polygon" and annot.info["content"].startswith("2") and annot.info["content"].endswith("mm²")
        assert len(annot.vertices) == 4


def test_invalid_measurements_are_rejected(engine):
    with pytest.raises(ValueError):
        engine.add_measurement(0, [(1, 1), (1.5, 1)], 1, "pt")
    with pytest.raises(ValueError):
        engine.add_measurement(0, [(0, 0), (50, 0)], 0, "mm")
    with pytest.raises(ValueError):
        engine.add_measurement(0, [(0, 0), (50, 0)], 1, "furlong")
    with pytest.raises(ValueError):
        engine.add_measurement(0, [(0, 0), (50, 0)], 1, "pt", area=True)
    assert engine.measurements(0) == []


def test_measure_tool_is_in_the_comment_group_with_an_icon(window):
    button = window.mode_buttons["measure"]
    assert button.text() == "Medir" and not button.icon().isNull()


def test_dragging_in_measure_mode_saves_a_distance_and_labels_it(window, app):
    window.set_mode("measure")
    view = window.view
    assert view.measure.bar.isVisibleTo(window)
    a, b = view.scene_point(fitz.Point(100, 100)), view.scene_point(fitz.Point(100 + 72, 100))
    view.measure.press(a, view.pdf_point(a))
    view.measure.release(b, view.pdf_point(b))
    app.processEvents()
    found = window.engine.measurements(window.page)
    assert len(found) == 1 and found[0]["label"] == "25,40 mm"
    assert window.engine.dirty
    window.undo()
    assert window.engine.measurements(window.page) == []


def test_clicking_corners_and_double_click_saves_an_area(window, app):
    window.set_mode("measure")
    view = window.view
    view.measure.set_kind("area")
    for x, y in ((100, 100), (172, 100), (172, 172)):
        scene = view.scene_point(fitz.Point(x, y))
        view.measure.press(scene, view.pdf_point(scene))
    assert view.measure.items
    view.measure.double_click()
    app.processEvents()
    found = window.engine.measurements(window.page)
    assert len(found) == 1 and found[0]["kind"] == "area" and found[0]["label"].endswith("mm²")
    assert found[0]["label"] == "322,58 mm²"


def test_area_needs_three_corners(window):
    window.set_mode("measure")
    view = window.view
    view.measure.set_kind("area")
    for x in (100, 150):
        scene = view.scene_point(fitz.Point(x, 100))
        view.measure.press(scene, view.pdf_point(scene))
    view.measure.double_click()
    assert window.engine.measurements(window.page) == []


def test_scale_is_edited_inline_and_applied_to_new_measurements(window):
    window.set_mode("measure")
    measure = window.view.measure
    measure.unit_box.setCurrentText("cm")
    measure.unit_chosen()
    measure.scale_edit.setText("0,1")
    measure.scale_edited()
    assert measure.scale() == (0.1, "cm")
    a, b = window.view.scene_point(fitz.Point(50, 50)), window.view.scene_point(fitz.Point(250, 50))
    measure.press(a, window.view.pdf_point(a))
    measure.release(b, window.view.pdf_point(b))
    assert window.engine.measurements(window.page)[0]["label"] == "20,00 cm"


def test_invalid_scale_text_is_reverted(window):
    window.set_mode("measure")
    measure = window.view.measure
    before = measure.scale()
    measure.scale_edit.setText("abc")
    measure.scale_edited()
    assert measure.scale() == before and measure.scale_edit.text() != "abc"
    measure.scale_edit.setText("-3")
    measure.scale_edited()
    assert measure.scale() == before


def test_saved_measurements_get_a_label_on_the_canvas_only_in_measure_mode(window):
    window.engine.add_measurement(window.page, [(50, 50), (150, 50)], 0.5, "mm")
    window.refresh()
    window.set_mode("measure")
    assert any(getattr(item, "childItems", None) and item.childItems() for item in window.view.layer_items)
    window.set_mode("select")
    assert not window.view.measure.bar.isVisibleTo(window)


def test_leaving_the_tool_discards_a_half_drawn_area(window):
    window.set_mode("measure")
    view = window.view
    view.measure.set_kind("area")
    scene = view.scene_point(fitz.Point(100, 100))
    view.measure.press(scene, view.pdf_point(scene))
    window.set_mode("select")
    assert view.measure.points == [] and view.measure.items == []
