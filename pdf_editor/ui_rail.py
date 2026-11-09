from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QSize, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractSpinBox, QApplication, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
    QPushButton, QScrollArea, QSpinBox, QTextEdit, QVBoxLayout, QWidget,
)

from . import icons
from .lang import _, N_
from .ui_support import ACTION_ICONS, RAIL_COMPACT, RAIL_WIDE, TOOL_ICONS
from .ui_widgets import RailButton

# Rail sections in order. Entries are ("mode", canvas mode, label) or ("doc", action key, label).
# Labels are short so that they fit at 1024 x 768 and at 125 % to 150 % scale; the full text is in the tooltip.
RAIL_SECTIONS = [
    (N_("Leer y editar"), [
        ("mode", "select", N_("Seleccionar texto")), ("mode", "edit", N_("Mover objetos")), ("mode", "hand", N_("Desplazar")),
        ("mode", "replace", N_("Texto")), ("mode", "image", N_("Insertar imagen")), ("mode", "link", N_("Enlace")),
    ]),
    (N_("Comentar"), [
        ("mode", "highlight", N_("Resaltar")), ("mode", "underline", N_("Subrayar")), ("mode", "strikeout", N_("Tachar")),
        ("mode", "note", N_("Nota")), ("mode", "freetext", N_("Cuadro de texto")), ("mode", "ink", N_("Dibujar")),
        ("mode", "line", N_("Línea")), ("mode", "arrow", N_("Flecha")), ("mode", "rectangle", N_("Rectángulo")), ("mode", "ellipse", N_("Elipse")),
        ("mode", "measure", N_("Medir")),
    ]),
    (N_("Formularios y seguridad"), [
        ("mode", "fill", N_("Rellenar y firmar")), ("mode", "field", N_("Crear campo")),
        ("mode", "redact", N_("Censurar (marcar)")), ("mode", "crop", N_("Recortar página")),
    ]),
]
# Document actions live in the menus and the page thumbnails; their buttons stay built but hidden for older callers.
DOC_ACTIONS = [
    ("forms", N_("Rellenar formularios")), ("redactsearch", N_("Buscar y censurar")), ("redactions", N_("Aplicar censuras")),
    ("protect", N_("Guardar con contraseña")), ("merge", N_("Combinar archivos")), ("rotate", N_("Girar 90°")),
    ("insertpage", N_("Insertar página")), ("pagelabels", N_("Etiquetas de página")), ("headerfooter", N_("Encabezado y pie")),
    ("bates", N_("Numeración Bates")), ("stamp", N_("Sellos")), ("export", N_("Exportar")), ("ocr", N_("Reconocer texto")),
    ("optimize", N_("Optimizar tamaño")), ("flatten", N_("Aplanar")), ("check", N_("Comprobar documento")),
    ("comparetext", N_("Comparar documentos")),
]
# The new tools reuse existing glyphs until icons.py gets its own.
MODE_ICONS = {"freetext": "text", "line": "ink", "arrow": "ink"}
# Files and new documents stay visible without a document open.
RAIL_ALWAYS = [("open", N_("Abrir PDF")), ("new", N_("Nuevo PDF"))]
RAIL_EMPTY_TEXT = N_("Abre un PDF para ver las herramientas")


class TextToolPressFilter(QObject):
    """Viewport filter: a left press on empty page in the Texto tool adds text there."""

    def __init__(self, window):
        super().__init__(window)
        self.window = window

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            return bool(self.window.text_tool_press(event))
        return False


