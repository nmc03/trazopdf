from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from PySide6.QtCore import QSettings, qInstallMessageHandler
from PySide6.QtWidgets import QApplication, QWidget, QPushButton

from pdf_editor.app import EditorWindow
from pdf_editor import icons
from pdf_editor.theme import STYLE, TOKENS, THEMES, apply_theme, build_style, contrast


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    instance.setStyle("Fusion")
    return instance


@pytest.fixture()
def window(app):
    with tempfile.TemporaryDirectory(dir=Path(__file__).parent, prefix="theme-") as folder:
        settings = QSettings(str(Path(folder) / "settings.ini"), QSettings.Format.IniFormat)
        app.setStyleSheet(STYLE)
        win = EditorWindow(settings)
        win.resize(1024, 768)
        win.show()
        app.processEvents()
        yield win
        win.engine.dirty = False
        win.close()
        win.engine.close()
        app.processEvents()


def test_no_unresolved_tokens():
    assert "@" not in STYLE
    assert all(value.startswith("#") and len(value) == 7 for value in TOKENS.values())
    changed = build_style({**TOKENS, "accent": "#123456"})
    assert "#123456" in changed


def test_style_applies_without_parse_warnings(app):
    messages = []
    previous = qInstallMessageHandler(lambda mode, ctx, msg: messages.append(msg))
    try:
        app.setStyleSheet(STYLE)
        widget = QWidget()
        widget.setLayout(__import__("PySide6.QtWidgets", fromlist=["QVBoxLayout"]).QVBoxLayout())
        widget.layout().addWidget(QPushButton("Prueba"))
        widget.show()
        app.processEvents()
        widget.close()
    finally:
        qInstallMessageHandler(previous)
    assert not [m for m in messages if "parse" in m.lower() or "unknown property" in m.lower()]


@pytest.mark.parametrize("mode,visible", [
    ("text", True), ("replace", True),
    ("hand", False), ("image", False), ("highlight", True),
])
def test_text_format_is_contextual(window, mode, visible):
    # The floating format bar replaces the rail panel; markup tools get their own profile.
    window.new_file()
    window.set_mode(mode)
    QApplication.processEvents()
    assert window.view.format_bar.isVisibleTo(window) is visible


def test_collapsed_pages_stay_usable_in_small_window(window):
    window.toggle_pages()
    QApplication.processEvents()
    assert window.pages_collapsed
    assert not window.left_tabs.isVisibleTo(window)
    assert window.pages_toggle.isVisibleTo(window)
    assert window.pages_panel.maximumWidth() == 38
    assert window.stack.width() >= 450
    window.toggle_pages()
    QApplication.processEvents()
    assert window.left_tabs.isVisibleTo(window)
    assert window.stack.width() >= 450


def test_common_buttons_have_tooltips_and_names(window):
    assert window.mode_buttons
    for button in window.mode_buttons.values():
        assert button.toolTip() and button.accessibleName()
    for button in window.findChildren(QPushButton, "DocButton"):
        assert button.toolTip()
    assert window.pages_toggle.toolTip() and window.pages_toggle.accessibleName()
    assert window.search.accessibleName()
    assert window.recents.accessibleName()


def test_small_window_keeps_document_area_visible(window):
    window.engine.new()
    window.refresh()
    QApplication.processEvents()
    page = window.stack.currentWidget()
    assert page is window.view or page.isAncestorOf(window.view)
    assert window.view.isVisible()
    assert window.view.viewport().width() >= 400
    assert window.view.viewport().height() >= 300


TEXT_PAIRS = [
    ("ink", "surface0"), ("ink", "surface1"), ("ink", "surface2"), ("ink", "canvas"), ("ink", "accentsoft"),
    ("inkmuted", "surface0"), ("inkmuted", "surface1"), ("inkmuted", "surface2"), ("inkmuted", "pill"),
    ("inkmuted", "canvas"), ("inkmuted", "accentsoft"), ("onaccent", "accent"), ("onaccent", "accenthover"),
    ("onaccent", "accentpressed"), ("danger", "surface1"),
]
NON_TEXT_PAIRS = [("accent", "surface1"), ("accent", "surface0"), ("accent", "canvas"), ("accent", "pill"),
                  ("borderstrong", "surface1"), ("borderstrong", "surface0")]


