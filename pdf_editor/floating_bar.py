"""Floating format bar: text, markup, shapes, notes and fields without dialogs."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QColorDialog, QComboBox, QFrame, QGridLayout,
                               QHBoxLayout, QLineEdit, QPushButton, QSpinBox, QToolButton,
                               QVBoxLayout, QWidget)

from . import icons
from .lang import _, N_

BASE_COLORS = ["#182e49", "#000000", "#d93025", "#188038", "#1a73e8", "#f9ab00", "#9334e6", "#5f6368"]
MARKUP_COLORS = ["#ffe066", "#8fd694", "#8ab4f8", "#f8a5c2", "#ffb86b"]
TEXT_SIZES = [8, 9, 10, 11, 12, 14, 18, 24, 36, 48]
FAMILIES = ["Arial", "Times", "Courier"]
WIDTHS = [1, 2, 4, 8]
OPACITIES = [1.0, 0.7, 0.4]
LINE_SPACINGS = [1.0, 1.15, 1.5, 2.0]
FIELD_KINDS = [(N_("Texto"), "text"), (N_("Casilla"), "checkbox"), (N_("Lista"), "choice")]
MAX_RECENT = 6

# Last colour, width, opacity and fill per tool, stored in QSettings toolStyle/<tool>/<key>.
TOOL_DEFAULTS = {
    "text": {"color": "#182e49"},
    "highlight": {"color": "#ffe066", "opacity": 1.0},
    "underline": {"color": "#1a73e8", "opacity": 1.0},
    "strikeout": {"color": "#d93025", "opacity": 1.0},
    "rectangle": {"color": "#d93025", "width": 2, "opacity": 1.0, "fill": False},
    "ellipse": {"color": "#1a73e8", "width": 2, "opacity": 1.0, "fill": False},
    "ink": {"color": "#182e49", "width": 2, "opacity": 1.0},
    "note": {"color": "#f9ab00"},
    "line": {"color": "#d93025", "width": 2, "opacity": 1.0},
    "arrow": {"color": "#d93025", "width": 2, "opacity": 1.0},
    "freetext": {"color": "#182e49"},
}

SHORTCUTS = {
    Qt.Key.Key_B: ("bold", None),
    Qt.Key.Key_I: ("italic", None),
    Qt.Key.Key_L: ("align", 0),
    Qt.Key.Key_E: ("align", 1),
    Qt.Key.Key_R: ("align", 2),
    Qt.Key.Key_J: ("align", 3),
    Qt.Key.Key_U: ("underline", None),
    Qt.Key.Key_Greater: ("step", 1),
    Qt.Key.Key_Less: ("step", -1),
}


def format_shortcut(event):
    """Return (action, value) for a text-format shortcut while the inline editor has focus."""
    modifiers = event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.AltModifier)
    entry = SHORTCUTS.get(Qt.Key(event.key()))
    if entry is None:
        return None
    if entry[0] == "step":
        wanted = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
    else:
        wanted = Qt.KeyboardModifier.ControlModifier
    return entry if modifiers == wanted else None


def rgb_of(color):
    value = QColor(color)
    return (value.redF(), value.greenF(), value.blueF())


def tool_style(settings, tool):
    """Last used style for a tool, falling back to the defaults."""
    style = {}
    for key, default in TOOL_DEFAULTS.get(tool, {}).items():
        stored = settings.value(f"toolStyle/{tool}/{key}", default)
        try:
            if isinstance(default, bool):
                value = stored if isinstance(stored, bool) else str(stored).lower() in ("true", "1")
            elif isinstance(default, float):
                value = float(stored)
            elif isinstance(default, int):
                value = int(float(stored))
            else:
                value = str(stored) if QColor(str(stored)).isValid() else default
        except (TypeError, ValueError):
            value = default
        style[key] = value
    return style


def set_tool_style(settings, tool, **values):
    for key, value in values.items():
        settings.setValue(f"toolStyle/{tool}/{key}", value)


def recent_colors(settings):
    value = settings.value("recentColors", [])
    if isinstance(value, str):
        value = [value] if value else []
    return [str(item) for item in value or [] if QColor(str(item)).isValid()][:MAX_RECENT]


def remember_color(settings, color):
    colors = [color] + [item for item in recent_colors(settings) if item.lower() != color.lower()]
    settings.setValue("recentColors", colors[:MAX_RECENT])


def next_field_name(existing):
    number = 1
    while f"Campo_{number}" in existing:
        number += 1
    return f"Campo_{number}"


def swatch_style(color):
    return (f"QToolButton {{ background: {color}; border: 1px solid rgba(128, 128, 128, 170); border-radius: 6px;"
            " padding: 0; min-width: 18px; min-height: 18px; }"
            " QToolButton:hover { border: 2px solid #0A7A6C; }"
            " QToolButton:checked { border: 2px solid #0A7A6C; }")


def swatch(color, tooltip):
    button = QToolButton()
    button.setFixedSize(20, 20)
    button.setToolTip(tooltip)
    button.setAccessibleName(tooltip)
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    button.setProperty("swatch", color)
    button.setStyleSheet(swatch_style(color))
    return button


def width_icon(width):
    pixmap = QPixmap(28, 16)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("#1B2326"), width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawLine(4, 8, 24, 8)
    painter.end()
    return pixmap


class ColorPopover(QFrame):
    """Small palette: recent colours, base colours and an escape hatch to the full picker."""

    picked = Signal(str)

    def __init__(self, settings, current, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("Pill")
        self.setAccessibleName(_("Paleta de colores"))
        self.settings = settings
        self.current = current
        column = QVBoxLayout(self)
        column.setContentsMargins(8, 8, 8, 8)
        column.setSpacing(6)
        colors = recent_colors(settings)
        if colors:
            column.addLayout(self._row(colors))
        column.addLayout(self._row([c for c in BASE_COLORS if c not in colors], columns=8))
        more = QPushButton(_("Más colores…"))
        more.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        more.clicked.connect(self._more)
        column.addWidget(more)

    def _row(self, colors, columns=None):
        grid = QGridLayout()
        grid.setSpacing(4)
        for index, color in enumerate(colors):
            button = swatch(color, color.upper())
            button.clicked.connect(lambda _=False, c=color: self._pick(c))
            grid.addWidget(button, index // (columns or 6), index % (columns or 6))
        return grid

    def _pick(self, color):
        self.close()
        self.picked.emit(color)

    def _more(self):
        self.close()
        color = QColorDialog.getColor(QColor(self.current), self.parentWidget(), _("Color"))
        if color.isValid():
            self.picked.emit(color.name())


class FloatingFormatBar(QFrame):
    """One pill-shaped bar whose controls depend on what is being edited.

    Controls emit actionRequested(name, value); the canvas applies them. Programmatic
    updates go through set_values, which never emits.
    """

    actionRequested = Signal(str, object)

    def __init__(self, view, settings):
        super().__init__(view.viewport())
        self.setObjectName("Pill")
        self.setAccessibleName(_("Barra de formato"))
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_NoMousePropagation)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.settings = settings
        self.profile = None
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(4, 4, 4, 4)
        self.row.setSpacing(4)
        self.groups = {}
        self._build_text()
        self._build_markup()
        self._build_shape()
        self._build_note()
        self._build_field()
        self._build_selection()
        self._build_object()
        self.setVisible(False)

    # Construction -----------------------------------------------------------

    def _group(self, name, spacing=4):
        group = QWidget()
        layout = QHBoxLayout(group)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(spacing)
        self.row.addWidget(group)
        self.groups[name] = group
        group.setVisible(False)
        return layout

    def _tool(self, text, tooltip, handler=None, checkable=False, icon=None):
        button = QToolButton()
        if icon is not None:
            button.setIcon(icon)
            button.setIconSize(QSize(18, 18))
        else:
            button.setText(text)
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setCheckable(checkable)
        # Fixed widths keep the bar inside a narrow document view (the stylesheet pads tool buttons).
        button.setFixedWidth(max(26, button.fontMetrics().horizontalAdvance(text) + 8) if text else 26)
        if handler is not None:
            button.clicked.connect(handler)
        return button

    def _emit(self, name, value=None):
        self.actionRequested.emit(name, value)

    def _build_text(self):
        layout = self._group("text", spacing=2)
        self.family = QComboBox()
        self.family.addItems(FAMILIES)
        self.family.setToolTip(_("Tipo de letra"))
        self.family.setAccessibleName(_("Tipo de letra"))
        self.family.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.family.setFixedWidth(52)
        self.family.currentIndexChanged.connect(lambda index: self._emit("family", index))
        layout.addWidget(self.family)
        layout.addWidget(self._tool("−", _("Reducir tamaño (Ctrl+Mayús+<)"), lambda: self._emit("step", -1)))
        self.size_spin = QSpinBox()
        self.size_spin.setRange(6, 144)
        self.size_spin.setValue(12)
        self.size_spin.setSuffix(" pt")
        self.size_spin.setToolTip(_("Tamaño de letra"))
        self.size_spin.setAccessibleName(_("Tamaño de letra"))
        self.size_spin.setFixedWidth(54)
        self.size_spin.valueChanged.connect(lambda value: self._emit("size", value))
        self.size_spin.editingFinished.connect(lambda: self._emit("focus"))
        layout.addWidget(self.size_spin)
        layout.addWidget(self._tool("+", _("Aumentar tamaño (Ctrl+Mayús+>)"), lambda: self._emit("step", 1)))
        self.bold = self._tool(_("N"), _("Negrita (Ctrl+B)"), lambda checked: self._emit("bold", checked), checkable=True)
        self.italic = self._tool(_("K"), _("Cursiva (Ctrl+I)"), lambda checked: self._emit("italic", checked), checkable=True)
        self.underline = self._tool(_("S"), _("Subrayado (Ctrl+U)"), lambda checked: self._emit("underline", checked), checkable=True)
        self.bold.setStyleSheet("QToolButton { font-weight: 700; }")
        self.italic.setStyleSheet("QToolButton { font-style: italic; }")
        underlined = self.underline.font()
        underlined.setUnderline(True)
        self.underline.setFont(underlined)
        layout.addWidget(self.bold)
        layout.addWidget(self.italic)
        layout.addWidget(self.underline)
        self.spacing = QComboBox()
        self.spacing.addItems([_("1,0"), _("1,15"), _("1,5"), _("2,0")])
        self.spacing.setToolTip(_("Interlineado"))
        self.spacing.setAccessibleName(_("Interlineado"))
        self.spacing.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.spacing.setFixedWidth(46)
        self.spacing.currentIndexChanged.connect(lambda index: self._emit("spacing", LINE_SPACINGS[index]))
        layout.addWidget(self.spacing)
        self.align_group = QButtonGroup(self)
        self.align_group.setExclusive(True)
        self.align_buttons = []
        for index, (icon_name, tooltip) in enumerate([("align-left", _("Alinear a la izquierda (Ctrl+L)")), ("align-center", _("Centrar (Ctrl+E)")),
                                                      ("align-right", _("Alinear a la derecha (Ctrl+R)")), ("align-justify", _("Justificar (Ctrl+J)"))]):
            button = self._tool("", tooltip, lambda _=False, i=index: self._emit("align", i), checkable=True, icon=icons.themed_icon(icon_name))
            self.align_group.addButton(button, index)
            self.align_buttons.append(button)
            layout.addWidget(button)
        self.align_buttons[0].setChecked(True)
        self.color_button = swatch(BASE_COLORS[0], _("Color del texto"))
        self.color_button.clicked.connect(lambda: self._emit("pick_color", self.color_button))
        layout.addWidget(self.color_button)
        layout.addWidget(self._tool("", _("Eliminar texto"), lambda: self._emit("delete"), icon=icons.themed_icon("close")))

    def _build_markup(self):
        layout = self._group("markup")
        self.markup_buttons = []
        for color in MARKUP_COLORS:
            button = swatch(color, _("Color {color}", color=color.upper()))
            button.clicked.connect(lambda _=False, c=color: self._emit("color", c))
            layout.addWidget(button)
            self.markup_buttons.append(button)
        layout.addWidget(self._tool(_("Más"), _("Más colores…"), lambda: self._emit("pick_color", self.groups["markup"])))

    def _build_shape(self):
        layout = self._group("shape")
        self.shape_color = swatch(BASE_COLORS[2], _("Color del trazo"))
        self.shape_color.clicked.connect(lambda: self._emit("pick_color", self.shape_color))
        layout.addWidget(self.shape_color)
        self.width_group = QButtonGroup(self)
        self.width_group.setExclusive(True)
        self.width_buttons = []
        for index, width in enumerate(WIDTHS):
            button = self._tool("", _("Grosor {width} pt", width=width), lambda _=False, w=width: self._emit("width", w), checkable=True)
            button.setIcon(QIcon(width_icon(width)))
            button.setIconSize(QSize(28, 16))
            button.setFixedSize(34, 26)
            self.width_group.addButton(button, index)
            self.width_buttons.append(button)
            layout.addWidget(button)
        self.fill = QComboBox()
        self.fill.addItems([_("Sin relleno"), _("Relleno translúcido")])
        self.fill.setToolTip(_("Relleno"))
        self.fill.setAccessibleName(_("Relleno"))
        self.fill.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.fill.currentIndexChanged.connect(lambda index: self._emit("fill", index == 1))
        layout.addWidget(self.fill)
        self.opacity = QComboBox()
        self.opacity.addItems(["100 %", "70 %", "40 %"])
        self.opacity.setToolTip(_("Opacidad"))
        self.opacity.setAccessibleName(_("Opacidad"))
        self.opacity.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.opacity.currentIndexChanged.connect(lambda index: self._emit("opacity", OPACITIES[index]))
        layout.addWidget(self.opacity)

    def _build_note(self):
        layout = self._group("note")
        self.note_color = swatch(TOOL_DEFAULTS["note"]["color"], _("Color de la nota"))
        self.note_color.clicked.connect(lambda: self._emit("pick_color", self.note_color))
        layout.addWidget(self.note_color)

    def _build_field(self):
        layout = self._group("field")
        self.field_kind_group = QButtonGroup(self)
        self.field_kind_group.setExclusive(True)
        self.field_kinds = []
        for index, (label, kind) in enumerate(FIELD_KINDS):
            label = _(label)
            button = self._tool(label, _("Tipo de campo: {tipo}", tipo=label.lower()), checkable=True)
            button.setProperty("kind", kind)
            self.field_kind_group.addButton(button, index)
            self.field_kinds.append(button)
            layout.addWidget(button)
        self.field_kinds[0].setChecked(True)
        self.field_name = QLineEdit()
        self.field_name.setPlaceholderText(_("Nombre del campo"))
        self.field_name.setToolTip(_("Nombre del siguiente campo"))
        self.field_name.setAccessibleName(_("Nombre del campo"))
        self.field_name.setFixedWidth(128)
        layout.addWidget(self.field_name)

    def _build_object(self):
        """Placed stamps and images: opacity for both; rotate and replace for images."""
        layout = self._group("object")
        self.object_opacity = QComboBox()
        self.object_opacity.addItems(["100 %", "70 %", "40 %"])
        self.object_opacity.setToolTip(_("Opacidad"))
        self.object_opacity.setAccessibleName(_("Opacidad"))
        self.object_opacity.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.object_opacity.currentIndexChanged.connect(lambda index: self._emit("opacity", OPACITIES[index]))
        layout.addWidget(self.object_opacity)
        self.object_rotate = self._tool("", _("Girar 90°"), lambda: self._emit("rotate"), icon=icons.themed_icon("rotate"))
        self.object_replace = self._tool("", _("Sustituir imagen"), lambda: self._emit("replace"), icon=icons.themed_icon("image"))
        layout.addWidget(self.object_rotate)
        layout.addWidget(self.object_replace)
        layout.addWidget(self._tool("", _("Eliminar"), lambda: self._emit("delete"), icon=icons.themed_icon("close")))

    def _build_selection(self):
        layout = self._group("selection")
        layout.addWidget(self._tool(_("Copiar"), _("Copiar el texto seleccionado (Ctrl+C)"), lambda: self._emit("copy")))
        layout.addWidget(self._tool(_("Resaltar"), _("Resaltar selección"), lambda: self._emit("markup:highlight")))
        layout.addWidget(self._tool(_("Subrayar"), _("Subrayar selección"), lambda: self._emit("markup:underline")))
        layout.addWidget(self._tool(_("Tachar"), _("Tachar selección"), lambda: self._emit("markup:strikeout")))

    # State -------------------------------------------------------------------

    def field_kind(self):
        checked = self.field_kind_group.checkedId()
        return FIELD_KINDS[max(0, checked)][1]

    def field_name_text(self):
        return self.field_name.text().strip()

    def line_spacing(self):
        return LINE_SPACINGS[max(0, self.spacing.currentIndex())]

    def set_field_name(self, name):
        self.field_name.setText(name)

    def _set_color(self, button, color):
        button.setProperty("swatch", color)
        button.setStyleSheet(swatch_style(color))

    def set_values(self, profile, values):
        """Show values without emitting actions."""
        if not values:
            return
        if profile == "text":
            widgets = [self.family, self.size_spin, self.bold, self.italic, self.underline, self.spacing]
            for widget in widgets:
                widget.blockSignals(True)
            try:
                if "family" in values:
                    self.family.setCurrentIndex(values["family"])
                if "size" in values:
                    self.size_spin.setValue(values["size"])
                if "bold" in values:
                    self.bold.setChecked(values["bold"])
                if "italic" in values:
                    self.italic.setChecked(values["italic"])
                if "underline" in values:
                    self.underline.setChecked(bool(values["underline"]))
                if "spacing" in values:
                    self.spacing.setCurrentIndex(min(range(len(LINE_SPACINGS)), key=lambda i: abs(LINE_SPACINGS[i] - values["spacing"])))
            finally:
                for widget in widgets:
                    widget.blockSignals(False)
            if "align" in values:
                self.align_group.blockSignals(True)
                self.align_buttons[values["align"]].setChecked(True)
                self.align_group.blockSignals(False)
            if "color" in values:
                self._set_color(self.color_button, values["color"])
        elif profile == "shape" or profile == "ink":
            if "color" in values:
                self._set_color(self.shape_color, values["color"])
            if "width" in values:
                index = WIDTHS.index(values["width"]) if values["width"] in WIDTHS else 1
                self.width_group.blockSignals(True)
                self.width_buttons[index].setChecked(True)
                self.width_group.blockSignals(False)
            if "opacity" in values:
                index = min(range(len(OPACITIES)), key=lambda i: abs(OPACITIES[i] - values["opacity"]))
                self.opacity.blockSignals(True)
                self.opacity.setCurrentIndex(index)
                self.opacity.blockSignals(False)
            if "fill" in values:
                self.fill.blockSignals(True)
                self.fill.setCurrentIndex(1 if values["fill"] else 0)
                self.fill.blockSignals(False)
        elif profile == "note":
            if "color" in values:
                self._set_color(self.note_color, values["color"])
        elif profile == "object":
            stamp = values.get("kind") == "stamp"
            self.object_opacity.setVisible(True)
            self.object_rotate.setVisible(not stamp)
            self.object_replace.setVisible(not stamp)
            if "opacity" in values:
                index = min(range(len(OPACITIES)), key=lambda i: abs(OPACITIES[i] - values["opacity"]))
                self.object_opacity.blockSignals(True)
                self.object_opacity.setCurrentIndex(index)
                self.object_opacity.blockSignals(False)
        elif profile == "markup":
            pass

    def show_profile(self, profile, values=None):
        self.profile = profile
        for name, group in self.groups.items():
            group.setVisible(name == profile or (profile == "ink" and name == "shape"))
        self.fill.setVisible(profile == "shape")
        self.set_values(profile, values)
        self.adjustSize()
        self.setVisible(True)
        self.raise_()

    def hide_profile(self):
        self.profile = None
        self.setVisible(False)

    def place(self, anchor=None):
        """Put the bar above the anchor (below it when there is no room), kept inside the viewport."""
        viewport = self.parentWidget().rect()
        self.adjustSize()
        width, height = self.width(), self.height()
        if anchor is None:
            x, y = (viewport.width() - width) // 2, 8
        else:
            x = anchor.center().x() - width // 2
            y = anchor.top() - height - 8
            if y < 8:
                y = anchor.bottom() + 8
        x = max(8, min(x, viewport.width() - width - 8))
        y = max(8, min(y, viewport.height() - height - 8))
        self.move(x, y)


def open_color_popover(parent, settings, current, anchor_widget, callback):
    """Show the colour palette under anchor_widget (or at the top of parent when there is none)."""
    popover = ColorPopover(settings, current, parent)
    popover.picked.connect(callback)
    if anchor_widget is not None:
        position = anchor_widget.mapToGlobal(QPoint(0, anchor_widget.height() + 4))
    else:
        position = parent.mapToGlobal(QPoint(12, 12))
    popover.move(position)
    popover.show()
    return popover
