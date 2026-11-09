"""Visual theme (QSS) for TrazoPDF. Tokens are substituted in Python because QSS has no variables.

Two token sets (light and dark) share the same names. `apply_theme` resolves the user's choice
(system / light / dark), installs the stylesheet and palette and re-tints the icon set.
"""
from __future__ import annotations

import re

LIGHT = {
    "accent": "#0A7A6C", "accenthover": "#08695D", "accentpressed": "#065248", "accentsoft": "#DDF0EC",
    "onaccent": "#FFFFFF", "canvas": "#E6E9EB", "surface0": "#F4F6F7", "surface1": "#FFFFFF",
    "surface2": "#E9EDEE", "pill": "#EEF1F2", "border": "#D9DFE1", "borderstrong": "#848F93",
    "ink": "#1A2225", "inkmuted": "#4B575B", "inkdisabled": "#8B9599", "danger": "#B42318",
    "shadow": "#0B1417",
}

DARK = {
    "accent": "#3FC1AF", "accenthover": "#5ED0C0", "accentpressed": "#2DA695", "accentsoft": "#173C37",
    "onaccent": "#04211D", "canvas": "#141819", "surface0": "#1B2022", "surface1": "#22282B",
    "surface2": "#2C3437", "pill": "#2A3134", "border": "#343D41", "borderstrong": "#7A878C",
    "ink": "#E9EEEF", "inkmuted": "#A7B3B7", "inkdisabled": "#68757A", "danger": "#F2796E",
    "shadow": "#000000",
}

TOKENS = LIGHT
THEMES = {"light": LIGHT, "dark": DARK}
_active = {"name": "light", "tokens": LIGHT}
_asset_paths: dict[str, dict[str, str]] = {}

