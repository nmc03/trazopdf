"""Regression tests for the review findings (flatten, worker, stamps, patterns, temp files, theme)."""
import io
import json
import os
import subprocess
import sys
import time

import pymupdf as fitz
import pytest
from PIL import Image, ImageChops

from pdf_editor import doctools as dt


def blank(rotation=0, size=(600, 600)):
    doc = fitz.open()
    page = doc.new_page(width=size[0], height=size[1])
    page.set_rotation(rotation)
    return doc


def render(doc):
    pix = doc[0].get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False)
    return Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")


def ink_box(image):
    return ImageChops.difference(image, Image.new("RGB", image.size, (255, 255, 255))).getbbox()


def logo_png():
    buf = io.BytesIO()
    image = Image.new("RGBA", (120, 40), (255, 255, 255, 0))
    for x in range(120):
        for y in range(40):
            image.putpixel((x, y), (200, 20, 20, 255) if x < 60 else (20, 20, 200, 255))
    image.save(buf, "PNG")
    return buf.getvalue()


# visual box 200x60 at (150, 120); the unrotated-space rect is what the canvas hands over
VISUAL = fitz.Rect(150, 120, 350, 180)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("as_annotation", [True, False])
@pytest.mark.parametrize("kind", ["preset", "image"])
def test_stamp_on_rotated_page_is_upright_and_wide(rotation, as_annotation, kind):
    reference = blank(0)
    doc = blank(rotation)
    rect = VISUAL * doc[0].derotation_matrix
    for target, area in ((reference, VISUAL), (doc, rect)):
        if kind == "preset":
            dt.add_preset_stamp(target, 0, area, "APROBADO", as_annotation=as_annotation)
        else:
            dt.add_image_stamp(target, 0, area, logo_png(), as_annotation=as_annotation)
    shown, expected = render(doc), render(reference)
    box = ink_box(shown)
    assert box and (box[2] - box[0]) > 2 * (box[3] - box[1]), box
    # Same picture as on an unrotated page: nothing sideways, nothing squeezed.
    diff = ImageChops.difference(shown, expected).convert("L")
    total = sum(level * count for level, count in enumerate(diff.histogram()))
    assert total / (diff.width * diff.height) < 2.0


@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_drawn_preset_stamp_text_direction(rotation):
    doc = blank(rotation)
    dt.add_preset_stamp(doc, 0, VISUAL * doc[0].derotation_matrix, "APROBADO", as_annotation=False)
    page = doc[0]
    line = next(l for b in page.get_text("dict")["blocks"] for l in b.get("lines", ()) if "APROBADO" in l["spans"][0]["text"])
    m = page.rotation_matrix
    d = fitz.Point(line["dir"]) * fitz.Matrix(m.a, m.b, m.c, m.d, 0, 0)
    assert d.x == pytest.approx(1, abs=0.01) and d.y == pytest.approx(0, abs=0.01)


# ------------------------------------------------------------ app fixtures

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMessageBox

from pdf_editor.app import EditorWindow
from pdf_editor.theme import STYLE

SECRET = "ZEBRA-4417"


@pytest.fixture(scope="module")
def qapp():
    a = QApplication.instance() or QApplication([])
    a.setStyleSheet(STYLE)
    return a


@pytest.fixture
def app_window(qapp, tmp_path):
    w = EditorWindow(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
    w.engine.new()
    w.engine.doc[0].insert_text((72, 100), SECRET, fontsize=12)
    w.engine.dirty = True
    w.refresh()
    yield w
    w.engine.dirty = False
    w.close()
    qapp.processEvents()


def pick(monkeypatch, *labels):
    """QMessageBox.exec clicks the first button whose label is in labels (in order)."""
    queue = list(labels)

    def fake_exec(box):
        wanted = queue.pop(0) if len(queue) > 1 else queue[0]
        for button in box.buttons():
            if button.text().replace("&", "") == wanted:
                box.setProperty("picked", wanted)
                box._picked = button
                return 0
        return 0

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda box: getattr(box, "_picked", None))


@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_click_stamp_on_rotated_page_is_wide(app_window, rotation):
    window = app_window
    window.engine.doc[0].set_rotation(rotation)
    page = window.engine.doc[0]
    window.pending_stamp = {"kind": "preset", "name": "APROBADO", "color": None, "image": "", "opacity": 1.0, "as_annotation": True}
    window.place_stamp(fitz.Point(300, 400) * page.derotation_matrix, None)
    annot = next(iter(page.annots()))
    visual = annot.rect * page.rotation_matrix
    assert visual.width == pytest.approx(180, abs=1) and visual.height == pytest.approx(54, abs=1)
