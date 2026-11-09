from __future__ import annotations

import json
import math
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

import pymupdf as fitz
from PySide6.QtCore import Qt, QRectF, QSize, QTimer, QSettings, QEventLoop, QItemSelectionModel, QProcess, QUrl
from PySide6.QtGui import (QAction, QActionGroup, QColor, QFont, QIcon, QImage,
                          QKeySequence, QPainter, QPen, QPixmap, QShortcut, QDesktopServices)
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QPushButton, QToolBar, QSpinBox, QDoubleSpinBox,
    QComboBox, QLineEdit, QSplitter, QListWidget, QListWidgetItem, QTabWidget,
    QScrollArea, QGraphicsView, QGraphicsScene, QFileDialog, QMessageBox,
    QInputDialog, QDialog, QDialogButtonBox, QFormLayout, QTextEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QProgressDialog, QCheckBox,
    QStackedWidget, QColorDialog, QAbstractItemView, QStyle, QFrame, QListView,
    QToolButton, QStyledItemDelegate, QSizePolicy, QStatusBar)
from PySide6.QtPrintSupport import QPrintDialog, QPrinter

from .lang import _
from .engine import PDFEngine, PendingRedactionsError, SecurityPreservationError

from . import __version__, doctools, doctools_dialogs, icons, theme  # noqa: F401
from .theme import STYLE  # noqa: F401
from .canvas import PageView  # noqa: F401
from .floating_bar import next_field_name, open_color_popover, rgb_of, tool_style
from .ui_widgets import RailButton, ThumbnailDelegate, RecentDelegate, make_pill  # noqa: F401
# Module-level helpers live in ui_support; they are re-exported here because tests and callers import them from this module.
from .ui_support import (  # noqa: F401
    ACTION_ICONS,
    CANCELLED,
    JOB_MAX_AGE,
    JOB_PREFIXES,
    OWNER_FILE,
    PAGE_MARGIN,
    RAIL_ACTION_GROUPS,
    RAIL_COMPACT,
    RAIL_WIDE,
    ROOT,
    THEME_CHOICES,
    TOOL_ICONS,
    claim_job_folder,
    format_text_comparison,
    pid_runs_editor,
    pixmap_for,
    purge_stale_jobs,
)
from .ui_menu import UiMenuMixin
from .ui_rail import UiRailMixin
from .ui_navigation import UiNavigationMixin
from .ui_pages import UiPagesMixin
from .ui_tools import UiToolsMixin
from .ui_security import UiSecurityMixin
from .ui_export import UiExportMixin
from .ui_jobs import UiJobsMixin
from .ui_document import UiDocumentMixin
from .ui_tabs import UiTabsMixin
from .ui_dialogs import UiDialogsMixin


class TimedStatusBar(QStatusBar):
    """Temporary messages fade after a few seconds; page and mode live in a permanent label."""
    MESSAGE_MS = 5000
    HISTORY_SIZE = 20

    def __init__(self, parent=None):
        super().__init__(parent)
        self.history = []
        self.on_history = None

    def showMessage(self, text, timeout=0):
        if text and (not self.history or self.history[-1][1] != text):
            self.history = (self.history + [(time.time(), text)])[-self.HISTORY_SIZE:]
        super().showMessage(text, timeout or self.MESSAGE_MS)

    def mousePressEvent(self, event):
        # The message zone is everything left of the permanent widgets.
        if self.on_history is not None and event.button() == Qt.MouseButton.LeftButton and event.position().x() < self.page_zone_left():
            self.on_history()
            return
        super().mousePressEvent(event)

    def page_zone_left(self):
        widgets = [w for w in self.findChildren(QLabel) if w.objectName() == "PageStatus" and w.isVisible()]
        return min((w.x() for w in widgets), default=self.width())