_QSS = """
QMainWindow, QDialog, QMessageBox { background: @surface0; color: @ink; }
QWidget { font-family: "Segoe UI Variable Text", "Segoe UI", Arial; font-size: 9.5pt; color: @ink; }
QWidget:disabled { color: @inkdisabled; }
QToolTip { background: @surface1; color: @ink; border: 1px solid @borderstrong; border-radius: 6px; padding: 4px 8px; }

QMenuBar { background: @surface1; border-bottom: 1px solid @border; padding: 2px 6px; }
QMenuBar::item { padding: 5px 10px; background: transparent; border-radius: 6px; }
QMenuBar::item:selected { background: @surface2; }
QMenuBar::item:pressed { background: @accentsoft; }
QMenu { background: @surface1; border: 1px solid @border; border-radius: 10px; padding: 6px; }
QMenu::item { padding: 7px 28px 7px 14px; border-radius: 6px; }
QMenu::item:selected { background: @accentsoft; color: @ink; }
QMenu::item:disabled { color: @inkdisabled; background: transparent; }
QMenu::separator { height: 1px; background: @border; margin: 5px 8px; }
QMenu::indicator { width: 14px; height: 14px; left: 4px; }

QToolBar#MainToolbar { background: @surface1; border: 0; border-bottom: 1px solid @border; spacing: 4px; padding: 6px 12px; }
QToolBar#MainToolbar QToolButton { min-width: 28px; min-height: 28px; padding: 2px; border: 2px solid transparent; border-radius: 8px; background: transparent; }
QToolBar#MainToolbar QToolButton:hover { background: @surface2; }
QToolBar#MainToolbar QToolButton:pressed, QToolBar#MainToolbar QToolButton:checked { background: @accentsoft; }
QToolBar#MainToolbar QToolButton:focus { border-color: @accent; }
QToolBar#MainToolbar QToolButton:disabled { background: transparent; }
QToolBar#MainToolbar::separator { background: @border; width: 1px; margin: 6px 8px; }
QToolButton { padding: 4px 6px; border: 2px solid transparent; border-radius: 8px; background: transparent; font-weight: 500; }
QToolButton:hover { background: @surface2; }
QToolButton:pressed, QToolButton:checked { background: @accentsoft; }
QToolButton:focus { border-color: @accent; }

QFrame#Pill { background: @pill; border: 1px solid @border; border-radius: 10px; }
QFrame#Pill QToolButton { min-width: 24px; min-height: 24px; padding: 1px; border: 2px solid transparent; border-radius: 7px; background: transparent; }
QFrame#Pill QToolButton:hover { background: @surface1; }
QFrame#Pill QToolButton:pressed { background: @accentsoft; }
QFrame#Pill QToolButton:focus { border-color: @accent; }
QFrame#Pill QSpinBox { background: transparent; border: 2px solid transparent; border-radius: 6px; padding: 0 2px; min-height: 22px; font-weight: 600; selection-background-color: @accent; selection-color: @onaccent; }
QFrame#Pill QSpinBox::up-button, QFrame#Pill QSpinBox::down-button { width: 0; height: 0; border: 0; }
QFrame#Pill QSpinBox:hover { background: @surface1; }
QFrame#Pill QSpinBox:focus { background: @surface1; border-color: @accent; padding: 0 2px; }
QFrame#Pill QLabel { background: transparent; color: @inkmuted; padding-right: 4px; }

QPushButton { background: @surface1; border: 1px solid @borderstrong; border-radius: 8px; padding: 5px 14px; min-height: 22px; font-weight: 500; }
QPushButton:hover { background: @surface2; }
QPushButton:pressed, QPushButton:checked { background: @accentsoft; border-color: @accent; }
QPushButton:focus { border: 2px solid @accent; padding: 4px 13px; }
QPushButton:disabled { color: @inkdisabled; background: @surface0; border-color: @border; }
QPushButton[primary="true"] { background: @accent; color: @onaccent; border: 1px solid @accent; padding: 9px 22px; font-weight: 600; }
QPushButton[primary="true"]:hover { background: @accenthover; border-color: @accenthover; }
QPushButton[primary="true"]:pressed { background: @accentpressed; border-color: @accentpressed; }
QPushButton[primary="true"]:focus { border: 2px solid @ink; padding: 8px 21px; }
QPushButton[secondary="true"] { padding: 9px 22px; }
QPushButton[secondary="true"]:focus { padding: 8px 21px; }

QPushButton#ModeButton, QPushButton#DocButton { text-align: left; background: transparent; border: 2px solid transparent; border-radius: 8px; padding: 1px 8px; min-height: 18px; font-weight: 400; }
QPushButton#DocButton { color: @inkmuted; }
QPushButton#ModeButton:hover, QPushButton#DocButton:hover { background: @surface2; }
QPushButton#ModeButton:pressed, QPushButton#DocButton:pressed { background: @accentsoft; }
QPushButton#ModeButton:checked { background: @accentsoft; border-color: transparent; padding-left: 10px; font-weight: 600; color: @ink; }
QPushButton#ModeButton:focus, QPushButton#DocButton:focus, QPushButton#ModeButton:checked:focus { border: 2px solid @accent; padding: 1px 8px; }
QPushButton#ModeButton:disabled, QPushButton#DocButton:disabled { color: @inkdisabled; background: transparent; border-color: transparent; }
QPushButton#ModeButton[compact="true"], QPushButton#DocButton[compact="true"], QPushButton#ModeButton[compact="true"]:checked, QPushButton#ModeButton[compact="true"]:focus, QPushButton#DocButton[compact="true"]:focus { text-align: center; padding: 1px 0; }
QPushButton#CollapseButton, QPushButton#RailToggle { background: transparent; border: 2px solid transparent; border-radius: 8px; padding: 2px; min-height: 24px; }
QPushButton#CollapseButton:hover, QPushButton#RailToggle:hover { background: @surface2; }
QPushButton#CollapseButton:focus, QPushButton#RailToggle:focus { border: 2px solid @accent; padding: 2px; }

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit { background: @surface1; border: 1px solid @borderstrong; border-radius: 8px; padding: 4px 8px; min-height: 22px; selection-background-color: @accent; selection-color: @onaccent; }
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover { border-color: @inkmuted; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QTextEdit:focus { border: 2px solid @accent; padding: 3px 7px; }
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled, QTextEdit:disabled { background: @surface0; color: @inkdisabled; border-color: @border; }
QLineEdit#SearchField { background: @pill; border: 1px solid @border; border-radius: 10px; padding: 2px 8px; min-height: 22px; }
QLineEdit#SearchField:hover { border-color: @borderstrong; }
QLineEdit#SearchField QToolButton { min-width: 0; min-height: 0; padding: 0; margin: 0; border: 0; background: transparent; }
QLineEdit#SearchField:focus { background: @surface1; border: 2px solid @accent; padding: 2px 7px; }
QComboBox QAbstractItemView { background: @surface1; border: 1px solid @border; selection-background-color: @accentsoft; selection-color: @ink; outline: 0; }
QComboBox::drop-down { border: 0; width: 22px; }

QListWidget, QTableWidget { background: @surface1; border: 0; outline: 0; }
QListWidget::item { padding: 6px; border: 2px solid transparent; border-radius: 8px; margin: 2px 6px; }
QListWidget::item:hover { background: @surface2; }
QListWidget::item:selected { background: @accentsoft; color: @ink; border: 2px solid @accent; }
QListWidget#ThumbnailList { background: @surface0; }
QListWidget#ThumbnailList::item, QListWidget#ThumbnailList::item:hover, QListWidget#ThumbnailList::item:selected { background: transparent; border: 0; margin: 0; padding: 0; }
QListWidget#RecentList { background: @surface1; border: 1px solid @border; border-radius: 12px; padding: 4px; }
QListWidget#RecentList::item { padding: 8px 10px; margin: 1px 2px; border: 2px solid transparent; border-radius: 8px; }
QListWidget#RecentList::item:selected { border: 2px solid @accent; }

QTabWidget::pane { border: 0; border-top: 1px solid @border; background: @surface0; }
QTabBar { background: @surface0; }
QTabBar::tab { background: @surface0; color: @inkmuted; padding: 8px 6px; min-width: 0; border-bottom: 2px solid transparent; font-weight: 500; }
QTabBar::tab:hover { background: @surface2; color: @ink; }
QTabBar::tab:selected { background: @surface0; color: @ink; border-bottom: 2px solid @accent; font-weight: 600; }
QTabBar::tab:focus { background: @accentsoft; }
QTabBar#DocumentTabs { background: @surface0; border-bottom: 1px solid @border; }
QTabBar#DocumentTabs::tab { background: @surface0; color: @inkmuted; padding: 7px 8px 7px 12px; min-width: 90px; max-width: 220px; border: 0; border-right: 1px solid @border; border-bottom: 2px solid transparent; font-weight: 500; }
QTabBar#DocumentTabs::tab:hover { background: @surface2; color: @ink; }
QTabBar#DocumentTabs::tab:selected { background: @surface1; color: @ink; border-bottom: 2px solid @accent; font-weight: 600; }
QToolButton#TabClose { border: 0; border-radius: 4px; padding: 2px; background: transparent; }
QToolButton#TabClose:hover { background: @accentsoft; }

QGraphicsView { background: @canvas; border: 0; }
QSplitter::handle { background: @border; width: 1px; }
QSplitter::handle:hover { background: @accent; }
QStatusBar { background: @surface1; border-top: 1px solid @border; color: @inkmuted; font-size: 8.5pt; }
QStatusBar::item { border: 0; }

QScrollArea#ToolRail { background: @surface0; border: 0; border-right: 1px solid @border; }
QWidget#ToolPanel { background: @surface0; }
QWidget#TextOptions { background: @surface1; border: 1px solid @border; border-radius: 10px; }
QWidget#TextOptions QLabel { background: transparent; }
QWidget#PagesPanel { background: @surface0; border-left: 1px solid @border; }
QWidget#PagesHeader { background: @surface0; border-bottom: 1px solid @border; }
QLabel#PagesTitle { padding-left: 14px; font-size: 10pt; font-weight: 600; background: transparent; }
QLabel#section { color: @inkmuted; font-weight: 600; font-size: 8.5pt; padding-top: 3px; padding-bottom: 1px; padding-left: 8px; background: transparent; }
QFrame#RailSeparator { background: @border; border: 0; max-height: 1px; min-height: 1px; margin: 3px 12px; }
QLabel#brand { color: @ink; font-size: 11pt; font-weight: 600; background: transparent; }
QLabel#caption { color: @inkmuted; font-size: 8.5pt; background: transparent; }

QWidget#WelcomeView { background: @canvas; }
QFrame#WelcomeCard { background: @surface1; border: 1px solid @border; border-radius: 16px; }
QFrame#WelcomeCard QLabel { background: transparent; }
QLabel#WelcomeTitle { font-family: "Segoe UI Variable Display", "Segoe UI", Arial; font-size: 21pt; font-weight: 600; }
QLabel#WelcomeSubtitle { font-size: 10.5pt; color: @inkmuted; }
QFrame#DropZone { background: @surface0; border: 1px dashed @borderstrong; border-radius: 12px; }
QFrame#DropZone QLabel { background: transparent; color: @inkmuted; }
QLabel#WelcomeHeading { color: @inkmuted; font-weight: 600; font-size: 9pt; background: transparent; }

QListWidget#ComparisonPages { background: @surface1; border: 1px solid @border; border-radius: 10px; padding: 4px; }
QScrollArea#ComparisonPanel { background: @canvas; border: 1px solid @border; border-radius: 10px; }
QScrollArea#ComparisonPanel > QWidget > QWidget { background: @canvas; }
QScrollArea#ComparisonPanel QLabel { background: transparent; color: @inkmuted; }
QHeaderView::section { background: @surface2; border: 0; border-bottom: 1px solid @border; padding: 6px; font-weight: 600; }
QProgressBar { background: @surface2; border: 1px solid @border; border-radius: 6px; text-align: center; }
QProgressBar::chunk { background: @accent; border-radius: 5px; }
QScrollArea#ToolRail[compact="true"] QScrollBar:vertical { width: 6px; }
QScrollArea#ToolRail[compact="true"] QScrollBar::handle:vertical { margin: 1px; border-radius: 2px; }
QScrollBar:vertical { background: transparent; width: 12px; margin: 0; }
QScrollBar:horizontal { background: transparent; height: 12px; margin: 0; }
QScrollBar::handle:vertical { background: @borderstrong; border-radius: 4px; min-height: 28px; margin: 2px; }
QScrollBar::handle:horizontal { background: @borderstrong; border-radius: 4px; min-width: 28px; margin: 2px; }
QScrollBar::handle:hover { background: @inkmuted; }
QScrollBar::handle:pressed { background: @accent; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
"""

