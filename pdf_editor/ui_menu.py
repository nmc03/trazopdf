from __future__ import annotations

import hashlib
import json
import threading
from datetime import date, datetime

import pymupdf as fitz
from PySide6.QtCore import QObject, QRectF, QSize, QStandardPaths, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QFont, QKeySequence, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QMessageBox,
    QAbstractItemView, QApplication, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListView,
    QListWidget, QListWidgetItem, QMenu, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QSplitter,
    QStackedWidget, QStyle, QTabBar, QTabWidget, QToolBar, QToolButton, QVBoxLayout, QWidget,
)
from pathlib import Path

from . import accessibility_dialog, autofields, guided, icons, theme
from .bookmarks_panel import BookmarksPanel
from .canvas import PageView
from .lang import _, N_
from .pages_panel import ThumbnailList
from .search_bar import SearchBar
from .ui_support import ACTION_ICONS, RAIL_WIDE, THEME_CHOICES
from .ui_widgets import RecentDelegate, make_pill


def relative_day(stamp, today=None):
    """"hoy", "ayer" or a dd/mm/aaaa date for a unix timestamp; empty when unknown."""
    if not stamp:
        return ""
    day = datetime.fromtimestamp(float(stamp)).date()
    days = ((today or date.today()) - day).days
    return _("hoy") if days == 0 else _("ayer") if days == 1 else day.strftime("%d/%m/%Y")


def recent_thumb_path(path):
    """Cache file for the first-page thumbnail; the key follows size and mtime so edits refresh it."""
    try:
        info = Path(path).stat()
    except OSError:
        return None
    key = hashlib.sha1(f"{Path(path).resolve()}|{info.st_size}|{info.st_mtime_ns}".encode("utf-8")).hexdigest()
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation) or str(Path.home() / ".pdf-editor-cache")
    return Path(base) / "recent-thumbs" / f"{key}.png"


def render_recent_thumb(path, target):
    """Draws page 1 small into target (png). Skips missing or encrypted files. Returns True when written."""
    try:
        with fitz.open(path) as doc:
            if doc.needs_pass or doc.is_encrypted or not len(doc):
                return False
            page = doc[0]
            zoom = 96 / max(page.rect.height, 1)
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        pix.save(str(target))
        return True
    except Exception:
        return False


class RecentThumbs(QObject):
    """Builds missing thumbnails on a worker thread and tells the interface when one is ready."""
    ready = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pending = set()

    def request(self, path):
        target = recent_thumb_path(path)
        if target is None or target.is_file() or path in self.pending:
            return
        self.pending.add(path)

        def work():
            done = render_recent_thumb(path, target)
            self.pending.discard(path)
            if done:
                self.ready.emit(path)

        threading.Thread(target=work, daemon=True).start()


