"""Miniaturas: insignias (comentarios, giro, etiqueta), control de tamaño recordado y placeholder."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from pdf_editor.app import EditorWindow
from pdf_editor.pages_panel import COMMENTS_ROLE, LABEL_ROLE, ROTATION_ROLE, BadgeDelegate, ThumbnailList


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def make_window(path):
    w = EditorWindow(QSettings(str(path), QSettings.Format.IniFormat))
    w.engine.new()
    w.engine.doc.new_page()
    w.engine.doc.new_page()
    w.engine.dirty = True
    return w


@pytest.fixture
def window(app, tmp_path):
    w = make_window(tmp_path / "s.ini")
    w.refresh()
    yield w
    w.engine.dirty = False
    w.close()
    app.processEvents()


def badge_kinds(window, row):
    delegate = window.thumbnails.itemDelegate()
    index = window.thumbnails.model().index(row, 0)
    return [corner for corner, _text, _tip in delegate.badges(index)]


def test_plain_pages_have_no_badges(window):
    assert isinstance(window.thumbnails.itemDelegate(), BadgeDelegate)
    assert [badge_kinds(window, row) for row in range(3)] == [[], [], []]


def test_comment_rotation_and_label_show_badges_only_on_their_page(window):
    window.engine.doc[1].add_text_annot((100, 100), "nota")
    window.engine.doc[2].set_rotation(90)
    window.engine.doc.set_page_labels([{"startpage": 0, "prefix": "A", "style": "D", "firstpagenum": 1}])
    window.refresh()
    item = window.thumbnails.item
    assert item(1).data(COMMENTS_ROLE) == 1 and item(0).data(COMMENTS_ROLE) == 0
    assert item(2).data(ROTATION_ROLE) == 90 and item(0).data(ROTATION_ROLE) == 0
    assert all(item(row).data(LABEL_ROLE) for row in range(3))
    assert "tr" in badge_kinds(window, 1) and "tl" not in badge_kinds(window, 1)
    assert "tl" in badge_kinds(window, 2) and "tr" not in badge_kinds(window, 2)
    window.engine.doc.set_page_labels([])
    window.refresh()
    assert badge_kinds(window, 0) == []


def test_unrendered_thumbnail_paints_placeholder(window):
    window.thumbnails.item(0).setIcon(__import__("PySide6.QtGui", fromlist=["QIcon"]).QIcon())
    pixmap = window.thumbnails.viewport().grab()
    assert not pixmap.isNull()


def test_size_slider_is_remembered(app, tmp_path):
    first = make_window(tmp_path / "s.ini")
    first.refresh()
    first.thumbnails.slider.setValue(150)
    assert first.thumbnails.thumb_size.width() == 150
    assert int(first.settings.value("thumbWidth")) == 150
    first.settings.sync()
    first.engine.dirty = False
    first.close()
    second = make_window(tmp_path / "s.ini")
    second.refresh()
    assert second.thumbnails.preferred_width == 150
    assert second.thumbnails.slider.value() == 150
    second.engine.dirty = False
    second.close()


def test_thumbnails_shrink_with_a_narrow_panel_and_recover(app):
    thumbs = ThumbnailList()
    thumbs.show()
    thumbs.set_thumb_width(160)
    thumbs.resize(400, 400)
    app.processEvents()
    assert thumbs.thumb_size.width() == 160
    thumbs.resize(120, 400)
    app.processEvents()
    assert thumbs.thumb_size.width() < 160
    assert thumbs.preferred_width == 160
    thumbs.resize(400, 400)
    app.processEvents()
    assert thumbs.thumb_size.width() == 160
    thumbs.close()