@pytest.mark.parametrize("name", sorted(THEMES))
def test_both_themes_meet_wcag_contrast(name):
    tokens = THEMES[name]
    assert set(tokens) == set(TOKENS)
    for foreground, background in TEXT_PAIRS:
        assert contrast(tokens[foreground], tokens[background]) >= 4.5, (name, foreground, background)
    for foreground, background in NON_TEXT_PAIRS:
        assert contrast(tokens[foreground], tokens[background]) >= 3.0, (name, foreground, background)


@pytest.mark.parametrize("name", sorted(THEMES))
def test_each_theme_applies_without_parse_warnings(app, name):
    messages = []
    previous = qInstallMessageHandler(lambda mode, ctx, msg: messages.append(msg))
    try:
        apply_theme(app, name)
        widget = QWidget()
        widget.setLayout(__import__("PySide6.QtWidgets", fromlist=["QVBoxLayout"]).QVBoxLayout())
        widget.layout().addWidget(QPushButton("Prueba"))
        widget.show()
        app.processEvents()
        widget.close()
    finally:
        qInstallMessageHandler(previous)
        apply_theme(app, "light")
    assert not [m for m in messages if "parse" in m.lower() or "unknown property" in m.lower()]


def test_every_tool_and_toolbar_action_has_an_icon(window):
    for button in window.mode_buttons.values():
        assert not button.icon().isNull()
    for button in window.findChildren(QPushButton, "DocButton"):
        assert not button.icon().isNull()
    for key in ("open", "save", "print", "undo", "redo"):
        assert not window.actions[key].icon().isNull()
    assert icons.names()


def test_theme_choice_is_persisted_and_applied(window, app):
    assert window.theme_mode == "system"
    window.set_theme("dark")
    assert window.settings.value("theme") == "dark"
    assert window.theme_actions["dark"].isChecked()
    from pdf_editor import theme
    assert theme.current_name() == "dark"
    window.set_theme("light")
    assert window.settings.value("theme") == "light"
    assert theme.current_name() == "light"
    window.set_theme("system")


TEXT_PAIRS = [
    ("ink", "surface0"), ("ink", "surface1"), ("ink", "surface2"), ("ink", "canvas"), ("ink", "accentsoft"),
    ("inkmuted", "surface0"), ("inkmuted", "surface1"), ("inkmuted", "surface2"), ("inkmuted", "pill"),
    ("inkmuted", "canvas"), ("inkmuted", "accentsoft"), ("onaccent", "accent"), ("onaccent", "accenthover"),
    ("onaccent", "accentpressed"), ("danger", "surface1"),
]
NON_TEXT_PAIRS = [("accent", "surface1"), ("accent", "surface0"), ("accent", "canvas"), ("accent", "pill"),
                  ("borderstrong", "surface1"), ("borderstrong", "surface0")]


@pytest.mark.parametrize("name", sorted(THEMES))
def test_both_themes_meet_wcag_contrast(name):
    tokens = THEMES[name]
    assert set(tokens) == set(TOKENS)
    for foreground, background in TEXT_PAIRS:
        assert contrast(tokens[foreground], tokens[background]) >= 4.5, (name, foreground, background)
    for foreground, background in NON_TEXT_PAIRS:
        assert contrast(tokens[foreground], tokens[background]) >= 3.0, (name, foreground, background)


@pytest.mark.parametrize("name", sorted(THEMES))
def test_each_theme_applies_without_parse_warnings(app, name):
    messages = []
    previous = qInstallMessageHandler(lambda mode, ctx, msg: messages.append(msg))
    try:
        apply_theme(app, name)
        widget = QWidget()
        widget.setLayout(__import__("PySide6.QtWidgets", fromlist=["QVBoxLayout"]).QVBoxLayout())
        widget.layout().addWidget(QPushButton("Prueba"))
        widget.show()
        app.processEvents()
        widget.close()
    finally:
        qInstallMessageHandler(previous)
        apply_theme(app, "light")
    assert not [m for m in messages if "parse" in m.lower() or "unknown property" in m.lower()]


