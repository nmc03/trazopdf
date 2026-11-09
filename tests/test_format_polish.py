"""Format polish: underline and line spacing, vector check marks, object bar for stamps and images, banners over the page."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf as fitz
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from pdf_editor import icons, toast
from pdf_editor.app import EditorWindow, STYLE
from pdf_editor.engine import PDFEngine
from pdf_editor.floating_bar import LINE_SPACINGS
from pdf_editor.toast import banner_for


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    a.setStyleSheet(STYLE)
    return a


@pytest.fixture
def window(app, tmp_path):
    w = EditorWindow(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
    w.engine.new()
    w.engine.doc[0].insert_text((72, 60), "Pagina de prueba", fontsize=12)
    w.engine.dirty = True
    w.refresh()
    yield w
    w.engine.dirty = False
    w.close()
    app.processEvents()


def line_tops(page):
    return [round(line["bbox"][1], 1) for block in page.get_text("dict")["blocks"] for line in block.get("lines", [])]


def png(tmp_path):
    image = QImage(60, 24, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 255))
    path = tmp_path / "imagen.png"
    image.save(str(path))
    return path


# ------------------------------------------------------- text: underline, spacing

def test_underline_draws_one_rule_under_the_block(tmp_path):
    engine = PDFEngine()
    engine.new()
    engine.add_text(0, (72, 100, 400, 200), "Linea uno\nLinea dos", 12, underline=True)
    drawings = engine.doc[0].get_drawings()
    assert len(drawings) == 1
    rules = [item for item in drawings[0]["items"] if item[0] == "l"]
    assert len(rules) == 2
    bottoms = [line["bbox"][3] for block in engine.doc[0].get_text("dict")["blocks"] for line in block.get("lines", [])]
    # Each rule sits just under its own text line.
    for rule, bottom in zip(sorted(rules, key=lambda item: item[1].y), bottoms):
        assert bottom < rule[1].y < bottom + 3


def test_line_spacing_doubles_the_distance_between_lines():
    engine = PDFEngine()
    engine.new()
    engine.add_text(0, (72, 100, 400, 200), "Linea uno\nLinea dos", 12, line_spacing=1.0)
    single = line_tops(engine.doc[0])
    engine.new()
    engine.add_text(0, (72, 100, 400, 260), "Linea uno\nLinea dos", 12, line_spacing=2.0)
    double = line_tops(engine.doc[0])
    assert len(single) == len(double) == 2
    assert double[1] - double[0] == pytest.approx(2 * (single[1] - single[0]), abs=1.0)


def test_replace_text_keeps_spacing_and_underline_on_save(tmp_path):
    engine = PDFEngine()
    engine.new()
    engine.add_text(0, (72, 100, 400, 200), "Original", 12)
    original = engine.doc[0].get_text("dict", clip=fitz.Rect(72, 100, 400, 200))["blocks"][0]["lines"][0]["bbox"]
    engine.replace_text(0, original, "Uno\nDos", 12, underline=True, line_spacing=1.5, target_rect=fitz.Rect(72, 100, 400, 200))
    assert len(engine.doc[0].get_drawings()) == 1
    target = tmp_path / "salida.pdf"
    engine.save(target)
    with fitz.open(target) as saved:
        tops = line_tops(saved[0])
        assert len(tops) == 2 and tops[1] - tops[0] > 17.7 * 1.3


def test_line_spacing_out_of_range_is_refused():
    engine = PDFEngine()
    engine.new()
    with pytest.raises(ValueError):
        engine.add_text(0, (72, 100, 400, 200), "Texto", 12, line_spacing=0.5)


def test_format_bar_offers_underline_and_spacing(window):
    bar = window.view.format_bar
    seen = []
    bar.actionRequested.connect(lambda name, value: seen.append((name, value)))
    bar.underline.click()
    bar.spacing.setCurrentIndex(2)
    assert ("underline", True) in seen
    assert ("spacing", LINE_SPACINGS[2]) in seen
    assert bar.underline.toolTip().endswith("(Ctrl+U)")


def test_live_editor_gets_underline_and_spacing(window):
    view = window.view
    window.set_mode("text")
    view.begin_editor(point=fitz.Point(72, 150))
    view.format_bar.underline.click()
    view.format_bar.spacing.setCurrentIndex(3)
    assert view.editor.underline is True
    assert view.editor.line_spacing == LINE_SPACINGS[3]
    view.editor.setPlainText("Subrayado en vivo")
    assert view.commit_editor()
    page = window.engine.doc[0]
    assert "Subrayado en vivo" in page.get_text()
    assert len(page.get_drawings()) == 1


# ---------------------------------------------------------- vector check marks

def test_check_and_cross_are_vector_strokes(tmp_path):
    engine = PDFEngine()
    engine.new()
    engine.add_mark(0, (72, 100, 92, 116), "check")
    engine.add_mark(0, (120, 100, 136, 116), "cross")
    drawings = engine.doc[0].get_drawings()
    assert len(drawings) == 2
    assert [len(d["items"]) for d in drawings] == [2, 2]
    assert engine.doc[0].get_text().strip() == ""
    # Stroke width follows the mark size.
    assert drawings[0]["width"] == pytest.approx(16 * 0.12, abs=0.05)


def test_mark_rejects_unknown_kind_and_tiny_boxes():
    engine = PDFEngine()
    engine.new()
    with pytest.raises(ValueError):
        engine.add_mark(0, (72, 100, 92, 116), "star")
    with pytest.raises(ValueError):
        engine.add_mark(0, (72, 100, 73, 101), "check")


# ------------------------------------------------------------- object bar

def test_image_rotates_a_quarter_turn(tmp_path):
    engine = PDFEngine()
    engine.new()
    engine.add_image(0, (100, 100, 300, 150), png(tmp_path))
    before = engine.images(0)[0]["rect"]
    engine.rotate_image(0, engine.images(0)[0]["index"])
    after = engine.images(0)[0]["rect"]
    assert after.width == pytest.approx(before.height, abs=1.0)
    assert after.height == pytest.approx(before.width, abs=1.0)
    assert (after.x0 + after.x1) / 2 == pytest.approx((before.x0 + before.x1) / 2, abs=1.0)
    assert (after.y0 + after.y1) / 2 == pytest.approx((before.y0 + before.y1) / 2, abs=1.0)


def test_selected_image_shows_rotate_replace_opacity_and_delete(window, tmp_path):
    window.engine.add_image(0, (100, 100, 300, 150), png(tmp_path))
    window.refresh()
    view = window.view
    image = window.engine.images(0)[0]
    view.select_image(image)
    bar = view.format_bar
    assert bar.profile == "object"
    assert bar.object_rotate.isVisibleTo(bar)
    assert bar.object_replace.isVisibleTo(bar)
    assert bar.object_opacity.isVisibleTo(bar)


def test_selected_stamp_shows_opacity_and_changes_it(window):
    window.engine.add_stamp(0, (100, 100, 260, 140), kind="preset", name="APROBADO")
    window.refresh()
    stamps = [a for a in window.engine.annotations(0) if a["type"] == "Stamp"]
    assert stamps, "el sello debe listarse como anotación editable"
    view = window.view
    view.select_annotation(stamps[0])
    bar = view.format_bar
    assert bar.profile == "object"
    assert bar.object_opacity.isVisibleTo(bar)
    assert not bar.object_rotate.isVisibleTo(bar)
    bar.object_opacity.setCurrentIndex(2)
    xref = stamps[0]["xref"]
    refreshed = [a for a in window.engine.annotations(0) if a["xref"] == xref][0]
    assert refreshed["opacity"] == pytest.approx(0.4, abs=0.05)


def test_format_actions_are_icons_not_text(window):
    bar = window.view.format_bar
    assert all(button.text() == "" and not button.icon().isNull() for button in bar.align_buttons)
    assert "(Ctrl+L)" in bar.align_buttons[0].toolTip()
    assert not icons.themed_icon("align-justify").isNull()


# --------------------------------------------------------------- banners

def test_banner_floats_over_the_page_without_a_column(window, app):
    window.resize(1100, 760)
    window.show()
    app.processEvents()
    splitter = window.splitter
    count, sizes, page_width = splitter.count(), splitter.sizes(), window.view.width()
    toast.notify(window, "Aviso que no debe ocupar columna")
    app.processEvents()
    banner = banner_for(window)
    assert banner.parentWidget() is window.stack
    assert splitter.count() == count
    assert splitter.sizes() == sizes
    assert window.view.width() == page_width
    assert banner.isVisible()
    window.engine.dirty = False
