"""Continuous scrolling: all pages in one scene, lazy pixmaps, current page from the view, and the editing paths on other pages."""
import os
import time
import tracemalloc

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf as fitz
import pytest
from PySide6.QtCore import QPointF, QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from pdf_editor.app import EditorWindow
from pdf_editor.canvas import LAZY_CACHE_SIZE
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


def settle(window, rounds=3):
    """Lets the throttled view tick run until it has nothing left to draw."""
    for _ in range(rounds):
        QTest.qWait(40)
        window.continuous_view_moved()
        QApplication.processEvents()


def scroll_to(window, index):
    """Scrolls like the user does: with the scroll bar, not with the page box."""
    rect = window.view.page_geometry[index]
    bar = window.view.verticalScrollBar()
    bar.setValue(int(rect.top() - window.view.sceneRect().top()))
    settle(window)


def scene_point_of(window, index, rect):
    """Scene position of a rectangle given in page coordinates."""
    scale = window.view.scale_factor
    r = fitz.Rect(rect)
    origin = window.view.page_origin[index]
    return QPointF(origin.x() + r.x0 * scale, origin.y() + r.y0 * scale), QPointF(origin.x() + r.x1 * scale, origin.y() + r.y1 * scale)


def test_continuous_layout_stacks_every_page_and_is_remembered(window, tmp_path):
    open_pages(window, tmp_path, ["one", "two", "three"])
    window.view_actions["continuous"].trigger()
    assert window.view_layout == "continuous"
    assert window.is_continuous()
    assert window.view.lazy
    assert set(window.view.page_geometry) == {0, 1, 2}
    tops = [window.view.page_geometry[index].top() for index in range(3)]
    assert tops == sorted(tops) and len(set(tops)) == 3
    # The gap between pages is the same as in the other layouts.
    assert tops[1] - window.view.page_geometry[0].bottom() == pytest.approx(16)
    assert window.settings.value("viewLayout") == "continuous"
    assert window.view_actions["continuous"].isChecked()
    assert window.visible_pages() == window.view.onscreen_pages()


def test_scrolling_moves_the_current_page_and_the_page_box_and_thumbnails(window, tmp_path):
    open_pages(window, tmp_path, [f"page {number}" for number in range(6)])
    window.view_actions["continuous"].trigger()
    assert window.page == 0
    scroll_to(window, 3)
    assert window.page == 3
    assert window.page_spin.value() == 4
    assert window.thumbnails.currentRow() == 3
    scroll_to(window, 5)
    assert window.page == 5
    scroll_to(window, 0)
    assert window.page == 0


def test_the_page_that_fills_most_of_the_view_is_current(window, tmp_path):
    open_pages(window, tmp_path, [f"page {number}" for number in range(4)])
    window.view_actions["continuous"].trigger()
    view = window.view
    # Half of page 1 and most of page 2 on screen: page 2 wins.
    top = view.page_geometry[1].top() + view.page_geometry[1].height() * 0.5
    view.verticalScrollBar().setValue(int(top - view.sceneRect().top()))
    settle(window)
    on_screen = view.onscreen_pages()
    assert 1 in on_screen and 2 in on_screen
    assert window.page == view.most_visible_page(on_screen)


def test_only_visible_pages_are_drawn_and_the_rest_stay_placeholders(window, tmp_path):
    open_pages(window, tmp_path, [f"page {number}" for number in range(40)])
    window.view_actions["continuous"].trigger()
    view = window.view
    settle(window)
    assert set(view.page_items) <= {0, 1, 2}
    assert 0 in view.page_items
    scroll_to(window, 20)
    assert set(view.page_items) <= set(range(19, 23))
    assert 20 in view.page_items
    # The placeholder of a page that is not drawn has the size of the page.
    placeholder_rects = [item.rect() for item in view.scene().items() if item.zValue() == -1]
    assert len(placeholder_rects) == 40
    assert placeholder_rects[39].height() == pytest.approx(view.page_geometry[39].height())


def test_pixmap_cache_is_small_while_scrolling_through_the_document(window, tmp_path):
    open_pages(window, tmp_path, [f"page {number}" for number in range(30)])
    window.view_actions["continuous"].trigger()
    largest = 0
    for index in range(0, 30, 2):
        scroll_to(window, index)
        largest = max(largest, len(window.view.page_cache))
        assert len(window.view.page_items) <= 5
    assert largest <= LAZY_CACHE_SIZE


def test_stale_renders_are_dropped_after_a_fast_scroll(window, tmp_path):
    open_pages(window, tmp_path, [f"page {number}" for number in range(30)])
    window.view_actions["continuous"].trigger()
    settle(window)
    rendered = []
    original = window.render_continuous_pixmap

    def counting(index):
        rendered.append(index)
        return original(index)

    window.render_continuous_pixmap = counting
    try:
        # Jump far away at once: the pages passed on the way are never drawn.
        scroll_to(window, 25)
    finally:
        window.render_continuous_pixmap = original
    assert 1 not in rendered and 10 not in rendered
    assert 25 in rendered or 25 in window.view.page_items


def test_three_hundred_pages_open_quickly_and_stay_light(window, tmp_path):
    open_pages(window, tmp_path, ["short"])
    window.view_actions["continuous"].trigger()
    path = make_pdf(tmp_path / "long.pdf", [f"page {number}" for number in range(300)])
    tracemalloc.start()
    try:
        started = time.perf_counter()
        window.open_path(path)
        QApplication.processEvents()
        elapsed = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert window.engine.page_count == 300
    assert elapsed < 2.5
    assert peak < 200 * 1024 * 1024
    assert len(window.view.page_items) <= 4
    assert len(window.view.page_cache) <= LAZY_CACHE_SIZE
    assert len(window.view.page_geometry) == 300