def test_every_tool_and_toolbar_action_has_an_icon(window):
    for button in window.mode_buttons.values():
        assert not button.icon().isNull()
    for button in window.findChildren(QPushButton, "DocButton"):
        assert not button.icon().isNull()
    for key in ("open", "save", "print", "undo", "redo"):
        assert not window.actions[key].icon().isNull()
    assert icons.names()


def test_theme_choice_is_persisted_and_applied(window, app):
    assert window.theme_mode == "system"
    window.set_theme("dark")
    assert window.settings.value("theme") == "dark"
    assert window.theme_actions["dark"].isChecked()
    from pdf_editor import theme
    assert theme.current_name() == "dark"
    window.set_theme("light")
    assert window.settings.value("theme") == "light"
    assert theme.current_name() == "light"
    window.set_theme("system")


TEXT_PAIRS = [
    ("ink", "surface0"), ("ink", "surface1"), ("ink", "surface2"), ("ink", "canvas"), ("ink", "accentsoft"),
    ("inkmuted", "surface0"), ("inkmuted", "surface1"), ("inkmuted", "surface2"), ("inkmuted", "pill"),
    ("inkmuted", "canvas"), ("inkmuted", "accentsoft"), ("onaccent", "accent"), ("onaccent", "accenthover"),
    ("onaccent", "accentpressed"), ("danger", "surface1"),
]
NON_TEXT_PAIRS = [("accent", "surface1"), ("accent", "surface0"), ("accent", "canvas"), ("accent", "pill"),
                  ("borderstrong", "surface1"), ("borderstrong", "surface0")]


@pytest.mark.parametrize("name", sorted(THEMES))
def test_both_themes_meet_wcag_contrast(name):
    tokens = THEMES[name]
    assert set(tokens) == set(TOKENS)
    for foreground, background in TEXT_PAIRS:
        assert contrast(tokens[foreground], tokens[background]) >= 4.5, (name, foreground, background)
    for foreground, background in NON_TEXT_PAIRS:
        assert contrast(tokens[foreground], tokens[background]) >= 3.0, (name, foreground, background)


@pytest.mark.parametrize("name", sorted(THEMES))
def test_each_theme_applies_without_parse_warnings(app, name):
    messages = []
    previous = qInstallMessageHandler(lambda mode, ctx, msg: messages.append(msg))
    try:
        apply_theme(app, name)
        widget = QWidget()
        widget.setLayout(__import__("PySide6.QtWidgets", fromlist=["QVBoxLayout"]).QVBoxLayout())
        widget.layout().addWidget(QPushButton("Prueba"))
        widget.show()
        app.processEvents()
        widget.close()
    finally:
        qInstallMessageHandler(previous)
        apply_theme(app, "light")
    assert not [m for m in messages if "parse" in m.lower() or "unknown property" in m.lower()]


def test_every_tool_and_toolbar_action_has_an_icon(window):
    for button in window.mode_buttons.values():
        assert not button.icon().isNull()
    for button in window.findChildren(QPushButton, "DocButton"):
        assert not button.icon().isNull()
    for key in ("open", "save", "print", "undo", "redo"):
        assert not window.actions[key].icon().isNull()
    assert icons.names()


def test_theme_choice_is_persisted_and_applied(window, app):
    assert window.theme_mode == "system"
    window.set_theme("dark")
    assert window.settings.value("theme") == "dark"
    assert window.theme_actions["dark"].isChecked()
    from pdf_editor import theme
    assert theme.current_name() == "dark"
    window.set_theme("light")
    assert window.settings.value("theme") == "light"
    assert theme.current_name() == "light"
    window.set_theme("system")