class RecentInfoDelegate(RecentDelegate):
    """Recent row with thumbnail (when cached), name, last use and folder."""

    def paint(self, painter, option, index):
        tokens = theme.current_tokens()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        row = QRectF(option.rect).adjusted(2, 1, -2, -1)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected or hovered:
            painter.setPen(QPen(QColor(tokens["accent"]), 2) if selected else Qt.PenStyle.NoPen)
            painter.setBrush(QColor(tokens["surface2"]))
            painter.drawRoundedRect(row.adjusted(1, 1, -1, -1), 8, 8)
        tile = QRectF(row.left() + 10, row.center().y() - 22, 36, 44)
        thumb = index.data(Qt.ItemDataRole.DecorationRole)
        if isinstance(thumb, QPixmap) and not thumb.isNull():
            painter.drawPixmap(tile.toRect(), thumb.scaled(tile.size().toSize(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            painter.setPen(QPen(QColor(tokens["border"]), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(tile)
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(tokens["accentsoft"]))
            painter.drawRoundedRect(tile, 9, 9)
            glyph = icons.pixmap("file", tokens["accent"], 20, painter.device().devicePixelRatioF())
            painter.drawPixmap(QRectF(tile.center().x() - 10, tile.center().y() - 10, 20, 20).toRect(), glyph)
        text_left = tile.right() + 12
        width = row.right() - text_left - 8
        path = str(index.data(Qt.ItemDataRole.UserRole) or "")
        when = str(index.data(Qt.ItemDataRole.UserRole + 1) or "")
        small = QFont(option.font)
        small.setPointSizeF(max(8.0, option.font.pointSizeF() - 1))
        painter.setFont(small)
        when_width = painter.fontMetrics().horizontalAdvance(when) + 4 if when else 0
        painter.setPen(QColor(tokens["inkmuted"]))
        painter.drawText(QRectF(row.right() - 8 - when_width, row.top() + 7, when_width, 20), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, when)
        name_font = QFont(option.font)
        name_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(name_font)
        painter.setPen(QColor(tokens["inkmuted"] if index.data(Qt.ItemDataRole.UserRole + 2) else tokens["ink"]))
        name_room = max(20, width - when_width - 8)
        name = painter.fontMetrics().elidedText(str(index.data(Qt.ItemDataRole.DisplayRole)), Qt.TextElideMode.ElideMiddle, int(name_room))
        painter.drawText(QRectF(text_left, row.top() + 7, name_room, 20), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, name)
        painter.setFont(small)
        painter.setPen(QColor(tokens["inkmuted"]))
        folder = painter.fontMetrics().elidedText(str(Path(path).parent), Qt.TextElideMode.ElideLeft, int(width))
        painter.drawText(QRectF(text_left, row.top() + 28, width, 18), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, folder)
        painter.restore()

    def sizeHint(self, option, index):
        return QSize(100, 56)


class SideTabBar(QTabBar):
    """Five tabs do not fit the narrow panel: ask for room for the first two and scroll the rest."""

    def sizeHint(self):
        hint = super().sizeHint()
        first_two = sum(self.tabSizeHint(i).width() for i in range(min(2, self.count())))
        hint.setWidth(min(hint.width(), first_two))
        return hint

    def minimumSizeHint(self):
        return QSize(0, super().minimumSizeHint().height())


class UiMenuMixin:
    """Actions, menus, toolbar, tool rail and welcome screen."""

    def action(self, key, label, handler, shortcut=None, document=True):
        action = QAction(label, self)
        action.triggered.connect(lambda _=False: self.run(lambda: self.run_action(key, handler)))
        if shortcut:
            keys = [shortcut] if isinstance(shortcut, str) else shortcut
            action.setShortcuts([QKeySequence(key_text) for key_text in keys])
        self.actions[key] = action
        if document:
            self.doc_actions.append(action)
        return action

    def build_actions(self):
        for key, label, handler, shortcut, doc in [
            ("open", _("Abrir…"), self.open_file, "Ctrl+O", False),
            ("new", _("Nuevo PDF"), self.new_file, "Ctrl+N", False),
            ("save", _("Guardar"), self.save, "Ctrl+S", True),
            ("saveas", _("Guardar como…"), lambda: self.save(True), "Ctrl+Shift+S", True),
            ("print", _("Imprimir…"), self.print_document, "Ctrl+P", True),
            ("undo", _("Deshacer"), self.undo, "Ctrl+Z", True),
            ("redo", _("Rehacer"), self.redo, ("Ctrl+Shift+Z", "Ctrl+Y"), True),
            ("selectall", _("Seleccionar todo"), self.select_all, "Ctrl+A", True),
            ("editpdf", _("Editar PDF"), lambda: self.set_mode("edit"), "Ctrl+E", True),
            ("merge", _("Combinar archivos…"), self.merge, None, True),
            ("extract", _("Extraer páginas…"), self.extract, None, True),
            ("split", _("Dividir en archivos…"), self.split, None, True),
            ("delete", _("Eliminar páginas"), self.delete_pages, None, True),
            ("duplicate", _("Duplicar página"), lambda: self.change(lambda: self.engine.duplicate_page(self.page)), None, True),
            ("blank", _("Insertar página en blanco"), lambda: self.change(lambda: self.engine.insert_blank(self.page)), None, True),
            ("rotate", _("Girar 90°"), self.rotate, "Ctrl+R", True),
            ("watermark", _("Marca de agua…"), self.watermark, None, True),
            ("number", _("Numerar páginas…"), self.number_pages, None, True),
            ("redactions", _("Aplicar censuras"), self.apply_redactions, None, True),
            ("sanitize", _("Eliminar datos ocultos…"), self.sanitize, None, True),
            ("anonymize", _("Anonimizar documento…"), self.anonymize, None, True),
            ("protect", _("Guardar con contraseña…"), self.protect, None, True),
            ("unprotect", _("Guardar copia sin contraseña…"), self.unprotect, None, True),
            ("metadata", _("Propiedades…"), self.metadata, "Alt+Return", True),
            ("forms", _("Rellenar formularios…"), self.forms_dialog, None, True),
            ("attachments", _("Archivos adjuntos…"), self.attachments_dialog, None, True),
            ("bookmarks", _("Editar marcadores"), self.focus_bookmarks, None, True),
            ("comments", _("Comentarios y anotaciones…"), self.comments_dialog, None, True),
            ("links", _("Enlaces del documento…"), self.links_dialog, None, True),
            ("ocr", _("Reconocer texto (OCR)…"), self.ocr, None, True),
            ("compare", _("Comparar PDFs…"), self.compare, None, True),
            ("comparetext", _("Comparar documentos…"), self.compare_documents, None, True),
            ("check", _("Comprobar documento…"), self.check_document, None, True),
            ("optimize", _("Optimizar tamaño…"), self.optimize, None, True),
            ("flatten", _("Aplanar…"), self.flatten, None, True),
            ("headerfooter", _("Encabezado y pie de página…"), self.header_footer, None, True),
            ("bates", _("Numeración Bates…"), self.bates, None, True),
            ("redactsearch", _("Buscar y censurar…"), self.redact_search, None, True),
            ("pagelabels", _("Etiquetas de página…"), self.page_labels, None, True),
            ("insertpage", _("Insertar página…"), self.insert_page, None, True),
            ("stamp", _("Sellos…"), self.stamp, None, True),
            ("sign", _("Firmar con certificado…"), self.sign, None, True),
            ("signatures", _("Examinar firmas…"), self.signatures, None, True),
            ("export", _("Exportar…"), self.export, None, True),
            ("export_text", _("Texto (.txt)"), lambda: self.export_as("export_text"), None, True),
            ("export_docx", _("Word (.docx)"), lambda: self.export_as("export_docx"), None, True),
            ("export_xlsx", _("Excel (.xlsx)"), lambda: self.export_as("export_xlsx"), None, True),
            ("export_pptx", _("PowerPoint (.pptx)"), lambda: self.export_as("export_pptx"), None, True),
            ("export_images", _("Imágenes…"), self.export_images, None, True),
            ("images", _("Crear PDF desde imágenes…"), self.from_images, None, False),
            ("office", _("Crear PDF desde Office…"), self.from_office, None, False),
            ("batch", _("Procesar varios PDFs…"), self.batch, None, False),
            ("measure", _("Medir"), self.start_measure, "Ctrl+Alt+M", True),
            ("guided", _("Acciones guiadas…"), lambda: guided.open_guided(self), None, False),
            ("accessibility", _("Comprobar accesibilidad…"), lambda: accessibility_dialog.open_accessibility(self), None, True),
            ("autofields", _("Detectar campos"), lambda: autofields.open_detector(self), None, True),
            ("close", _("Cerrar documento"), self.close_document, "Ctrl+W", True),
            ("savecopy", _("Guardar una copia…"), lambda: self.save_copy(), "Ctrl+Alt+S", True),
            ("revert", _("Revertir"), lambda: self.revert_document(), None, True),
            ("quit", _("Salir"), lambda: self.close(), "Ctrl+Q", False),
            ("shortcuts", _("Atajos de teclado"), self.shortcuts_dialog, "F1", False),
            ("about", _("Acerca de TrazoPDF"), self.about, None, False),
        ]:
            self.action(key, label, handler, shortcut, doc)

    def start_measure(self):
        self.set_mode("measure")
        if self.view.mode == "measure":
            self.statusBar().showMessage(_("Arrastra sobre la página para medir una distancia · Elige Área para marcar vértices"))

    def build_recent_menu(self, parent):
        menu = QMenu(_("Abrir reciente"), parent)
        menu.aboutToShow.connect(self.fill_recent_menu)
        self.recent_submenu = menu
        return menu

    def fill_recent_menu(self):
        """Lists the recent files; the ones that no longer exist are marked "No disponible" with a way to drop them."""
        menu = self.recent_submenu
        menu.clear()
        recent = self.settings.value("recent", [], type=list)
        for path in recent:
            if Path(path).is_file():
                when = relative_day(self.recent_used().get(path))
                action = menu.addAction("  ·  ".join(part for part in (Path(path).name, when, Path(path).parent.name or str(Path(path).parent)) if part))
                action.setToolTip(path)
                action.triggered.connect(lambda _=False, p=path: self.run(lambda: self.open_path(p)))
            else:
                gone = menu.addMenu(_("{name}  ·  No disponible", name=Path(path).name))
                gone.menuAction().setToolTip(_("No se encuentra este archivo: {path}", path=path))
                gone.addAction(_("Quitar de recientes"), lambda _=False, p=path: self.forget_recent(p))
        if not recent:
            menu.addAction(_("No hay archivos recientes")).setEnabled(False)
        menu.addSeparator()
        clear = menu.addAction(_("Borrar lista"))
        clear.setEnabled(bool(recent))
        clear.triggered.connect(lambda _=False: self.clear_recents())

    def recent_used(self):
        try:
            data = json.loads(str(self.settings.value("recentUsed", "{}")))
            return {str(k): float(v) for k, v in data.items()} if isinstance(data, dict) else {}
        except (ValueError, TypeError):
            return {}

    def clear_recents(self):
        self.settings.setValue("recent", [])
        self.settings.setValue("recentUsed", "{}")
        self.fill_recents()

    def forget_recent(self, path):
        recent = self.settings.value("recent", [], type=list)
        self.settings.setValue("recent", [item for item in recent if item != path])
        self.fill_recents()

    def compare_documents(self):
        """One entry for both comparisons; a small dialog asks which one to run."""
        visual, text = _("Apariencia (visual)"), _("Texto")
        picked = self.choose(_("Comparar documentos"), _("¿Cómo quieres comparar el documento actual con otro PDF?"), [visual, text])
        if picked == visual:
            self.compare()
        elif picked == text:
            self.compare_text()

    def build_menu(self):
        # A tuple (title, keys) is a submenu; "recent" is the Abrir reciente submenu.
        groups = [
            (N_("Archivo"), ["new", "open", "recent", None, "save", "saveas", "savecopy", "revert", None,
                         (N_("Crear PDF"), ["images", "office"]), (N_("Exportar como"), ["export_text", "export_docx", "export_xlsx", "export_pptx", "export_images"]),
                         None, "print", "metadata", None, "close", "quit"]),
            (N_("Edición"), ["undo", "redo", "selectall", "editpdf", None, "comments", "forms", "links", "bookmarks", "attachments"]),
            (N_("Páginas"), ["merge", "blank", "insertpage", "duplicate", "delete", "rotate", "extract", "split", None, "watermark", "number", "headerfooter", "stamp", "pagelabels"]),
            (N_("Seguridad"), ["redactsearch", "redactions", "sanitize", "anonymize", "protect", "unprotect", "sign", "signatures"]),
            (N_("Herramientas"), ["guided", "measure", "autofields", None, "ocr", "comparetext", "check", "accessibility", None, "optimize", "flatten", (N_("Avanzado"), ["bates"]), None, "batch"]),
            (N_("Ayuda"), ["shortcuts", "about"]),
        ]
        def add_entries(menu, keys):
            for key in keys:
                if key is None:
                    menu.addSeparator()
                elif key == "recent":
                    menu.addMenu(self.build_recent_menu(menu))
                elif isinstance(key, tuple):
                    title, sub_keys = key
                    add_entries(menu.addMenu(_(title)), sub_keys)
                else:
                    menu.addAction(self.actions[key])
        for title, keys in groups:
            menu = self.menuBar().addMenu(_(title))
            add_entries(menu, keys)
            if title == "Edición":
                self.build_view_menu()
            if title == "Ayuda":
                self.build_language_menu(menu)

    def build_language_menu(self, menu):
        """Ayuda > Idioma: sistema + idiomas disponibles. El cambio se aplica al reiniciar."""
        from . import lang
        submenu = menu.addMenu(_("Idioma"))
        group = QActionGroup(self)
        group.setExclusive(True)
        chosen = str(self.settings.value("language", "system"))
        self.language_actions = {}
        for code, label in [("system", _("Idioma del sistema"))] + [(c, lang.NAMES[c]) for c in lang.available()]:
            action = submenu.addAction(label)
            action.setCheckable(True)
            action.setChecked(code == chosen or (code == "system" and chosen not in lang.available()))
            action.triggered.connect(lambda _checked=False, value=code: self.set_language(value))
            group.addAction(action)
            self.language_actions[code] = action

    def set_language(self, code):
        if str(self.settings.value("language", "system")) == code:
            return
        self.settings.setValue("language", code)
        QMessageBox.information(self, _("Idioma"), _("El idioma cambiará la próxima vez que abras TrazoPDF."))

    def build_view_actions(self):
        """Zoom, layout, search and full-screen actions. The Ver menu and the toolbar's view button share them."""
        actions = self.view_actions = {}

        def make(key, text, handler, shortcuts=(), checkable=False, document=True):
            action = QAction(text, self)
            if shortcuts:
                action.setShortcuts([QKeySequence(shortcut) for shortcut in shortcuts])
            action.setCheckable(checkable)
            action.triggered.connect(lambda _=False, call=handler: call())
            actions[key] = action
            if document:
                self.doc_actions.append(action)
            return action

        make("fit_page", _("Ajustar página"), self.fit_page, ["Ctrl+9"], True)
        make("fit_width", _("Ajustar ancho"), self.fit_width, ["Ctrl+0"], True)
        make("actual", _("Tamaño real (100 %)"), self.actual_size, ["Ctrl+1"], True)
        make("zoom_in", _("Acercar"), lambda: self.set_zoom(self.zoom.value() + 10), ["Ctrl++", "Ctrl+="])
        make("zoom_out", _("Alejar"), lambda: self.set_zoom(self.zoom.value() - 10), ["Ctrl+-"])
        for percent in (50, 75, 100, 125, 150, 200):
            make(f"zoom_{percent}", f"{percent} %", lambda value=percent: self.set_zoom(value))
        make("single", _("Una página"), lambda: self.set_view_layout("single"), checkable=True)
        make("double", _("Dos páginas"), lambda: self.set_view_layout("double"), checkable=True)
        make("continuous", _("Desplazamiento continuo"), lambda: self.set_view_layout("continuous"), checkable=True)
        make("double_continuous", _("Dos páginas continuo"), lambda: self.set_view_layout("double_continuous"), checkable=True)
        layouts = QActionGroup(self)
        layouts.setExclusive(True)
        for key in ("single", "double", "continuous", "double_continuous"):
            layouts.addAction(actions[key])
        make("search", _("Buscar…"), self.open_search, ["Ctrl+F"], document=False)
        make("find_next", _("Buscar siguiente"), lambda: self.search_navigate(True), ["F3"])
        make("find_prev", _("Buscar anterior"), lambda: self.search_navigate(False), ["Shift+F3"])
        make("goto", _("Ir a la página…"), lambda: (self.page_spin.setFocus(), self.page_spin.selectAll()), ["Ctrl+G"])
        make("rotate", _("Girar la vista"), self.rotate_view, ["Ctrl+Shift+G"])
        make("fullscreen", _("Pantalla completa"), self.toggle_fullscreen, ["F11"], True, document=False)
        return actions

    def build_view_menu(self):
        self.init_navigation_state()
        view = self.menuBar().addMenu(_("Ver"))
        actions = self.build_view_actions()
        view.addAction(actions["fit_page"])
        view.addAction(actions["fit_width"])
        view.addAction(actions["actual"])
        zoom_menu = view.addMenu(_("Zoom"))
        zoom_menu.addAction(actions["zoom_in"])
        zoom_menu.addAction(actions["zoom_out"])
        zoom_menu.addSeparator()
        for percent in (50, 75, 100, 125, 150, 200):
            zoom_menu.addAction(actions[f"zoom_{percent}"])
        layout_menu = view.addMenu(_("Diseño"))
        layout_menu.addAction(actions["single"])
        layout_menu.addAction(actions["double"])
        layout_menu.addAction(actions["continuous"])
        layout_menu.addAction(actions["double_continuous"])
        view.addSeparator()
        view.addAction(actions["search"])
        view.addAction(actions["find_next"])
        view.addAction(actions["find_prev"])
        view.addAction(actions["goto"])
        view.addSeparator()
        self.rail_action = view.addAction(_("Barra de herramientas compacta"), lambda: self.set_rail_collapsed(not self.rail_collapsed), QKeySequence("Ctrl+B"))
        self.rail_action.setCheckable(True)
        self.rail_action.setChecked(self.rail_collapsed)
        view.addAction(_("Panel de páginas"), self.toggle_pages, QKeySequence("Ctrl+Shift+B"))
        view.addAction(actions["rotate"])
        view.addAction(actions["fullscreen"])
        view.addAction(_("Historial de mensajes"), lambda: self.show_message_history())
        view.addSeparator()
        theme_menu = view.addMenu(_("Tema"))
        group = QActionGroup(self)
        group.setExclusive(True)
        self.theme_actions = {}
        for mode, label, glyph in THEME_CHOICES:
            action = theme_menu.addAction(_(label))
            action.setCheckable(True)
            action.setChecked(mode == self.theme_mode)
            action.triggered.connect(lambda _=False, m=mode: self.set_theme(m))
            group.addAction(action)
            self.theme_actions[mode] = action

    def set_theme(self, mode):
        self.theme_mode = mode
        self.settings.setValue("theme", mode)
        for key, action in self.theme_actions.items():
            action.setChecked(key == mode)
        theme.apply_theme(QApplication.instance(), mode)
        self.apply_icons()
        self.view.viewport().update()
        self.thumbnails.viewport().update()

    def system_scheme_changed(self, *_):
        if self.theme_mode == "system" and theme.resolve_mode("system") != theme.current_name():
            self.set_theme("system")

    def bind_icon(self, target, name, tone="ink", checked=None):
        self.icon_bindings.append((target, name, tone, checked))
        target.setIcon(icons.themed_icon(name, tone, checked))

    def apply_icons(self):
        for target, name, tone, checked in self.icon_bindings:
            target.setIcon(icons.themed_icon(name, tone, checked))
        tokens = theme.current_tokens()
        ratio = self.devicePixelRatioF()
        self.welcome_mark.setPixmap(icons.app_mark(88, ratio))
        self.rail_mark.setPixmap(icons.app_mark(22, ratio))
        self.drop_icon.setPixmap(icons.pixmap("drop", tokens["inkmuted"], 22, ratio))
        for button in self.primary_buttons:
            button.setIcon(icons.tinted_icon(button.property("glyph"), tokens["onaccent"]))
        self.update_pages_toggle()
        self.refresh_tab_icons()
        self.recents.viewport().update()

    def update_pages_toggle(self):
        self.pages_toggle.setIcon(icons.themed_icon("chevron-left" if self.pages_collapsed else "chevron-right", "muted"))

    def build_toolbar(self):
        bar = QToolBar(_("Documento"))
        bar.setMovable(False)
        bar.setObjectName("MainToolbar")
        bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        bar.setIconSize(QSize(20, 20))
        self.addToolBar(bar)
        for key in ("open", "save", "print"):
            action = self.actions[key]
            self.bind_icon(action, ACTION_ICONS[key])
            shortcut = action.shortcut().toString()
            action.setToolTip(f"{action.text().rstrip('…')} ({shortcut})")
            bar.addAction(action)
            bar.widgetForAction(action).setAccessibleName(action.toolTip())
        bar.addSeparator()
        for key in ("undo", "redo"):
            action = self.actions[key]
            self.bind_icon(action, ACTION_ICONS[key])
            action.setToolTip(f"{action.text()} ({action.shortcut().toString()})")
            bar.addAction(action)
            bar.widgetForAction(action).setAccessibleName(action.toolTip())
        bar.addSeparator()
        self.page_spin = QSpinBox()
        self.page_spin.setRange(1, 1)
        self.page_spin.setFixedWidth(44)
        self.page_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_spin.setAccessibleName(_("Número de página"))
        self.page_spin.valueChanged.connect(lambda value: self.goto(value - 1))
        self.total = QLabel(" / 0   ")
        self.total.setAccessibleName(_("Total de páginas"))
        previous = self.pill_button("chevron-left", _("Página anterior"), lambda: self.goto(self.page - 1))
        following = self.pill_button("chevron-right", _("Página siguiente"), lambda: self.goto(self.page + 1))
        bar.addWidget(make_pill(previous, self.page_spin, self.total, following))
        bar.addWidget(self.bar_gap(8))
        self.zoom = QSpinBox()
        self.zoom.setRange(25, 400)
        self.zoom.setValue(100)
        self.zoom.setSuffix(" %")
        self.zoom.setFixedWidth(64)
        self.zoom.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.zoom.setAccessibleName(_("Nivel de zoom"))
        self.zoom.valueChanged.connect(self.zoom_changed)
        zoom_out = self.pill_button("minus", _("Reducir zoom"), lambda: self.set_zoom(self.zoom.value() - 10))
        zoom_in = self.pill_button("plus", _("Aumentar zoom"), lambda: self.set_zoom(self.zoom.value() + 10))
        bar.addWidget(make_pill(zoom_out, self.zoom, zoom_in))
        self.zoom_presets = QComboBox()
        self.zoom_presets.setObjectName("ZoomPresets")
        self.zoom_presets.setAccessibleName(_("Preajustes de zoom"))
        self.zoom_presets.setToolTip(_("Preajustes de zoom"))
        self.zoom_presets.setFixedWidth(104)
        self.zoom_presets.addItem(_("Zoom"), None)
        for percent in (50, 75, 100, 125, 150, 200):
            self.zoom_presets.addItem(f"{percent} %", f"zoom_{percent}")
        for label, key in ((_("Ajustar anchura"), "fit_width"), (_("Ajustar página"), "fit_page"), (_("Tamaño real"), "actual")):
            self.zoom_presets.addItem(label, key)
        self.zoom_presets.activated.connect(self.apply_zoom_preset)
        self.zoom_presets.setEnabled(False)
        bar.addWidget(self.zoom_presets)
        bar.addWidget(self.bar_gap(4))
        bar.addWidget(self.pill_button("fit-width", _("Ajustar a la anchura de la página"), self.fit_width, pill=False))
        view_button = QToolButton()
        view_button.setObjectName("ViewButton")
        view_button.setToolTip(_("Vista y zoom"))
        view_button.setAccessibleName(_("Vista y zoom"))
        view_button.setAutoRaise(True)
        view_button.setIconSize(QSize(20, 20))
        view_button.setCursor(Qt.CursorShape.PointingHandCursor)
        view_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.bind_icon(view_button, "pages", "ink")
        view_menu = QMenu(view_button)
        for key in ("fit_page", "fit_width", "actual"):
            view_menu.addAction(self.view_actions[key])
        view_menu.addSeparator()
        for percent in (50, 75, 100, 125, 150, 200):
            view_menu.addAction(self.view_actions[f"zoom_{percent}"])
        view_menu.addSeparator()
        view_menu.addAction(self.view_actions["single"])
        view_menu.addAction(self.view_actions["double"])
        view_menu.addAction(self.view_actions["continuous"])
        view_menu.addAction(self.view_actions["double_continuous"])
        view_button.setMenu(view_menu)
        bar.addWidget(view_button)
        bar.addWidget(self.pill_button("rotate", _("Girar la vista (Ctrl+Mayús+G)"), self.rotate_view, pill=False))
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bar.addWidget(spacer)
        # The search row sits under this toolbar; its field is kept as window.search for the existing callers.
        self.search_bar = SearchBar(self)
        self.search = self.search_bar.field
        bar.addWidget(self.pill_button("search", _("Buscar texto en el documento"), self.open_search, pill=False))
        self.toolbar_prev = self.pill_button("arrow-up", _("Ir a la coincidencia anterior"), lambda: self.search_navigate(False), pill=False)
        self.toolbar_next = self.pill_button("arrow-down", _("Ir a la coincidencia siguiente"), lambda: self.search_navigate(True), pill=False)
        self.toolbar_prev.setEnabled(False)
        self.toolbar_next.setEnabled(False)
        bar.addWidget(self.toolbar_prev)
        bar.addWidget(self.toolbar_next)
        self.addToolBarBreak(Qt.ToolBarArea.TopToolBarArea)
        self.search_toolbar = QToolBar(_("Búsqueda"))
        self.search_toolbar.setObjectName("SearchToolbar")
        self.search_toolbar.setMovable(False)
        self.search_toolbar.addWidget(self.search_bar)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.search_toolbar)
        self.search_toolbar.hide()

    def left_tab_changed(self, index):
        if 0 <= index < len(self.side_tab_keys):
            self.settings.setValue("leftTab", self.side_tab_keys[index])
        self.refresh_side_panel(True)

    def apply_zoom_preset(self, index):
        key = self.zoom_presets.itemData(index)
        self.zoom_presets.setCurrentIndex(0)
        if key and self.has_doc():
            self.view_actions[key].trigger()

    def pill_button(self, glyph, tooltip, handler, pill=True):
        button = QToolButton()
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setAutoRaise(True)
        button.setIconSize(QSize(18 if pill else 20, 18 if pill else 20))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda _=False: handler())
        self.bind_icon(button, glyph, "ink")
        return button

    def bar_gap(self, width):
        gap = QWidget()
        gap.setFixedWidth(width)
        return gap

    def build_layout(self):
        self.splitter = QSplitter()
        self.splitter.setChildrenCollapsible(False)
        self.setCentralWidget(self.splitter)
        self.left_tabs = QTabWidget()
        self.left_tabs.setTabBar(SideTabBar())
        self.thumbnails = ThumbnailList()
        self.thumbnails.currentRowChanged.connect(self.goto)
        self.thumbnails.verticalScrollBar().valueChanged.connect(lambda _: self.load_thumbnails())
        self.thumbnails.sizeChanged.connect(self.load_thumbnails)
        self.thumbnails.reorderRequested.connect(self.move_pages)
        self.thumbnails.filesDropped.connect(self.dropped_files)
        self.thumbnails.deleteRequested.connect(lambda: self.has_doc() and self.run(self.delete_pages))
        self.thumbnails.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.thumbnails.customContextMenuRequested.connect(self.thumbnail_menu)
        pages_tab = QWidget()
        pages_tab.setObjectName("PagesTab")
        pages_column = QVBoxLayout(pages_tab)
        pages_column.setContentsMargins(0, 0, 0, 0)
        pages_column.setSpacing(0)
        pages_column.addWidget(self.build_page_bar())
        pages_column.addWidget(self.thumbnails, 1)
        self.left_tabs.addTab(pages_tab, _("Páginas"))
        self.bookmark_panel = BookmarksPanel()
        self.bookmark_list = self.bookmark_panel.tree
        self.bookmark_list.pageRequested.connect(self.goto)
        self.bookmark_list.commitRequested.connect(self.save_bookmarks)
        self.bookmark_list.page_provider = lambda: self.page
        self.bookmark_panel.addRequested.connect(lambda: self.has_doc() and self.bookmark_list.add_marker(self.page))
        self.left_tabs.addTab(self.bookmark_panel, _("Marcadores"))
        self.side_tab_keys = ["pages", "bookmarks"]
        for key, title, widget in self.build_side_panels():
            self.left_tabs.addTab(widget, title)
            self.side_tab_keys.append(key)
        saved = str(self.settings.value("leftTab", "pages"))
        if saved in self.side_tab_keys:
            self.left_tabs.setCurrentIndex(self.side_tab_keys.index(saved))
        self.left_tabs.currentChanged.connect(self.left_tab_changed)
        self.left_tabs.setMinimumWidth(176)
        self.left_tabs.setMaximumWidth(300)
        self.left_tabs.setUsesScrollButtons(True)
        self.left_tabs.setDocumentMode(True)
        self.left_tabs.setElideMode(Qt.TextElideMode.ElideNone)
        self.stack = QStackedWidget()
        self.stack.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.view = PageView(self)
        self.view.setObjectName("DocumentArea")
        self.view.setAccessibleName(_("Documento"))
        self.stack.addWidget(self.welcome())
        document_page = QWidget()
        document_column = QVBoxLayout(document_page)
        document_column.setContentsMargins(0, 0, 0, 0)
        document_column.setSpacing(0)
        document_column.addWidget(self.build_tab_bar())
        document_column.addWidget(self.view, 1)
        self.stack.addWidget(document_page)
        self.stack.currentChanged.connect(lambda index: self.zoom_presets.setEnabled(index == 1))
        scroll = self.build_rail()
        self.splitter.addWidget(scroll)
        self.splitter.addWidget(self.stack)
        self.pages_panel = QWidget()
        pages_layout = QVBoxLayout(self.pages_panel)
        pages_layout.setContentsMargins(0, 0, 0, 0)
        pages_layout.setSpacing(0)
        page_header = QHBoxLayout()
        page_header.setContentsMargins(0, 0, 6, 0)
        self.pages_label = QLabel(_("Navegación"))
        self.pages_label.setObjectName("PagesTitle")
        self.pages_toggle = QPushButton()
        self.pages_toggle.setFixedWidth(32)
        self.pages_toggle.setIconSize(QSize(18, 18))
        self.pages_toggle.setToolTip(_("Plegar / desplegar el panel de páginas"))
        self.pages_toggle.setObjectName("CollapseButton")
        self.pages_toggle.setAccessibleName(_("Plegar panel de páginas"))
        self.pages_panel.setObjectName("PagesPanel")
        self.pages_toggle.clicked.connect(self.toggle_pages)
        page_header.addWidget(self.pages_label)
        page_header.addWidget(self.pages_toggle)
        header_widget = QWidget()
        header_widget.setObjectName("PagesHeader")
        header_widget.setLayout(page_header)
        header_widget.setFixedHeight(42)
        pages_layout.addWidget(header_widget)
        pages_layout.addWidget(self.left_tabs, 1)
        self.pages_collapsed = False
        self.pages_min = 176
        self.pages_panel.setMinimumWidth(176)
        self.pages_panel.setMaximumWidth(300)
        self.splitter.addWidget(self.pages_panel)
        self.update_pages_toggle()
        self.fit_tab_width()
        QTimer.singleShot(0, self.fit_tab_width)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        self.splitter.setSizes([RAIL_WIDE, 940, 250])
        self.set_rail_collapsed(self.rail_collapsed, persist=False)
        self.apply_icons()
        if self.settings.value("pagesCollapsed", False, type=bool):
            self.toggle_pages()
        self.set_mode("select")
        self.stack.setFocus()

    def welcome(self):
        area = QScrollArea()
        area.setObjectName("WelcomeScroll")
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        widget = QWidget()
        widget.setObjectName("WelcomeView")
        outer = QVBoxLayout(widget)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.addStretch(1)
        card = QFrame()
        card.setObjectName("WelcomeCard")
        card.setMaximumWidth(600)
        card.setMinimumWidth(320)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(40, 34, 40, 30)
        layout.setSpacing(0)
        self.welcome_mark = QLabel()
        self.welcome_mark.setPixmap(icons.app_mark(88, self.devicePixelRatioF()))
        self.welcome_mark.setFixedSize(88, 88)
        self.welcome_mark.setScaledContents(True)
        self.welcome_mark.setAccessibleName("TrazoPDF")
        layout.addWidget(self.welcome_mark, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(16)
        title = QLabel(_("Abre un PDF para empezar"))
        title.setObjectName("WelcomeTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setWordWrap(True)
        layout.addWidget(title)
        layout.addSpacing(6)
        subtitle = QLabel(_("Abre un archivo, edita su texto y guarda los cambios. Todo ocurre en tu equipo."))
        subtitle.setObjectName("WelcomeSubtitle")
        subtitle.setWordWrap(True)
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)
        layout.addSpacing(22)
        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addStretch(1)
        open_button = QPushButton(_("Abrir PDF"))
        open_button.setToolTip(_("Elige un PDF de tu equipo (Ctrl+O)"))
        open_button.setProperty("primary", True)
        open_button.setProperty("glyph", "open")
        open_button.setIconSize(QSize(18, 18))
        open_button.setMinimumWidth(150)
        open_button.setCursor(Qt.CursorShape.PointingHandCursor)
        open_button.clicked.connect(lambda: self.run(self.open_file))
        self.primary_buttons = [open_button]
        open_button.setIcon(icons.tinted_icon("open", theme.current_tokens()["onaccent"]))
        buttons.addWidget(open_button)
        new = QPushButton(_("Crear documento en blanco"))
        new.setProperty("secondary", True)
        new.setIconSize(QSize(18, 18))
        new.setToolTip(_("Empieza con un documento vacío (Ctrl+N)"))
        new.setCursor(Qt.CursorShape.PointingHandCursor)
        new.clicked.connect(lambda: self.run(self.new_file))
        self.bind_icon(new, "new", "ink")
        buttons.addWidget(new)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        layout.addSpacing(20)
        drop = QFrame()
        drop.setObjectName("DropZone")
        drop_row = QHBoxLayout(drop)
        drop_row.setContentsMargins(16, 12, 16, 12)
        drop_row.setSpacing(12)
        drop_row.addStretch(1)
        drop_icon = QLabel()
        drop_icon.setFixedSize(24, 24)
        self.drop_icon = drop_icon
        drop_row.addWidget(drop_icon)
        hint = QLabel(_("Arrastra un PDF hasta aquí para abrirlo"))
        hint.setObjectName("caption")
        drop_row.addWidget(hint)
        drop_row.addStretch(1)
        self.drop_hint = hint
        layout.addWidget(drop)
        layout.addSpacing(16)
        tasks = QGridLayout()
        tasks.setHorizontalSpacing(8)
        tasks.setVerticalSpacing(8)
        self.task_buttons = []
        for index, (label, glyph, handler, tip) in enumerate([
            (_("Combinar PDFs"), "merge", lambda: self.merge(), _("Une varios archivos en un solo PDF")),
            (_("Imágenes a PDF"), "images", lambda: self.from_images(), _("Crea un PDF a partir de fotos o imágenes")),
            (_("Convertir desde Office"), "file", lambda: self.from_office(), _("Convierte documentos de Word, Excel o PowerPoint a PDF")),
            (_("Comparar"), "compare-text", lambda: self.compare_documents(), _("Compara dos PDF por apariencia o por texto")),
        ]):
            button = QPushButton(label)
            button.setProperty("secondary", True)
            button.setIconSize(QSize(18, 18))
            button.setToolTip(tip)
            button.setAccessibleName(tip)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, h=handler: self.run(h))
            self.bind_icon(button, glyph, "ink")
            tasks.addWidget(button, index // 2, index % 2)
            self.task_buttons.append(button)
        layout.addLayout(tasks)
        layout.addSpacing(8)
        self.guided_button = QPushButton(_("Acciones guiadas"))
        self.guided_button.setProperty("secondary", True)
        self.guided_button.setIconSize(QSize(18, 18))
        self.guided_button.setToolTip(_("Asistentes paso a paso: preparar para enviar, combinar, censurar, rellenar y firmar"))
        self.guided_button.setAccessibleName(_("Acciones guiadas: asistentes paso a paso"))
        self.guided_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.guided_button.clicked.connect(lambda: self.run(lambda: guided.open_guided(self)))
        self.bind_icon(self.guided_button, "check", "ink")
        layout.addWidget(self.guided_button)
        layout.addSpacing(18)
        self.recents_title = QLabel(_("Recientes"))
        self.recents_title.setObjectName("WelcomeHeading")
        layout.addWidget(self.recents_title)
        layout.addSpacing(6)
        self.recents = QListWidget()
        self.recents.setMaximumHeight(248)
        self.recents.setObjectName("RecentList")
        self.recents.setItemDelegate(RecentInfoDelegate(self.recents))
        self.recents.setIconSize(QSize(20, 20))
        self.recents.setMouseTracking(True)
        self.recents.setToolTip(_("Doble clic o Intro para abrir un archivo reciente"))
        self.recents.setAccessibleName(_("Archivos recientes"))
        self.recents.itemActivated.connect(lambda item: self.run(lambda: self.open_path(item.data(Qt.ItemDataRole.UserRole))))
        self.recents.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.recents.customContextMenuRequested.connect(self.recent_context_menu)
        layout.addWidget(self.recents)
        self.fill_recents()
        outer.addWidget(card, 0, Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch(2)
        area.setWidget(widget)
        return area

    def recent_context_menu(self, pos):
        item = self.recents.itemAt(pos)
        if item is None:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self.recents)
        if Path(path).is_file():
            menu.addAction(_("Abrir"), lambda: self.run(lambda: self.open_path(path)))
        menu.addAction(_("Quitar de recientes"), lambda: self.forget_recent(path))
        menu.exec(self.recents.mapToGlobal(pos))

    def recent_thumb_ready(self, path):
        target = recent_thumb_path(path)
        pixmap = QPixmap(str(target)) if target is not None else QPixmap()
        if pixmap.isNull():
            return
        for index in range(self.recents.count()):
            item = self.recents.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == path:
                item.setData(Qt.ItemDataRole.DecorationRole, pixmap)
        self.recents.viewport().update()

    def fill_recents(self):
        self.recents.clear()
        used = self.recent_used()
        if not hasattr(self, "recent_thumbs"):
            self.recent_thumbs = RecentThumbs(self)
            self.recent_thumbs.ready.connect(self.recent_thumb_ready)
        for path in self.settings.value("recent", [], type=list):
            exists = Path(path).is_file()
            name = Path(path).name
            item = QListWidgetItem(name if exists else _("{name} (No disponible)", name=name))
            item.setData(Qt.ItemDataRole.UserRole + 2, not exists)
            item.setToolTip(path if exists else _("No se encuentra este archivo: {path}", path=path))
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setData(Qt.ItemDataRole.UserRole + 1, relative_day(used.get(path)))
            item.setSizeHint(QSize(100, 56))
            if exists:
                cached = recent_thumb_path(path)
                if cached is not None and cached.is_file():
                    item.setData(Qt.ItemDataRole.DecorationRole, QPixmap(str(cached)))
                else:
                    self.recent_thumbs.request(path)
            self.recents.addItem(item)
        has_recents = self.recents.count() > 0
        if has_recents:
            self.recents.setFixedHeight(min(248, self.recents.count() * 58 + 10))
        self.recents.setVisible(has_recents)
        self.recents_title.setVisible(has_recents)
