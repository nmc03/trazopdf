from PySide6.QtWidgets import QPushButton
"""Panel de páginas: miniaturas, acciones sobre la selección, combinar archivos y marcadores en árbol."""
from pdf_editor.toast import ToastBanner
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf as fitz
import pytest
from PySide6.QtCore import QSettings, QSize
from PySide6.QtWidgets import QApplication, QMessageBox

from pdf_editor.app import EditorWindow
from pdf_editor.pages_panel import MergeDialog, ThumbnailList, moved_order, notify


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path):
    w = EditorWindow(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
    w.engine.new()
    w.engine.doc[0].insert_text((72, 100), "uno", fontsize=12)
    w.engine.doc.new_page().insert_text((72, 100), "dos", fontsize=12)
    w.engine.doc.new_page().insert_text((72, 100), "tres", fontsize=12)
    w.engine.dirty = True
    w.refresh()
    yield w
    for tab in w.documents:
        tab.engine.dirty = False
    w.close()
    app.processEvents()


def texts(w):
    return [w.engine.doc[i].get_text().strip() for i in range(w.engine.page_count)]


def select(w, pages):
    w.thumbnails.clearSelection()
    for index in pages:
        w.thumbnails.item(index).setSelected(True)


def make_pdf(path, *labels):
    with fitz.open() as doc:
        for label in labels:
            doc.new_page().insert_text((72, 100), label, fontsize=12)
        doc.save(path)
    return str(path)


def test_moved_order_places_selected_pages_before_target():
    assert moved_order(3, [0], 3) == [1, 2, 0]
    assert moved_order(5, [1], 0) == [1, 0, 2, 3, 4]
    assert moved_order(3, [0, 2], 1) == [0, 2, 1]


def test_drag_moves_pages_as_one_undo_step(window):
    window.move_pages([0], 3)
    assert texts(window) == ["dos", "tres", "uno"]
    assert window.page == 2
    window.undo()
    assert texts(window) == ["uno", "dos", "tres"]


def test_moving_several_selected_pages_keeps_their_order(window):
    window.move_pages([0, 2], 1)
    assert texts(window) == ["uno", "tres", "dos"]


def test_dropping_a_page_on_itself_is_a_no_op(window):
    window.move_pages([1], 1)
    assert texts(window) == ["uno", "dos", "tres"]
    assert not window.engine.can_undo


def test_delete_selected_pages_without_asking(window, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: pytest.fail("no debe preguntar")))
    select(window, [1, 2])
    window.delete_pages()
    assert texts(window) == ["uno"]
    window.undo()
    assert texts(window) == ["uno", "dos", "tres"]


def test_rotate_applies_to_the_selection_only(window):
    select(window, [1])
    window.rotate_selected(-90)
    assert [p.rotation for p in window.engine.doc] == [0, 270, 0]


def test_duplicate_selection_copies_each_page_after_itself(window):
    select(window, [0, 2])
    window.duplicate_pages_selected()
    assert texts(window) == ["uno", "uno", "dos", "tres", "tres"]


def test_blank_page_takes_the_size_of_the_current_page(window):
    window.engine.insert_blank(0, width=300, height=400)
    window.refresh()
    window.goto(1)
    window.insert_blank_here()
    assert window.engine.page_count == 5
    assert round(window.engine.doc[2].rect.width) == 300
    assert round(window.engine.doc[2].rect.height) == 400


def test_thumbnail_size_is_clamped_and_refreshes_icons(window):
    window.thumbnails.set_thumb_width(500)
    assert window.thumbnails.thumb_size.width() == ThumbnailList.MAX_WIDTH
    assert window.thumbnails.item(0).icon().actualSize(QSize(1000, 1000)).width() > 104
    window.thumbnails.set_thumb_width(1)
    assert window.thumbnails.thumb_size.width() == ThumbnailList.MIN_WIDTH


def test_thumbnails_render_in_batches(window):
    for _ in range(30):
        window.engine.insert_blank(window.engine.page_count - 1)
    window.refresh()
    window.load_thumbnails()
    loaded = sum(1 for row in range(window.thumbnails.count()) if not window.thumbnails.item(row).icon().isNull())
    assert 0 < loaded <= window.THUMB_BATCH


def test_dropped_pdf_is_inserted_at_the_drop_position(window, tmp_path):
    path = make_pdf(tmp_path / "nuevo.pdf", "nuevo")
    window.dropped_files([path], 1)
    assert window.engine.page_count == 4
    assert texts(window)[1] == "nuevo"


def test_merge_as_new_document_drops_the_blank_start_page(window, monkeypatch, tmp_path):
    monkeypatch.setattr(window, "confirm_discard", lambda: True)
    path = make_pdf(tmp_path / "dos.pdf", "a", "b")
    window.merge_as_new_document([path])
    assert window.engine.page_count == 2
    assert texts(window) == ["a", "b"]


def test_merge_dialog_lists_files_and_reorders_them(app, tmp_path):
    a = make_pdf(tmp_path / "a.pdf", "a")
    b = make_pdf(tmp_path / "b.pdf", "b1", "b2")
    dialog = MergeDialog(0)
    dialog.add_files([a, b])
    assert dialog.files.count() == 2
    dialog.files.item(1).setSelected(True)
    dialog.move_selected(-1)
    paths, where = dialog.values()
    assert paths == [b, a]
    assert where == "end"
    assert "3 página(s)" in dialog.summary.text()
    dialog.close()


def test_bookmark_tree_round_trip_keeps_nesting(window):
    toc = [[1, "Inicio", 1], [2, "Detalle", 2], [3, "Nota", 2], [1, "Final", 3]]
    window.bookmark_list.set_toc(toc)
    assert window.bookmark_list.to_toc() == toc


def test_new_bookmark_is_saved_after_its_name_is_set(window, app):
    tree = window.bookmark_list
    window.goto(2)
    tree.add_marker(window.page)
    app.processEvents()
    assert window.engine.bookmarks() == []  # not saved until the name is confirmed
    tree.currentItem().setText(0, "Capítulo tres")
    app.processEvents()
    assert [(lvl, title, page) for lvl, title, page, *_ in window.engine.bookmarks()] == [(1, "Capítulo tres", 3)]
    window.undo()
    assert window.engine.bookmarks() == []


def test_deleting_a_bookmark_with_the_delete_key_saves_the_tree(window, app):
    window.engine.set_bookmarks([[1, "A", 1], [2, "B", 2]])
    window.refresh()
    tree = window.bookmark_list
    tree.setCurrentItem(tree.topLevelItem(0))
    tree.topLevelItem(0).setSelected(True)
    tree.delete_selected()
    app.processEvents()
    assert window.engine.bookmarks() == []


def test_notify_shows_a_banner_with_the_undo_action(window):
    calls = []
    notify(window, "2 páginas eliminadas", "Deshacer", lambda: calls.append("undo"))
    banner = window.findChild(ToastBanner)
    assert banner is not None and not banner.isHidden()
    assert "2 páginas eliminadas" in banner.label.text()
    buttons = [b for b in banner.findChildren(QPushButton) if b.text() == "Deshacer"]
    assert buttons, "falta el botón Deshacer"
    buttons[0].click()
    assert calls == ["undo"]