# Spin and combo arrows need image files; they are written per theme by apply_theme().
_ASSET_QSS = """
QSpinBox::up-button, QDoubleSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right; width: 20px; border: 0; margin: 3px 3px 0 0; }
QSpinBox::down-button, QDoubleSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right; width: 20px; border: 0; margin: 0 3px 3px 0; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: url(@chevronup); width: 10px; height: 10px; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: url(@chevrondown); width: 10px; height: 10px; }
QSpinBox::up-arrow:disabled, QSpinBox::down-arrow:disabled { image: none; }
QFrame#Pill QSpinBox::up-button, QFrame#Pill QSpinBox::down-button { width: 0; height: 0; border: 0; margin: 0; }
QFrame#Pill QSpinBox::up-arrow, QFrame#Pill QSpinBox::down-arrow { image: none; width: 0; height: 0; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: center right; border: 0; width: 24px; }
QComboBox::down-arrow { image: url(@chevrondown); width: 10px; height: 10px; }
"""


def build_style(tokens: dict[str, str] | None = None, assets: dict[str, str] | None = None) -> str:
    values = {**(tokens or TOKENS), **(assets or {})}
    sheet = _QSS + (_ASSET_QSS if assets else "")
    return re.sub(r"@([a-z0-9]+)", lambda m: values[m.group(1)], sheet)