class EditorWindow(UiMenuMixin,
                   UiRailMixin,
                   UiNavigationMixin,
                   UiPagesMixin,
                   UiToolsMixin,
                   UiSecurityMixin,
                   UiExportMixin,
                   UiJobsMixin,
                   UiTabsMixin,
                   UiDocumentMixin,
                   UiDialogsMixin,
                   QMainWindow):
    def __init__(self, settings=None):
        super().__init__()
        self.setObjectName("AppWindow")
        self.init_tab_state()
        self.page = 0
        self.settings = settings if settings is not None else QSettings("Personal", "TrazoPDF")
        self.ink_color = QColor(tool_style(self.settings, "text")["color"])
        self.setWindowTitle("TrazoPDF")
        self.resize(1440, 920)
        if (ROOT / "assets/pdf-editor.ico").exists():
            self.setWindowIcon(QIcon(str(ROOT / "assets/pdf-editor.ico")))
        self.actions = {}
        self.pending_stamp = None
        self.doc_actions = []
        self.search_results = []
        self.search_index = -1
        self.icon_bindings = []
        mode = str(self.settings.value("theme", "system"))
        self.theme_mode = mode if mode in ("system", "light", "dark") else "system"
        theme.apply_theme(QApplication.instance(), self.theme_mode)
        QApplication.instance().styleHints().colorSchemeChanged.connect(self.system_scheme_changed)
        self.rail_collapsed = self.settings.value("railCollapsed", False, type=bool)
        self.build_actions()
        self.build_menu()
        self.build_toolbar()
        self.build_layout()
        self.setAcceptDrops(True)
        self.setStatusBar(TimedStatusBar(self))
        self.statusBar().on_history = self.show_message_history
        self.statusBar().setToolTip(_("Clic para ver los últimos mensajes"))
        self.page_status = QLabel()
        self.page_status.setObjectName("PageStatus")
        self.statusBar().addPermanentWidget(self.page_status)
        self.statusBar().showMessage(_("Todo en tu equipo · Abre un PDF para empezar"))
        geometry = self.settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        self.refresh()

    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, "_shown_once", False):
            self._shown_once = True
            QTimer.singleShot(0, self.clear_initial_focus)

    def clear_initial_focus(self):
        """Keep the keyboard focus ring hidden until the user presses Tab."""
        widget = QApplication.focusWidget()
        if widget is not None and self.isAncestorOf(widget) and not isinstance(widget, QLineEdit):
            widget.clearFocus()

    def has_doc(self):
        return self.engine.doc is not None and not self.engine.doc.is_closed and self.engine.page_count > 0

    def choose(self, title, text, buttons, icon=QMessageBox.Icon.Question, detail="", cancel=None):
        """Message box with custom buttons; returns the label picked, or None for the cancel button / Esc.

        buttons is the list of labels in display order (the first one is the default).
        """
        if cancel is None:
            cancel = _("Cancelar")
        box = QMessageBox(self)
        box.setIcon(icon)
        box.setWindowTitle(title)
        box.setText(text)
        if detail:
            box.setInformativeText(detail)
        made = {}
        for label in buttons:
            role = QMessageBox.ButtonRole.RejectRole if label == cancel else QMessageBox.ButtonRole.ActionRole
            made[label] = box.addButton(label, role)
        if buttons:
            box.setDefaultButton(made[buttons[0]])
        box.exec()
        clicked = box.clickedButton()
        for label, button in made.items():
            if clicked is button:
                return None if label == cancel else label
        return None

    def update_history_actions(self, *args):
        editor = self.view.editor
        self.actions["undo"].setEnabled(editor.document().isUndoAvailable() if editor else self.has_doc() and self.engine.can_undo)
        self.actions["redo"].setEnabled(editor.document().isRedoAvailable() if editor else self.has_doc() and self.engine.can_redo)

    def current_font(self):
        from .canvas import pdf_font
        family = ["Helvetica", "Times", "Courier"][self.font_family.currentIndex()]
        return pdf_font(family, (16 if self.bold.isChecked() else 0) | (2 if self.italic.isChecked() else 0))

    def change(self, function):
        result = function()
        self.search_results = []
        self.refresh()
        return result

    def mode_help(self):
        return {"select": _("Selecciona texto · Ctrl+C para copiar · Doble clic selecciona una palabra"), "edit": _("Arrastra texto o imágenes para mover · Esquinas de imagen para redimensionar · Supr elimina"), "text": _("Haz clic y escribe directamente sobre la página"), "hand": _("Arrastra para mover la página"), "replace": _("Haz clic sobre un texto para editarlo, o en una zona vacía para añadir texto"), "link": _("Arrastra para crear un enlace · Haz clic sobre un enlace para editarlo"), "redact": _("Marca un área; después usa Aplicar censuras"), "ink": _("Dibuja sobre la página; firma visual sin certificado"), "stamp": _("Haz clic para colocar el sello, o arrastra para elegir su tamaño · Elige otra herramienta para cancelar")}.get(self.view.mode, _("Arrastra sobre la página para definir un área"))

    def set_mode(self, mode):
        if not self.view.commit_editor():
            return
        if mode in ("highlight", "underline", "strikeout") and self.view.selected_rects:
            self.run(lambda: self.view.apply_text_markup(mode))
        if mode != "stamp":
            self.pending_stamp = None
        self.view.set_mode(mode)
        for key, button in self.mode_buttons.items():
            button.setChecked(key == mode)
        self.statusBar().showMessage(self.mode_help())
        if self.has_doc():
            self.view.clear_text_selection()
            self.view.reset_transient()
            self.view.populate_text()
            self.refresh_search_highlights()
            self.update_page_status()

    def choose_color(self, anchor=None):
        """Colour palette next to the control that asked for it; no modal colour dialog."""
        self._color_popover = open_color_popover(self, self.settings, self.ink_color.name(), anchor, lambda color: self.view.format_action("color", color))

    def perform_selection(self, mode, rect, point, clicked, ink):
        def operation():
            page = self.engine.doc[self.page]
            if mode == "stamp":
                self.place_stamp(point, None if clicked else rect)
                return
            if mode == "text":
                self.view.begin_editor(point=point, rect=None if clicked else rect)
                return
            if mode == "replace":
                run = self.view.run_at(point) or next((r for r in self.view.runs if r.rect.intersects(rect)), None)
                if run:
                    self.view.begin_editor(run=run)
                else:
                    self.statusBar().showMessage(_("Haz clic sobre un texto para editarlo"))
                return
            if mode == "select":
                if clicked:
                    return
                text = page.get_textbox(rect)
                if text.strip():
                    self.statusBar().showMessage(_("{n} caracteres seleccionados · Ctrl+C o Copiar para copiar", n=len(text)))
                return
            if mode == "ink":
                if len(ink) > 1:
                    style = self.view.tool_style("ink")
                    self.change(lambda: self.engine.add_ink(self.page, ink, rgb_of(style["color"]), style["width"], style["opacity"]))
                else:
                    self.render_page()
                return
            if clicked:
                if mode == "note":
                    rect_local = fitz.Rect(point.x, point.y, point.x + 20, point.y + 20)
                else:
                    raise ValueError(_("Arrastra para definir el área de esta herramienta."))
            else:
                rect_local = rect
            if mode == "image":
                path, _filter = QFileDialog.getOpenFileName(self, _("Insertar imagen"), "", _("Imágenes (*.png *.jpg *.jpeg *.tif *.tiff *.bmp)"))
                if path:
                    self.change(lambda: self.engine.add_image(self.page, rect_local, path))
            elif mode == "link":
                self.edit_link(rect_local)
            elif mode == "crop":
                self.change(lambda: self.engine.crop(self.page, rect_local))
            elif mode == "field":
                existing = {field["name"] for field in self.engine.forms()}
                name = self.view.format_bar.field_name_text() or next_field_name(existing)
                if name in existing:
                    self.statusBar().showMessage(_("Ya existe un campo llamado «{name}». Elige otro nombre en la barra.", name=name))
                    return
                kind = self.view.format_bar.field_kind()
                self.change(lambda: self.engine.add_field(self.page, rect_local, name, kind))
                self.view.format_bar.set_field_name(next_field_name(existing | {name}))
            elif mode == "note":
                style = self.view.tool_style("note")
                xref = self.change(lambda: self.engine.annotate(self.page, rect_local, "note", "", color=rgb_of(style["color"])))
                self.view.open_note_popover(xref, rect_local)
            elif mode in ("rectangle", "ellipse"):
                style = self.view.tool_style(mode)
                fill = rgb_of(style["color"]) if style["fill"] else None
                self.change(lambda: self.engine.annotate(self.page, rect_local, mode, "", color=rgb_of(style["color"]), width=style["width"], opacity=style["opacity"], fill=fill))
            elif mode == "redact":
                self.change(lambda: self.engine.annotate(self.page, rect_local, mode))
        self.run(operation)

    def color_tuple(self):
        return (self.ink_color.redF(), self.ink_color.greenF(), self.ink_color.blueF())

    def undo(self):
        self.change(self.engine.undo)

    def redo(self):
        self.change(self.engine.redo)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        from .worker import run_worker
        run_worker(sys.argv[2])
        return
    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        from .smoke import run_smoke
        run_smoke(sys.argv[2])
        return
    if len(sys.argv) > 1 and sys.argv[1] in ("--batch", "--watch"):
        from .batch import cli_main
        sys.exit(cli_main(sys.argv[1:]))
    purge_stale_jobs()
    app = QApplication(sys.argv)
    app.setApplicationName("TrazoPDF")
    app.setOrganizationName("Personal")
    app.setStyle("Fusion")
    from . import lang
    from .i18n import install_translations
    code = lang.set_language(QSettings("Personal", "TrazoPDF").value("language", "system"))
    install_translations(app, code)
    window = EditorWindow()
    window.show()
    QTimer.singleShot(0, window.start_recovery)
    if len(sys.argv) > 1 and Path(sys.argv[1]).is_file():
        QTimer.singleShot(0, lambda: window.run(lambda: window.open_path(sys.argv[1])))
    sys.exit(app.exec())