class UiRailMixin:
    """The left tool rail: sections, tool buttons and collapse state."""

    def build_rail(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("ToolRail")
        scroll.setAccessibleName(_("Herramientas"))
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.rail = scroll
        panel = QWidget()
        panel.setObjectName("ToolPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(0)
        self.rail_layout = layout
        head = QHBoxLayout()
        head.setContentsMargins(4, 0, 0, 0)
        self.rail_mark = QLabel()
        self.rail_mark.setPixmap(icons.app_mark(22, self.devicePixelRatioF()))
        self.rail_mark.setFixedSize(22, 22)
        self.rail_mark.setScaledContents(True)
        brand = QLabel("TrazoPDF")
        brand.setObjectName("brand")
        self.rail_brand = brand
        self.rail_toggle = QPushButton()
        self.rail_toggle.setObjectName("RailToggle")
        self.rail_toggle.setIconSize(QSize(18, 18))
        self.rail_toggle.setFixedSize(32, 30)
        self.rail_toggle.setAccessibleName(_("Contraer barra de herramientas"))
        self.rail_toggle.clicked.connect(lambda: self.set_rail_collapsed(not self.rail_collapsed))
        self.bind_icon(self.rail_toggle, "panel-left", "muted")
        head.addWidget(self.rail_mark)
        head.addSpacing(6)
        head.addWidget(brand, 1)
        head.addWidget(self.rail_toggle, 0, Qt.AlignmentFlag.AlignRight)
        self.rail_head = head
        layout.addLayout(head)
        self.rail_empty = QLabel(_(RAIL_EMPTY_TEXT))
        self.rail_empty.setObjectName("caption")
        self.rail_empty.setWordWrap(True)
        layout.addWidget(self.rail_empty)
        self.mode_buttons = {}
        self.rail_items = []
        self.rail_labels = []
        self.rail_separators = []
        self.rail_always = []
        self.doc_buttons = {}
        for key, label in RAIL_ALWAYS:
            label = _(label)
            button = self.rail_button(label, label, ACTION_ICONS.get(key, key), lambda k=key: self.actions[k].trigger())
            self.rail_always.append(button)
            layout.addWidget(button)
        for heading, entries in RAIL_SECTIONS:
            self.rail_section(layout, heading)
            for kind, key, label in entries:
                if kind == "mode":
                    self.add_mode_button(layout, key, _(label))
                else:
                    self.add_doc_button(layout, key, _(label))
        for key, label in DOC_ACTIONS:
            if key in self.actions:
                self.add_doc_button(layout, key, _(label)).hide()
        fill_key = QShortcut(QKeySequence("F"), self)
        fill_key.activated.connect(self.fill_shortcut)
        # Text format controls live in the floating format bar; the window keeps the old names.
        bar = self.view.format_bar
        self.font_size = bar.size_spin
        self.font_family = bar.family
        self.bold = bar.bold
        self.italic = bar.italic
        layout.addStretch()
        for child in panel.findChildren(QLabel):
            if child is not self.rail_mark:
                child.setWordWrap(True)
        for child in panel.findChildren(QWidget):
            if isinstance(child, (QPushButton, QComboBox, QSpinBox)) and child is not self.rail_toggle:
                policy = child.sizePolicy()
                policy.setHorizontalPolicy(policy.Policy.Ignored)
                child.setSizePolicy(policy)
        scroll.setWidget(panel)
        self.install_text_tool()
        self.stack.currentChanged.connect(lambda _=0: self.sync_rail_visibility())
        self.sync_rail_visibility()
        return scroll

    def rail_button(self, text, tooltip, icon, handler, tone="muted", checkable=False):
        button = RailButton(text)
        button.setCheckable(checkable)
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setIconSize(QSize(18, 18))
        self.bind_icon(button, icon, tone, "accent" if checkable else None)
        button.clicked.connect(lambda checked=False: handler())
        self.rail_items.append((button, text))
        return button

    def add_mode_button(self, layout, mode, title):
        # Texto (T) is the replace mode; the old text mode name keeps working through set_mode.
        letter = "T" if mode == "replace" else self.tool_letter(mode)
        tooltip = f"{title} ({letter})" if letter else title
        icon = "text" if mode == "replace" else MODE_ICONS.get(mode) or TOOL_ICONS.get(mode, mode)
        button = self.rail_button(title, tooltip, icon, lambda m=mode: self.set_mode(m), "muted", True)
        button.setObjectName("ModeButton")
        self.mode_buttons[mode] = button
        layout.addWidget(button)
        return button

    def add_doc_button(self, layout, key, label):
        action = self.actions[key]
        button = self.rail_button(label, action.text().rstrip("…"), ACTION_ICONS[key], lambda k=key: self.actions[k].trigger())
        button.setObjectName("DocButton")
        action.changed.connect(lambda b=button, k=key: b.setEnabled(self.actions[k].isEnabled()))
        self.doc_buttons[key] = button
        layout.addWidget(button)
        return button

    def tool_letter(self, mode):
        from .canvas import TOOL_LETTERS
        return next((letter for letter, name in TOOL_LETTERS.items() if name == mode), "")

    def install_text_tool(self):
        """One Texto tool: a click on existing text edits that block, a click on empty page adds text.

        The window keeps the "text" (add) and "replace" (edit) modes for the canvas and the older callers,
        so these two wrappers route the rail's Texto tool to the right one.
        """
        set_mode = self.set_mode
        perform_selection = self.perform_selection

        def route_mode(mode):
            set_mode("replace" if mode == "text" else mode)

        def route_selection(mode, rect, point, clicked, ink):
            if mode == "replace" and not self.text_at(point, rect):
                mode = "text"
            return perform_selection(mode, rect, point, clicked, ink)

        def route_shapes(mode, rect, point, clicked, ink):
            if mode in ("line", "arrow", "freetext"):
                return self.place_annotation_tool(mode, rect, point, clicked)
            return route_selection(mode, rect, point, clicked, ink)

        self.set_mode = route_mode
        self.perform_selection = route_shapes
        self.engine.author = str(self.settings.value("annotationAuthor", "") or "") or self.engine.author
        # The canvas ignores a press on empty space in replace mode, so the rail filters that press here.
        self._text_tool_filter = TextToolPressFilter(self)
        self.view.viewport().installEventFilter(self._text_tool_filter)
        # The rail shows the T letter for Texto, so the generic letter labelling must not overwrite it.
        self._tool_letters_done = True

    def text_tool_press(self, event):
        """A press on empty page with the Texto tool starts a new text box; returns True when it handled the press."""
        view = self.view
        if view.mode != "replace" or not self.has_doc() or view.editor is not None:
            return False
        scene_point = view.mapToScene(event.position().toPoint())
        # A press on another visible page is the canvas's to handle: it makes that page the current one first.
        if any(rect.contains(scene_point) for _, rect in view.companion_rects):
            return False
        if view.lazy:
            view.switch_page_under(scene_point)
        point = view.pdf_point(scene_point)
        if view.run_at(point):
            return False
        self.run(lambda: view.begin_editor(point=point, rect=None))
        return True

    def text_at(self, point, rect):
        if point is not None and self.view.run_at(point):
            return True
        return rect is not None and any(run.rect.intersects(rect) for run in self.view.runs)

    def sync_rail_visibility(self):
        """Without a document the rail shows one hint line and only the file buttons."""
        has_doc = self.has_doc()
        collapsed = self.rail_collapsed
        self.rail_empty.setVisible(not has_doc and not collapsed)
        for button, _text in self.rail_items:
            if button not in self.rail_always and button not in self.doc_buttons.values():
                button.setVisible(has_doc)
        for label in self.rail_labels:
            label.setVisible(has_doc and not collapsed)
        for line in self.rail_separators:
            line.setVisible(has_doc and collapsed)

    def fill_shortcut(self):
        """F opens "Rellenar y firmar", except while text is being typed."""
        typing = isinstance(QApplication.focusWidget(), (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox))
        if not self.has_doc() or typing or self.view.editor is not None:
            return
        self.set_mode("fill")

    def rail_section(self, layout, heading):
        if self.rail_labels:
            line = QFrame()
            line.setObjectName("RailSeparator")
            line.setFrameShape(QFrame.Shape.NoFrame)
            line.hide()
            layout.addWidget(line)
            self.rail_separators.append(line)
        label = QLabel(_(heading))
        label.setObjectName("section")
        layout.addWidget(label)
        self.rail_labels.append(label)

    def set_rail_collapsed(self, collapsed, persist=True):
        """Switch the tool rail between full rows (icon + label) and a 56 px icon-only strip."""
        collapsed = bool(collapsed)
        self.rail_collapsed = collapsed
        if persist:
            self.settings.setValue("railCollapsed", collapsed)
        for button, text in self.rail_items:
            button.setText("" if collapsed else text)
            button.setProperty("compact", collapsed)
            button.style().unpolish(button)
            button.style().polish(button)
        self.sync_rail_visibility()
        self.rail_mark.setVisible(not collapsed)
        self.rail_brand.setVisible(not collapsed)
        self.rail.setProperty("compact", collapsed)
        self.rail.style().unpolish(self.rail)
        self.rail.style().polish(self.rail)
        self.rail_layout.setContentsMargins(*(4, 4, 4, 4) if collapsed else (8, 4, 8, 4))
        self.rail_head.setContentsMargins(*(0, 0, 0, 0) if collapsed else (4, 0, 0, 0))
        self.rail_toggle.setToolTip(_("Expandir barra de herramientas (Ctrl+B)") if collapsed else _("Contraer a solo iconos (Ctrl+B)"))
        self.rail_toggle.setAccessibleName(_("Expandir barra de herramientas") if collapsed else _("Contraer barra de herramientas"))
        if collapsed:
            self.rail.setMinimumWidth(RAIL_COMPACT)
            self.rail.setMaximumWidth(RAIL_COMPACT)
        else:
            self.rail.setMinimumWidth(224)
            self.rail.setMaximumWidth(300)
        if hasattr(self, "rail_action"):
            self.rail_action.setChecked(collapsed)
        sizes = self.splitter.sizes()
        if len(sizes) == 3 and sum(sizes) > 0:
            target = RAIL_COMPACT if collapsed else RAIL_WIDE
            self.splitter.setSizes([target, max(1, sizes[1] + sizes[0] - target), sizes[2]])
