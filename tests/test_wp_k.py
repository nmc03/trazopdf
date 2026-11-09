from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QComboBox, QMenu

from pdf_editor.app import EditorWindow
from pdf_editor.theme import STYLE


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    instance.setStyle("Fusion")
    instance.setStyleSheet(STYLE)
    return instance


@pytest.fixture()
def folder():
    with tempfile.TemporaryDirectory(prefix="wp-k-", ignore_cleanup_errors=True) as path:
        yield Path(path)


def make_window(app, folder):
    settings = QSettings(str(folder / "settings.ini"), QSettings.Format.IniFormat)
    win = EditorWindow(settings)
    win.resize(1100, 760)
    win.show()
    app.processEvents()
    return win


def dispose(app, win):
    win.engine.dirty = False
    win.close()
    win.engine.close()
    app.processEvents()


@pytest.fixture()
def window(app, folder):
    win = make_window(app, folder)
    yield win
    dispose(app, win)


def test_ctrl_y_redoes_and_f1_opens_shortcuts_without_clashes(window):
    redo = window.actions["redo"]
    assert "Ctrl+Y" in [s.toString() for s in redo.shortcuts()]
    assert "Ctrl+Shift+Z" in [s.toString() for s in redo.shortcuts()]
    assert window.actions["shortcuts"].shortcut().toString() == "F1"
    owners = {}
    for action in list(window.actions.values()) + list(window.view_actions.values()):
        for sequence in action.shortcuts():
            assert owners.setdefault(sequence.toString(), action) is action, sequence.toString()
    ayuda = next(a.menu() for a in window.menuBar().actions() if a.text() == "Ayuda")
    assert window.actions["shortcuts"] in ayuda.actions()


def test_shortcuts_dialog_lists_every_window_action_shortcut(window):
    dialog = window.build_shortcuts_dialog()
    listed = {dialog.table.item(row, 1).text() for row in range(dialog.table.rowCount())}
    joined = " / ".join(listed)
    for action in window.actions.values():
        for sequence in action.shortcuts():
            assert sequence.toString(sequence.SequenceFormat.NativeText) in joined, action.text()
    labels = {dialog.table.item(row, 0).text() for row in range(dialog.table.rowCount())}
    assert {"Rehacer", "Seleccionar todo", "Atajos de teclado"} <= labels
    dialog.deleteLater()


def test_select_all_picks_every_thumbnail_when_the_panel_has_focus(app, window):
    window.new_file()
    window.engine.insert_blank(0)
    window.engine.insert_blank(1)
    window.refresh()
    app.processEvents()
    window.thumbnails.setFocus()
    app.processEvents()
    window.actions["selectall"].trigger()
    assert window.thumbnails.count() == 3
    assert len(window.thumbnails.selectedItems()) == 3


def test_select_all_selects_page_text_from_the_document(app, window):
    window.new_file()
    window.view.setFocus()
    window.actions["selectall"].trigger()
    assert window.view.selection_anchor == 0


def test_zoom_presets_combo_drives_the_zoom(app, window):
    assert isinstance(window.zoom_presets, QComboBox)
    assert not window.zoom_presets.isEnabled()
    window.new_file()
    app.processEvents()
    assert window.zoom_presets.isEnabled()
    index = window.zoom_presets.findText("150 %")
    window.zoom_presets.setCurrentIndex(index)
    window.zoom_presets.activated.emit(index)
    assert window.zoom.value() == 150
    assert window.zoom_presets.currentIndex() == 0
    fit = window.zoom_presets.findText("Ajustar anchura")
    window.zoom_presets.activated.emit(fit)
    assert window.zoom_mode == "width"


def test_left_panel_has_five_tabs_and_remembers_the_last_one(app, folder):
    win = make_window(app, folder)
    try:
        titles = [win.left_tabs.tabText(i) for i in range(win.left_tabs.count())]
        assert titles == ["Páginas", "Marcadores", "Comentarios", "Adjuntos", "Enlaces", "Capas", "Campos", "Propiedades"]
        win.left_tabs.setCurrentIndex(4)
        app.processEvents()
    finally:
        dispose(app, win)
    again = make_window(app, folder)
    try:
        assert again.left_tabs.tabText(again.left_tabs.currentIndex()) == "Enlaces"
    finally:
        dispose(app, again)


def test_side_panels_show_document_contents_inline(app, window):
    window.new_file()
    window.engine.annotate(0, __import__("pymupdf").Rect(50, 50, 150, 80), "note", "Revisar esto")
    window.left_tabs.setCurrentWidget(window.side_panels["comments"])
    window.refresh_side_panel(True)
    assert "Revisar esto" in window.comment_list.item(0).text()
    window.left_tabs.setCurrentWidget(window.side_panels["attachments"])
    window.refresh_side_panel(True)
    assert window.attachment_list.item(0).text() == "Sin adjuntos."
    window.left_tabs.setCurrentWidget(window.side_panels["links"])
    window.refresh_side_panel(True)
    assert window.link_list.item(0).text() == "Sin enlaces."
