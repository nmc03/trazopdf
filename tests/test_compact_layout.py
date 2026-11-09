from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from PySide6.QtCore import QPoint, QSettings
from PySide6.QtWidgets import QApplication, QScrollArea, QToolBar, QToolButton, QWidget

from pdf_editor.app import EditorWindow
from pdf_editor.theme import STYLE

TOLERANCE = 2
TOOLBAR_LABELS = [
    "Página anterior", "Página siguiente", "Reducir zoom", "Aumentar zoom",
    "Ajustar a la anchura de la página", "Buscar texto en el documento",
    "Ir a la coincidencia siguiente",
]


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    instance.setStyle("Fusion")
    instance.setStyleSheet(STYLE)
    return instance


@pytest.fixture()
def window(app):
    with tempfile.TemporaryDirectory(prefix="compact-layout-", ignore_cleanup_errors=True) as folder:
        settings = QSettings(str(Path(folder) / "settings.ini"), QSettings.Format.IniFormat)
        win = EditorWindow(settings)
        win.resize(1024, 768)
        win.show()
        app.processEvents()
        yield win
        win.engine.dirty = False
        win.close()
        win.engine.close()
        app.processEvents()


def rail_of(win):
    return win.findChild(QScrollArea, "ToolRail")


def test_collapse_keeps_rail_width_stable_and_frees_document_space(window, app):
    rail = rail_of(window)
    rail_before = rail.width()
    document_before = window.stack.width()
    window.toggle_pages()
    app.processEvents()
    assert window.pages_collapsed
    assert abs(rail.width() - rail_before) <= TOLERANCE
    assert window.stack.width() > document_before + 50
    window.toggle_pages()
    app.processEvents()
    assert not window.pages_collapsed
    assert abs(rail.width() - rail_before) <= TOLERANCE
    assert window.pages_panel.width() >= 176 - TOLERANCE
    assert window.left_tabs.isVisibleTo(window)


def test_repeated_fold_and_expand_is_stable(window, app):
    rail = rail_of(window)
    rail_before = rail.width()
    for cycle in range(4):
        window.toggle_pages()
        app.processEvents()
        assert window.pages_collapsed == (cycle % 2 == 0)
        assert abs(rail.width() - rail_before) <= TOLERANCE
    assert not window.pages_collapsed
    assert window.left_tabs.isVisibleTo(window)


def test_text_format_controls_fit_document_view_at_1024(window, app):
    window.new_file()
    window.set_mode("text")
    app.processEvents()
    assert window.view.format_bar.isVisibleTo(window)
    rail = rail_of(window)
    assert rail.widget().width() <= rail.viewport().width() + TOLERANCE
    viewport = window.view.viewport()
    controls = [w for w in window.view.format_bar.findChildren(QWidget) if w.isVisibleTo(window.view.format_bar)]
    assert len(controls) >= 5
    for control in controls:
        origin = control.mapTo(viewport, QPoint(0, 0))
        assert origin.x() >= -TOLERANCE
        assert origin.x() + control.width() <= viewport.width() + TOLERANCE


def test_pages_and_bookmark_tabs_have_full_readable_labels(window, app):
    assert not window.pages_collapsed
    app.processEvents()
    tabs = window.left_tabs
    bar = tabs.tabBar()
    metrics = bar.fontMetrics()
    for index, label in enumerate(["Páginas", "Marcadores"]):
        assert tabs.tabText(index) == label
        rect = bar.tabRect(index)
        assert rect.width() >= metrics.horizontalAdvance(label)
        assert rect.right() <= bar.width() + TOLERANCE


def test_first_run_recents_are_hidden_when_empty(window):
    assert window.stack.currentIndex() == 0
    assert window.recents.count() == 0
    assert not window.recents.isVisibleTo(window)


def test_toolbar_navigation_and_zoom_controls_have_accessible_names(window):
    # Page navigator, zoom and search live in grouped widgets, so look the buttons up inside the toolbar.
    toolbar = window.findChild(QToolBar, "MainToolbar")
    assert toolbar is not None
    named = {}
    for button in toolbar.findChildren(QToolButton):
        if button.toolTip() in TOOLBAR_LABELS:
            named[button.toolTip()] = button.accessibleName()
    assert set(named) == set(TOOLBAR_LABELS)
    for label, accessible in named.items():
        assert accessible == label
    for action in toolbar.actions():
        if action.toolTip():
            widget = toolbar.widgetForAction(action)
            assert widget is not None and widget.accessibleName()


def test_toolbar_fits_at_1024_without_overflow(window):
    toolbar = window.findChild(QToolBar, "MainToolbar")
    extension = toolbar.findChild(QWidget, "qt_toolbar_ext_button")
    assert extension is None or not extension.isVisible()


def test_icon_only_rail_is_56_wide_and_keeps_every_tool_reachable(window, app):
    window.set_rail_collapsed(True)
    app.processEvents()
    rail = rail_of(window)
    assert rail.width() == 56
    for key, button in window.mode_buttons.items():
        assert button.text() == ""
        assert button.toolTip() and button.accessibleName()
        assert not button.icon().isNull()
    window.set_rail_collapsed(False)
    app.processEvents()
    assert rail.width() >= 224
    assert all(button.text() for button in window.mode_buttons.values())


def test_text_tool_keeps_compact_rail_and_shows_format_bar(window, app):
    window.new_file()
    window.set_rail_collapsed(True)
    window.set_mode("text")
    app.processEvents()
    assert window.rail_collapsed
    assert window.view.format_bar.isVisibleTo(window)