def test_go_to_page_scrolls_to_it(window, tmp_path):
    open_pages(window, tmp_path, [f"page {number}" for number in range(25)])
    window.view_actions["continuous"].trigger()
    window.goto(20)
    settle(window)
    assert window.page == 20
    assert window.page_spin.value() == 21
    top = window.view.mapFromScene(window.view.page_geometry[20].topLeft()).y()
    assert 0 <= top <= window.view.viewport().height() / 2
    window.goto(2)
    settle(window)
    assert window.page == 2


def test_search_highlights_every_match_across_pages(window, tmp_path):
    open_pages(window, tmp_path, ["alpha", "needle one", "beta", "gamma", "needle two"])
    window.view_actions["continuous"].trigger()
    window.search_bar.field.setText("needle")
    window.find_text()
    assert [index for index, _ in window.search_results] == [1, 4]
    settle(window)
    assert window.page == 1
    assert len(window.search_items) >= 1
    window.search_navigate(True)
    settle(window)
    assert window.page == 4
    window.search_navigate(True)
    settle(window)
    assert window.page == 1


def test_text_selection_works_on_the_second_page(window, tmp_path):
    open_pages(window, tmp_path, ["first page", "second page words"])
    window.view_actions["continuous"].trigger()
    settle(window)
    rect = fitz.Rect(window.engine.doc[1].search_for("second")[0])
    start, _ = scene_point_of(window, 1, rect)
    end_rect = fitz.Rect(window.engine.doc[1].search_for("words")[0])
    _, end = scene_point_of(window, 1, end_rect)
    viewport = window.view.viewport()
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, window.view.mapFromScene(start))
    QTest.mouseMove(viewport, window.view.mapFromScene(end))
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, window.view.mapFromScene(end))
    assert window.page == 1
    assert "second" in window.view.selected_text


def test_clicking_another_page_makes_it_current_and_edits_it(window, tmp_path):
    open_pages(window, tmp_path, ["one", "two", "three"])
    window.view_actions["continuous"].trigger()
    settle(window)
    center = window.view.page_geometry[2].center()
    QTest.mouseClick(window.view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, window.view.mapFromScene(center))
    assert window.page == 2
    assert window.view.page_offset == window.view.page_origin[2]


def test_inline_text_is_added_to_the_page_under_the_pointer(window, tmp_path):
    open_pages(window, tmp_path, ["one", "two", "three"])
    window.view_actions["continuous"].trigger()
    settle(window)
    window.set_mode("text")
    center = window.view.page_geometry[1].center()
    point = window.view.mapFromScene(QPointF(center.x() - 150, window.view.page_geometry[1].top() + 200))
    QTest.mouseClick(window.view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    assert window.page == 1
    assert window.view.editor is not None
    window.view.editor.setPlainText("nota")
    window.view.commit_editor()
    QApplication.processEvents()
    assert "nota" in window.engine.doc[1].get_text()
    assert "nota" not in window.engine.doc[0].get_text()


def test_zoom_fit_width_uses_the_current_page(window, tmp_path):
    open_pages(window, tmp_path, ["a", "b", "c"])
    window.view_actions["continuous"].trigger()
    window.fit_width()
    expected = window.fit_zoom("width")
    assert window.zoom_mode == "width"
    assert abs(window.zoom.value() - expected) <= 1
    view = window.view
    vbar = view.verticalScrollBar()
    available = view.viewport().width() + (vbar.width() if vbar.isVisible() else 0) - 2 * PAGE_MARGIN - 8
    assert view.page_geometry[0].width() <= available + 2
    assert view.page_geometry[0].width() >= available - 8   # el zoom es entero: un paso del 1 % son unos 5 px


def test_zoom_keeps_the_view_near_the_same_place(window, tmp_path):
    open_pages(window, tmp_path, [f"page {number}" for number in range(10)])
    window.view_actions["continuous"].trigger()
    window.set_zoom(100)
    scroll_to(window, 6)
    before = window.view.mapToScene(window.view.viewport().rect().center()).y() / window.view.scale_factor
    window.set_zoom(150)
    settle(window)
    after = window.view.mapToScene(window.view.viewport().rect().center()).y() / window.view.scale_factor
    assert abs(after - before) < 60


def test_two_page_continuous_pairs_pages_in_rows(window, tmp_path):
    open_pages(window, tmp_path, [f"page {number}" for number in range(12)])
    window.view_actions["double_continuous"].trigger()
    assert window.view_layout == "double_continuous"
    view = window.view
    assert view.page_geometry[0].top() == view.page_geometry[1].top()
    assert view.page_geometry[1].left() > view.page_geometry[0].left()
    assert view.page_geometry[2].top() > view.page_geometry[0].bottom()
    assert view.page_geometry[10].top() > view.page_geometry[8].bottom()
    window.goto(4)
    settle(window)
    assert window.page == 4
    assert window.row_pages() == [4, 5]
    assert window.thumbnails.currentRow() == 4
    scroll_to(window, 9)
    assert window.page in (8, 9, 10)      # la fila visible depende del ancho disponible


def test_layout_change_keeps_the_current_page_in_view(window, tmp_path):
    open_pages(window, tmp_path, [f"page {number}" for number in range(8)])
    window.goto(5)
    window.view_actions["continuous"].trigger()
    settle(window)
    assert window.page == 5
    rect = window.view.page_geometry[5]
    visible = window.view.mapFromScene(rect.center()).y()
    assert 0 <= visible <= window.view.viewport().height()
    window.view_actions["single"].trigger()
    assert window.view_layout == "single"
    assert window.page == 5
    assert not window.view.lazy