def write_assets(tokens: dict[str, str], name: str) -> dict[str, str]:
    """Render the arrow glyphs used by spin boxes and combo boxes; returns QSS-ready file paths."""
    import tempfile
    from pathlib import Path
    from . import icons
    folder = Path(tempfile.gettempdir()) / "pdf-editor-ui"
    folder.mkdir(parents=True, exist_ok=True)
    paths = {}
    for key, glyph in (("chevronup", "chevron-up"), ("chevrondown", "chevron-down")):
        base = folder / f"{glyph}-{name}.png"
        icons.pixmap(glyph, tokens["inkmuted"], 12, 1.0).save(str(base))
        icons.pixmap(glyph, tokens["inkmuted"], 12, 2.0).save(str(folder / f"{glyph}-{name}@2x.png"))
        paths[key] = base.as_posix()
    return paths


STYLE = build_style()


def luminance(color: str) -> float:
    def channel(value: int) -> float:
        value /= 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(foreground: str, background: str) -> float:
    a, b = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def current_tokens() -> dict[str, str]:
    return _active["tokens"]


def current_name() -> str:
    return _active["name"]


def resolve_mode(mode: str, app=None) -> str:
    """Map 'system' | 'light' | 'dark' to 'light' or 'dark'."""
    if mode in THEMES:
        return mode
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        app = app or QApplication.instance()
        return "dark" if app.styleHints().colorScheme() == Qt.ColorScheme.Dark else "light"
    except Exception:
        return "light"


