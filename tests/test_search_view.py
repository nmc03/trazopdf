"""Inline search bar, zoom and view modes, page memory, rotated view and full screen."""
import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf as fitz
import pytest
from PySide6.QtCore import QPoint, QPointF, QSettings, Qt
from PySide6.QtGui import QKeySequence, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QToolBar, QToolButton

from pdf_editor import ui_navigation
from pdf_editor.app import EditorWindow
from pdf_editor.theme import STYLE
from pdf_editor.ui_support import PAGE_MARGIN


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    instance.setStyle("Fusion")
    instance.setStyleSheet(STYLE)
    return instance


@pytest.fixture()
def window(app, tmp_path):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    win = EditorWindow(settings)
    win.resize(1024, 768)
    win.show()
    app.processEvents()
    yield win
    win.engine.dirty = False
    win.close()
    app.processEvents()


def make_pdf(path, pages):
    doc = fitz.open()
    for text in pages:
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 100), text, fontsize=12)
    doc.save(str(path))
    doc.close()
    return str(path)


def open_pages(window, tmp_path, pages, name="doc.pdf"):
    path = make_pdf(tmp_path / name, pages)
    window.open_path(path)
    QApplication.processEvents()
    window.fit_locked_until = 0.0
    return path


def wait_for_search(window, limit=10.0):
    end = time.monotonic() + limit
    while window.search_state is not None and time.monotonic() < end:
        QTest.qWait(5)
    assert window.search_state is None


def test_ctrl_f_opens_bar_and_escape_closes_it(window, tmp_path):
    open_pages(window, tmp_path, ["alpha"])
    assert window.view_actions["search"].shortcut() == QKeySequence("Ctrl+F")
    assert not window.search_toolbar.isVisible()
    window.view_actions["search"].trigger()
    assert window.search_toolbar.isVisible()
    QTest.keyClick(window.search, Qt.Key.Key_Escape)
    assert not window.search_toolbar.isVisible()
    assert window.search_results == []


def test_counter_next_previous_and_wrap(window, tmp_path):
    open_pages(window, tmp_path, ["alpha one", "beta", "alpha two", "alpha three"])
    window.search.setText("alpha")
    QTest.keyClick(window.search, Qt.Key.Key_Return)
    assert window.search_bar.count.text() == "1 de 3"
    assert window.search_bar.next_button.isEnabled()
    QTest.keyClick(window.search, Qt.Key.Key_Return)
    assert window.search_bar.count.text() == "2 de 3"
    assert window.page == 2
    QTest.keyClick(window.search, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert window.search_bar.count.text() == "1 de 3"
    window.search_navigate(False)
    assert window.search_bar.count.text() == "3 de 3"
    assert window.page == 3


def test_case_and_whole_word_switches(window, tmp_path):
    open_pages(window, tmp_path, ["Alpha alphabet alpha"])
    window.search.setText("alpha")
    window.find_text()
    assert len(window.search_results) == 3
    window.search_bar.case_button.setChecked(True)
    assert len(window.search_results) == 2
    window.search_bar.case_button.setChecked(False)
    window.search_bar.word_button.setChecked(True)
    assert len(window.search_results) == 2
    window.search_bar.case_button.setChecked(True)
    assert len(window.search_results) == 1


def test_every_match_is_highlighted_and_current_is_stronger(window, tmp_path):
    open_pages(window, tmp_path, ["gamma gamma gamma"])
    window.search.setText("gamma")
    window.find_text()
    current = [item for item in window.search_items if item.zValue() == 4]
    other = [item for item in window.search_items if item.zValue() == 3]
    assert len(current) == 1
    assert len(other) == 2


def test_no_results_is_shown_in_the_bar(window, tmp_path):
    open_pages(window, tmp_path, ["delta"])
    window.search.setText("zzz")
    window.find_text()
    assert window.search_bar.count.text() == "Sin resultados"
    assert not window.search_bar.next_button.isEnabled()
    assert not window.toolbar_next.isEnabled()
    assert window.search_toolbar.isVisible() is False


def test_long_document_is_searched_in_batches(window, tmp_path):
    pages = [f"page {index} needle" for index in range(70)]
    open_pages(window, tmp_path, pages, name="long.pdf")
    window.search.setText("needle")
    window.find_text()
    assert window.search_state is not None
    assert window.search_bar.count.text().startswith("Buscando")
    wait_for_search(window)
    assert len(window.search_results) == 70
    assert window.search_bar.count.text() == "1 de 70"


def test_fit_width_and_fit_page_match_the_viewport(window, tmp_path):
    open_pages(window, tmp_path, ["one page"])
    window.fit_width()
    vbar, hbar = window.view.verticalScrollBar(), window.view.horizontalScrollBar()
    width = window.view.viewport().width() + (vbar.width() if vbar.isVisible() else 0)
    height = window.view.viewport().height() + (hbar.height() if hbar.isVisible() else 0)
    expected_width = (width - 2 * PAGE_MARGIN - 8) / 612 / 1.25 * 100
    assert abs(window.zoom.value() - expected_width) <= 1
    assert window.zoom_mode == "width"
    window.fit_page()
    expected_height = (height - 2 * PAGE_MARGIN - 8) / 792 / 1.25 * 100
    expected_page = min(expected_width, expected_height)
    assert abs(window.zoom.value() - expected_page) <= 1
    assert window.zoom_mode == "page"
    window.actual_size()
    assert window.zoom.value() == 100
    assert window.zoom_mode == "actual"


def test_two_page_view_pairs_pages_and_clicking_the_other_page_selects_it(window, tmp_path):
    open_pages(window, tmp_path, ["one", "two", "three"])
    window.goto(0)
    window.view_actions["double"].trigger()
    assert window.view_layout == "double"
    assert window.visible_pages() == [0, 1]
    assert [index for index, _ in window.view.companion_rects] == [1]
    window.goto(2)
    assert window.visible_pages() == [2]
    window.goto(1)
    assert window.visible_pages() == [0, 1]
    window.goto(0)
    rect = dict(window.view.companion_rects)[1]
    point = window.view.mapFromScene(rect.center())
    QTest.mouseClick(window.view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    assert window.page == 1


def test_wheel_past_the_bottom_turns_the_page(window, tmp_path):
    open_pages(window, tmp_path, ["first", "second"])
    window.fit_page()
    bar = window.view.verticalScrollBar()
    bar.setValue(bar.maximum())
    window.view.last_wheel_turn = 0.0
    wheel = QWheelEvent(QPointF(100, 100), QPointF(100, 100), QPoint(0, 0), QPoint(0, -120),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    window.view.wheelEvent(wheel)
    assert window.page == 1
    window.view.last_wheel_turn = 0.0
    wheel = QWheelEvent(QPointF(100, 100), QPointF(100, 100), QPoint(0, 0), QPoint(0, 120),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    window.view.wheelEvent(wheel)
    assert window.page == 0


def test_last_page_is_remembered_per_file(window, tmp_path):
    first = open_pages(window, tmp_path, ["a", "b", "c"], name="first.pdf")
    window.goto(2)
    open_pages(window, tmp_path, ["other"], name="second.pdf")
    assert window.page == 0
    window.open_path(first)
    QApplication.processEvents()
    assert window.page == 2
    assert window.saved_position(first) == 2


def test_zoom_mode_and_layout_are_remembered(window, tmp_path):
    open_pages(window, tmp_path, ["one", "two"])
    window.fit_page()
    window.set_view_layout("double")
    settings = window.settings
    assert settings.value("zoomMode") == "page"
    assert settings.value("viewLayout") == "double"
    other = EditorWindow(settings)
    try:
        assert other.zoom_mode == "page"
        assert other.view_layout == "double"
    finally:
        other.close()


def test_fullscreen_hides_panels_and_escape_restores_them(window, tmp_path):
    open_pages(window, tmp_path, ["full"])
    rail = window.splitter.widget(0)
    assert rail.isVisible()
    window.toggle_fullscreen()
    assert window.isFullScreen()
    assert rail.isHidden()
    assert window.pages_panel.isHidden()
    assert window.menuBar().isHidden()
    window.view.setFocus()
    QTest.keyClick(window.view, Qt.Key.Key_Escape)
    assert not window.isFullScreen()
    assert rail.isVisible()
    assert window.pages_panel.isVisible()


def test_rotate_view_leaves_the_document_alone(window, tmp_path):
    open_pages(window, tmp_path, ["turn"])
    window.rotate_view()
    assert window.view_angle == 90
    assert abs(window.view.transform().m11()) < 1e-6
    assert window.engine.doc[0].rotation == 0


def test_tool_letters_pick_the_tool_when_the_page_has_focus(window, tmp_path):
    open_pages(window, tmp_path, ["letters"])
    window.view.setFocus()
    QTest.keyClick(window.view, Qt.Key.Key_T)
    # T is the unified Texto tool, which is the replace mode (the old "text" mode is routed there).
    assert window.view.mode == "replace"
    QTest.keyClick(window.view, Qt.Key.Key_V)
    assert window.view.mode == "select"


def test_zoom_shortcuts_are_bound(window, tmp_path):
    open_pages(window, tmp_path, ["zoom"])
    assert window.view_actions["fit_page"].shortcut() == QKeySequence("Ctrl+9")
    assert window.view_actions["actual"].shortcut() == QKeySequence("Ctrl+1")
    assert window.view_actions["find_next"].shortcut() == QKeySequence("F3")
    assert window.view_actions["find_prev"].shortcut() == QKeySequence("Shift+F3")
    window.set_zoom(100)
    window.view_actions["zoom_in"].trigger()
    assert window.zoom.value() == 110


def test_rail_tooltips_show_the_tool_letter(window, tmp_path):
    open_pages(window, tmp_path, ["tips"])
    assert window.mode_buttons["select"].toolTip().endswith("(V)")
    # Texto replaced the separate text and replace buttons; its tooltip keeps the T letter.
    assert window.mode_buttons["replace"].toolTip().endswith("(T)")


def test_toolbar_search_and_arrow_buttons_are_named(window, tmp_path):
    open_pages(window, tmp_path, ["named"])
    toolbar = window.findChild(QToolBar, "MainToolbar")
    tips = {button.toolTip() for button in toolbar.findChildren(QToolButton)}
    assert {"Buscar texto en el documento", "Ir a la coincidencia anterior", "Ir a la coincidencia siguiente", "Vista y zoom"} <= tips
    assert window.search.accessibleName() == "Buscar texto en el documento"