def build_palette(tokens: dict[str, str]):
    from PySide6.QtGui import QColor, QPalette
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: "surface0", QPalette.ColorRole.WindowText: "ink",
        QPalette.ColorRole.Base: "surface1", QPalette.ColorRole.AlternateBase: "surface2",
        QPalette.ColorRole.Text: "ink", QPalette.ColorRole.Button: "surface1",
        QPalette.ColorRole.ButtonText: "ink", QPalette.ColorRole.ToolTipBase: "surface1",
        QPalette.ColorRole.ToolTipText: "ink", QPalette.ColorRole.Highlight: "accent",
        QPalette.ColorRole.HighlightedText: "onaccent", QPalette.ColorRole.Link: "accent",
        QPalette.ColorRole.PlaceholderText: "inkmuted", QPalette.ColorRole.BrightText: "danger",
    }
    for role, token in roles.items():
        palette.setColor(role, QColor(tokens[token]))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(tokens["inkdisabled"]))
    return palette


def apply_theme(app, mode: str = "system") -> str:
    """Install stylesheet, palette and icon tint for `mode`; returns the resolved name ('light' or 'dark')."""
    from PySide6.QtCore import Qt
    from . import icons
    name = resolve_mode(mode, app)
    tokens = THEMES[name]
    _active.update(name=name, tokens=tokens)
    hints = app.styleHints()
    try:
        if mode == "system":
            hints.unsetColorScheme()
        else:
            hints.setColorScheme(Qt.ColorScheme.Dark if name == "dark" else Qt.ColorScheme.Light)
    except Exception:
        pass
    icons.set_palette(tokens)
    palette = build_palette(tokens)
    if app.palette() != palette:
        app.setPalette(palette)
    current = app.styleSheet()
    # Re-installing a sheet re-polishes every live widget, so only touch it on a real change. The plain
    # sheet (STYLE, without arrow images) counts as installed for its theme, for callers that set it themselves.
    if current != build_style(tokens):
        if name not in _asset_paths:
            try:
                _asset_paths[name] = write_assets(tokens, name)
            except Exception:
                _asset_paths[name] = {}   # no writable temp folder: the plain sheet, without arrow images
        sheet = build_style(tokens, _asset_paths[name] or None)
        if current != sheet:
            app.setStyleSheet(sheet)
    return name
