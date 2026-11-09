"""Interactive PDF canvas: glyph selection, inline editing and object movement."""
from __future__ import annotations

import hashlib
import math
import os
import time
from collections import OrderedDict
from dataclasses import dataclass

import pymupdf as fitz
from PySide6.QtCore import Qt, QEvent, QRectF, QPointF, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QTextBlockFormat, QTextCursor
from PySide6.QtWidgets import (QApplication, QComboBox, QGraphicsRectItem, QGraphicsSimpleTextItem, QLineEdit, QToolButton, QGraphicsView, QGraphicsScene, QFrame,
                               QGraphicsTextItem, QHBoxLayout, QLabel, QMessageBox, QMenu,
                               QPlainTextEdit, QPushButton, QVBoxLayout)

from .floating_bar import FloatingFormatBar, TEXT_SIZES, format_shortcut, remember_color, rgb_of, set_tool_style, tool_style
from . import theme
from .engine import PDFEngine
from .lang import _, N_
from .signing_ui import FillMode

ANNOTATION_PROFILES = {"Highlight": "markup", "Underline": "markup", "StrikeOut": "markup",
                       "Square": "shape", "Circle": "shape", "Ink": "ink", "Text": "note", "Stamp": "object",
                       "Line": "ink", "FreeText": "note"}
TEXT_FORMAT_ACTIONS = ("size", "family", "bold", "italic", "underline", "spacing", "align")
MOVABLE_ANNOTATIONS = ("Square", "Circle", "Text", "FreeText")
RESIZABLE_ANNOTATIONS = ("Square", "Circle", "FreeText")
LINE_MODES = ("line", "arrow")
# Single letters that pick a tool when the page has focus (no text is being typed). The rail shows them in its tooltips.
TOOL_LETTERS = {"V": "select", "H": "hand", "E": "edit", "T": "text", "R": "replace", "I": "image", "L": "link",
                "N": "note", "D": "ink", "M": "highlight", "U": "underline", "X": "strikeout", "F": "fill", "K": "field", "C": "redact"}
# Continuous layouts: pixmaps drawn per timer tick at most, pixmaps kept for recently seen pages, and the tick interval.
LAZY_RENDER_BUDGET = 2
LAZY_CACHE_SIZE = 8
LAZY_INTERVAL_MS = 16


def pdf_font(font, flags=0):
    lower = font.lower()
    bold = bool(flags & 16) or "bold" in lower
    italic = bool(flags & 2) or "italic" in lower or "oblique" in lower
    if any(name in lower for name in ("times", "serif", "roman")):
        return {(False, False): "tiro", (True, False): "tibo", (False, True): "tiit", (True, True): "tibi"}[bold, italic]
    if any(name in lower for name in ("courier", "mono")):
        return {(False, False): "cour", (True, False): "cobo", (False, True): "coit", (True, True): "cobi"}[bold, italic]
    return {(False, False): "helv", (True, False): "hebo", (False, True): "heit", (True, True): "hebi"}[bold, italic]


def qt_font(name, size):
    font = QFont("Times New Roman" if name.startswith("ti") else "Courier New" if name.startswith("co") else "Arial")
    font.setPixelSize(max(1, round(size)))
    font.setBold(name in ("hebo", "hebi", "tibo", "tibi", "cobo", "cobi"))
    font.setItalic(name in ("heit", "hebi", "tiit", "tibi", "coit", "cobi"))
    return font


@dataclass
class TextRun:
    rect: fitz.Rect
    text: str
    size: float
    font: str
    color: tuple
    direction: tuple = (1, 0)


class InlineText(QGraphicsTextItem):
    def __init__(self, view, rect, text, size, font, color, original=None, page=None):
        super().__init__()
        self.view = view
        self.pdf_rect = fitz.Rect(rect)
        self.original = original
        self.size = size
        self.font_name = font
        self.color = color
        self.setFont(qt_font(font, size))
        self.setDefaultTextColor(QColor.fromRgbF(*color))
        self.document().setDocumentMargin(0)
        self.setTextWidth(rect.width)
        self.setPlainText(text)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
        self.document().setUndoRedoEnabled(True)
        self.document().undoAvailable.connect(view.window.update_history_actions)
        self.document().redoAvailable.connect(view.window.update_history_actions)
        self.align = 0
        self.underline = False
        self.line_spacing = 1.0
        self.setFlag(self.GraphicsItemFlag.ItemIsFocusable)
        self.setZValue(20)
        self.setScale(view.scale_factor)
        self.setRotation(view.page_frame(page)[0].rotation)
        self.setPos(view.scene_point(rect.tl, page))

    def apply_layout(self):
        """Underline and line spacing, applied to every line of the editor at once."""
        font = self.font()
        font.setUnderline(self.underline)
        self.setFont(font)
        cursor = QTextCursor(self.document())
        cursor.select(QTextCursor.SelectionType.Document)
        block_format = QTextBlockFormat()
        block_format.setLineHeight(self.line_spacing * 100, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
        cursor.mergeBlockFormat(block_format)
        cursor.clearSelection()

    def paint(self, painter, option, widget=None):
        painter.fillRect(self.boundingRect().adjusted(-2, -2, 2, 2), QColor(255, 255, 255, 242))
        super().paint(painter, option, widget)
        painter.setPen(QPen(QColor("#087f70"), 0.8))
        painter.drawRect(self.boundingRect().adjusted(-2, -2, 2, 2))

    def keyPressEvent(self, event):
        shortcut = format_shortcut(event)
        if self.view.mode == "fill" and event.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab, Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.view.fill.editor_key(event):
            event.accept()
        elif shortcut is not None:
            self.view.apply_shortcut(*shortcut)
            event.accept()
        elif event.key() == Qt.Key.Key_Escape:
            QTimer.singleShot(0, self.view.cancel_editor)
            event.accept()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            QTimer.singleShot(0, self.view.commit_editor)
            event.accept()
        else:
            super().keyPressEvent(event)


class NoteEditor(QPlainTextEdit):
    def __init__(self, popover):
        super().__init__()
        self.popover = popover

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape or (event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.popover.finish()
            event.accept()
        else:
            super().keyPressEvent(event)


class NotePopover(QFrame):
    """Comment text anchored to a note icon. An empty note is removed when the popover closes."""

    def __init__(self, view, xref, anchor):
        super().__init__(view.viewport())
        self.setObjectName("Pill")
        self.setAccessibleName(_("Comentario"))
        self.setAttribute(Qt.WidgetAttribute.WA_NoMousePropagation)
        self.view = view
        self.xref = xref
        self.closed = False
        column = QVBoxLayout(self)
        column.setContentsMargins(8, 8, 8, 8)
        column.setSpacing(6)
        self.edit = NoteEditor(self)
        self.edit.setPlaceholderText(_("Escribe el comentario"))
        self.edit.setAccessibleName(_("Texto del comentario"))
        self.edit.setFixedSize(240, 96)
        column.addWidget(self.edit)
        row = QHBoxLayout()
        hint = QLabel(_("Ctrl+Intro guarda · Esc cierra"))
        hint.setStyleSheet("background: transparent;")
        row.addWidget(hint, 1)
        save = QPushButton(_("Guardar"))
        save.clicked.connect(self.finish)
        row.addWidget(save)
        column.addLayout(row)
        self.place(anchor)
        self.show()
        self.edit.setFocus()

    def place(self, anchor):
        viewport = self.parentWidget().rect()
        self.adjustSize()
        x = min(anchor.right() + 8, viewport.width() - self.width() - 8)
        y = min(max(8, anchor.top()), viewport.height() - self.height() - 8)
        self.move(max(8, x), max(8, y))

    def finish(self):
        if self.closed:
            return
        self.closed = True
        content = self.edit.toPlainText().strip()
        if self.view.note_popover is self:
            self.view.note_popover = None
            self.view.note_popover_rect = None
        self.hide()
        self.deleteLater()
        window, xref = self.view.window, self.xref
        if content:
            window.run(lambda: window.change(lambda: window.engine.set_annotation_content(window.page, xref, content)))
        else:
            window.run(lambda: window.change(lambda: window.engine.delete_annotation(window.page, xref)))
        self.view.setFocus()


class MeasureMode:
    """Medir: distance by dragging, area by clicking the corners; the scale is edited in a bar over the page."""

    def __init__(self, view):
        self.view = view
        self.kind = "distance"
        self.points = []
        self.cursor = None
        self.items = []
        self.bar = bar = QFrame(view.viewport())
        bar.setObjectName("Pill")
        bar.setAccessibleName(_("Barra de medición"))
        bar.setAttribute(Qt.WidgetAttribute.WA_NoMousePropagation)
        row = QHBoxLayout(bar)
        row.setContentsMargins(6, 4, 6, 4)
        row.setSpacing(4)
        self.kind_buttons = {}
        for key, text in (("distance", N_("Distancia")), ("area", N_("Área"))):
            button = QToolButton()
            button.setText(_(text))
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, k=key: self.set_kind(k))
            self.kind_buttons[key] = button
            row.addWidget(button)
        row.addWidget(QLabel(_("1 pt =")))
        self.scale_edit = QLineEdit()
        self.scale_edit.setAccessibleName(_("Valor de 1 punto en la unidad elegida"))
        self.scale_edit.setFixedWidth(72)
        self.scale_edit.editingFinished.connect(self.scale_edited)
        row.addWidget(self.scale_edit)
        self.unit_box = QComboBox()
        self.unit_box.setAccessibleName(_("Unidad de medida"))
        self.unit_box.addItems(PDFEngine.MEASURE_UNITS)
        self.unit_box.activated.connect(lambda _: self.unit_chosen())
        row.addWidget(self.unit_box)
        bar.hide()
        self.load_scale()
        self.set_kind("distance")

    # Scale ----------------------------------------------------------------------

    @property
    def settings(self):
        return self.view.window.settings

    def document_key(self):
        """QSettings prefix for the open document's own scale, or None when it has no path yet."""
        window = self.view.window
        path = window.engine.path if window.has_doc() else None
        if not path:
            return None
        return "measure/docs/" + hashlib.sha1(os.path.normcase(str(path)).encode("utf-8")).hexdigest()[:20]

    def scale(self):
        """(units per page point, unit): this document's own scale, else the last one used, else real size."""
        prefix = self.document_key()
        if prefix is None or self.settings.value(prefix + "/scale") is None:
            prefix = "measure"
        unit = str(self.settings.value(prefix + "/unit", "mm") or "mm")
        if unit not in PDFEngine.MEASURE_UNITS:
            unit = "mm"
        try:
            value = float(self.settings.value(prefix + "/scale", PDFEngine.measure_true_scale(unit)))
        except (TypeError, ValueError):
            value = 0.0
        return (value if math.isfinite(value) and value > 0 else PDFEngine.measure_true_scale(unit)), unit

    def load_scale(self):
        value, unit = self.scale()
        self.unit_box.setCurrentText(unit)
        self.scale_edit.setText(f"{value:.6g}".replace(".", ","))

    def set_scale(self, value, unit):
        if not (math.isfinite(value) and value > 0) or unit not in PDFEngine.MEASURE_UNITS:
            raise ValueError(_("La escala debe ser un número mayor que cero."))
        for prefix in ("measure", self.document_key()):
            if prefix:
                self.settings.setValue(prefix + "/scale", float(value))
                self.settings.setValue(prefix + "/unit", unit)
        self.load_scale()
        self.redraw_preview()

    def scale_edited(self):
        try:
            self.set_scale(float(self.scale_edit.text().strip().replace(",", ".")), self.unit_box.currentText())
        except ValueError:
            self.view.window.statusBar().showMessage(_("La escala debe ser un número mayor que cero"))
            self.load_scale()

    def unit_chosen(self):
        unit = self.unit_box.currentText()
        self.set_scale(PDFEngine.measure_true_scale(unit), unit)

    def set_kind(self, kind):
        self.kind = kind
        for key, button in self.kind_buttons.items():
            button.setChecked(key == kind)
        hint = _("Arrastra sobre la página para medir una distancia") if kind == "distance" else _("Haz clic en cada vértice y haz doble clic para cerrar el área")
        for button in self.kind_buttons.values():
            button.setToolTip(hint)
        self.view.window.statusBar().showMessage(hint)
        self.cancel()
        self.place()

    # Placement and state --------------------------------------------------------

    def place(self):
        self.bar.adjustSize()
        self.bar.move(max(8, (self.view.viewport().width() - self.bar.width()) // 2), 10)
        self.bar.raise_()

    def set_active(self, active):
        self.bar.setVisible(active)
        if active:
            self.load_scale()
            self.place()
        else:
            self.cancel()

    def clear_preview(self):
        for item in self.items:
            if self.view.alive(item):
                self.view.scene().removeItem(item)
        self.items = []

    def cancel(self):
        self.points = []
        self.cursor = None
        self.clear_preview()

    # Drawing --------------------------------------------------------------------

    def label_item(self, text, anchor, z=13):
        tokens = theme.current_tokens()
        label = QGraphicsSimpleTextItem(text)
        font = QFont(label.font())
        font.setPointSizeF(10)
        font.setBold(True)
        label.setFont(font)
        label.setBrush(QBrush(QColor(tokens["ink"])))
        box = label.boundingRect().adjusted(-5, -2, 5, 2)
        back = QGraphicsRectItem(box)
        back.setBrush(QBrush(QColor(tokens["surface1"])))
        back.setPen(QPen(QColor(tokens["accent"]), 1))
        back.setZValue(z)
        label.setParentItem(back)
        back.setPos(anchor.x() - box.width() / 2, anchor.y() - box.height() - 6)
        self.view.scene().addItem(back)
        return back

    @staticmethod
    def centroid(points):
        return QPointF(sum(p.x() for p in points) / len(points), sum(p.y() for p in points) / len(points))

    def draw(self):
        """Labels of the measurements already saved on the page; the view calls this after drawing the page."""
        self.clear_preview()
        if self.view.mode != "measure" or not self.view.window.has_doc():
            return
        if not self.scale_edit.hasFocus():
            self.load_scale()
        for found in self.view.window.engine.measurements(self.view.window.page):
            points = [self.view.scene_point(p) for p in found["points"]]
            if points and found["label"]:
                self.view.layer_items.append(self.label_item(found["label"], self.centroid(points)))

    def redraw_preview(self):
        self.clear_preview()
        points = self.points + ([self.cursor] if self.points and self.cursor is not None else [])
        if len(points) < 2:
            return
        area = self.kind == "area"
        scene = [self.view.scene_point(p) for p in points]
        pen = QPen(QColor("#d93025"), 1.6, Qt.PenStyle.DashLine)
        segments = list(zip(scene, scene[1:])) + ([(scene[-1], scene[0])] if area and len(scene) >= 3 else [])
        for a, b in segments:
            line = self.view.scene().addLine(a.x(), a.y(), b.x(), b.y(), pen)
            line.setZValue(12)
            self.items.append(line)
        if area and len(points) < 3:
            return
        value, unit = self.scale()
        amount = PDFEngine.measure_area(points) * value * value if area else PDFEngine.measure_length(points) * value
        self.items.append(self.label_item(PDFEngine.format_measure(amount, unit, area), self.centroid(scene), 14))

    # Mouse and keys -------------------------------------------------------------

    def press(self, scene_point, point):
        if self.kind == "distance":
            self.points = [point]
        elif self.points and (self.view.scene_point(self.points[-1]) - scene_point).manhattanLength() < 4:
            return
        else:
            self.points.append(point)
        self.cursor = point
        self.redraw_preview()

    def move(self, point):
        if self.points:
            self.cursor = point
            self.redraw_preview()

    def release(self, scene_point, point):
        if self.kind != "distance" or not self.points:
            return
        start = self.points[0]
        if (self.view.scene_point(start) - scene_point).manhattanLength() < 6:
            self.cancel()
            self.view.window.statusBar().showMessage(_("Arrastra para medir una distancia"))
            return
        self.commit([start, point])

    def double_click(self):
        if self.kind == "area":
            self.finish_area()

    def finish_area(self):
        if len(self.points) < 3:
            self.view.window.statusBar().showMessage(_("Marca al menos tres puntos para medir un área"))
            return
        self.commit(list(self.points))

    def key(self, event):
        if not self.points:
            return False
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.kind == "area":
            self.finish_area()
        elif event.key() == Qt.Key.Key_Escape:
            self.cancel()
        elif event.key() == Qt.Key.Key_Backspace and self.kind == "area":
            self.points.pop()
            self.redraw_preview()
        else:
            return False
        return True

    def commit(self, points):
        window, area = self.view.window, self.kind == "area"
        value, unit = self.scale()
        self.cancel()

        def operation():
            label = window.engine.measure_value(points, value, unit, area)
            window.change(lambda: window.engine.add_measurement(window.page, points, value, unit, area))
            window.statusBar().showMessage(_("Medida: {label}", label=label))

        window.run(operation)


class PageView(QGraphicsView):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.setScene(QGraphicsScene(self))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.mode = "select"
        self.scale_factor = 1.0
        self.origin = None
        self.preview = None
        self.ink = []
        self.last_drag = None
        self.chars = []
        self.runs = []
        self.selection_anchor = None
        self.selection_end = None
        self.selection_items = []
        self.selected_text = ""
        self.selected_rects = []
        self.selected_run = None
        self.object_outline = None
        self.editor = None
        self.drag_run = None
        self.ghost = None
        self.images = []
        self.selected_image = None
        self.drag_image = None
        self.resize_corner = None
        self.image_handles = []
        self.selected_annot = None
        self.annot_drag = None
        self.note_popover = None
        self.page_rect = None
        self.note_popover_rect = None
        # Scene position of the page being edited (0, 0 in one-page view). Other visible pages are only shown.
        self.page_offset = QPointF(0, 0)
        self.page_rects = []
        self.companion_rects = []
        # Page origins (top-left corners) and rectangles in scene units, by page index.
        self.page_origin = {}
        self.page_geometry = {}
        # Continuous layouts: lazy flag, pixmap items on screen, LRU cache of rendered pixmaps, text layer items.
        self.lazy = False
        self.page_items = {}
        self.page_cache = OrderedDict()
        self.layer_items = []
        self.char_cache = {}
        self.selection_page = None
        self.selection_end_page = None
        # The page opened from the page box or search stays current until the view leaves the position it was put in.
        self.pin_page = None
        self.pin_value = 0
        self.lazy_timer = QTimer(self)
        self.lazy_timer.setSingleShot(True)
        self.lazy_timer.setInterval(LAZY_INTERVAL_MS)
        self.lazy_timer.timeout.connect(lambda: self.window.continuous_view_moved())
        self.last_wheel_turn = 0.0
        self.fill = FillMode(self)
        self.format_bar = FloatingFormatBar(self, window.settings)
        self.measure = MeasureMode(self)
        self.format_bar.actionRequested.connect(self.format_action)
        self.horizontalScrollBar().valueChanged.connect(lambda _: self.place_format_bar())
        self.verticalScrollBar().valueChanged.connect(lambda _: self.place_format_bar())
        self.horizontalScrollBar().valueChanged.connect(lambda _: self.schedule_lazy())
        self.verticalScrollBar().valueChanged.connect(lambda _: self.schedule_lazy())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.place_format_bar()
        self.measure.place()
        self.schedule_lazy()
        self.window.view_resized()

    def event(self, event):
        # Format shortcuts belong to the inline editor while it is open (Ctrl+B beats the rail toggle, Ctrl+E, Ctrl+R).
        if event.type() == QEvent.Type.ShortcutOverride and self.editor is not None and format_shortcut(event) is not None:
            event.accept()
            return True
        # While a field or quick text is being typed, plain letters belong to the editor, not to rail shortcuts.
        if event.type() == QEvent.Type.ShortcutOverride and self.editor is not None and event.text() and not event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier):
            event.accept()
            return True
        # Tab moves between fields in the fill mode, so the scroll area must not take focus.
        if event.type() == QEvent.Type.KeyPress and self.mode == "fill" and self.editor is None and event.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            self.keyPressEvent(event)
            return True
        return super().event(event)

    def drawBackground(self, painter, rect):
        super().drawBackground(painter, rect)
        pages = self.page_rects or [self.page_rect if self.page_rect is not None else self.scene().sceneRect()]
        if pages[0].isEmpty():
            return
        if self.lazy:
            pages = [page for page in pages if page.adjusted(-40, -40, 40, 40).intersects(rect)]
        from .theme import current_tokens
        tokens = current_tokens()
        shadow = QColor(tokens["shadow"])
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for page in pages:
            painter.setPen(Qt.PenStyle.NoPen)
            for step in range(12):
                spread = step * 1.5
                shadow.setAlpha(round(40 * (1 - step / 12) ** 2.0))
                painter.setBrush(shadow)
                painter.drawRoundedRect(page.adjusted(-spread, -spread + 3, spread, spread + 5), 2 + spread, 2 + spread)
            edge = QColor(tokens["shadow"])
            edge.setAlpha(60)
            painter.setPen(QPen(edge, 0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(page.adjusted(-0.5, -0.5, 0.5, 0.5))
        painter.restore()

    def page_frame(self, page=None):
        """Page and scene origin of the given page. Without an index, the page being edited."""
        if page is None or page == self.window.page or page not in self.page_origin:
            return self.window.engine.doc[self.window.page], self.page_offset
        return self.window.engine.doc[page], self.page_origin[page]

    def pdf_point(self, scene_point, page=None):
        doc_page, offset = self.page_frame(page)
        p = fitz.Point((scene_point.x() - offset.x()) / self.scale_factor, (scene_point.y() - offset.y()) / self.scale_factor)
        return p * doc_page.derotation_matrix

    def scene_point(self, point, page=None):
        doc_page, offset = self.page_frame(page)
        p = fitz.Point(point) * doc_page.rotation_matrix
        return QPointF(p.x * self.scale_factor + offset.x(), p.y * self.scale_factor + offset.y())

    def scene_rect(self, rect, page=None):
        doc_page, offset = self.page_frame(page)
        r = fitz.Rect(rect) * doc_page.rotation_matrix
        return QRectF(r.x0 * self.scale_factor + offset.x(), r.y0 * self.scale_factor + offset.y(), r.width * self.scale_factor, r.height * self.scale_factor)

    def reset_transient(self, clear_selection=True):
        self.origin = None
        self.preview = None
        self.ink = []
        self.drag_run = None
        self.ghost = None
        self.editor = None
        self.object_outline = None
        self.selected_image = self.drag_image = self.resize_corner = None
        self.image_handles = []
        self.selected_annot = self.annot_drag = None
        if clear_selection:
            self.selection_anchor = self.selection_end = self.selection_page = self.selection_end_page = None
            self.selected_text = ""
            self.selected_rects = []
            self.selected_run = None
            self.selection_items = []
        self.sync_format_bar()

    def alive(self, item):
        """False for items that were removed from the scene or deleted with it."""
        try:
            return item.scene() is self.scene()
        except RuntimeError:
            return False

    def add_layer(self, rect, pen, brush=None, z=3):
        """Outline of the text layer (edit, replace, link modes). It is removed when the current page changes."""
        item = self.scene().addRect(rect, pen, brush) if brush is not None else self.scene().addRect(rect, pen)
        item.setZValue(z)
        self.layer_items.append(item)
        return item

    def clear_layer(self):
        for item in self.layer_items:
            if self.alive(item):
                self.scene().removeItem(item)
        self.layer_items = []

    def populate_text(self):
        self.clear_layer()
        self.char_cache = {}
        self.chars = []
        self.runs = []
        self.images = self.window.engine.images(self.window.page)
        raw = self.window.engine.doc[self.window.page].get_text("rawdict", sort=True)
        line_index = 0
        for block in raw["blocks"]:
            block_runs = []
            for line in block.get("lines", []):
                for span in line["spans"]:
                    text = "".join(c["c"] for c in span["chars"])
                    color = fitz.sRGB_to_pdf(span["color"])
                    block_runs.append(TextRun(fitz.Rect(span["bbox"]), text, span["size"], pdf_font(span["font"], span["flags"]), color, tuple(line["dir"])))
                    for char in span["chars"]:
                        self.chars.append((char["c"], fitz.Rect(char["bbox"]), line_index))
                self.chars.append(("\n", None, line_index))
                line_index += 1
            if block_runs:
                first = block_runs[0]
                # Group compatible lines into an editable paragraph. Mixed styles
                # remain separate runs so that editing does not flatten them.
                if all((r.size, r.font, r.color, r.direction) == (first.size, first.font, first.color, first.direction) for r in block_runs):
                    bounds = fitz.Rect(first.rect)
                    for run in block_runs[1:]:
                        bounds |= run.rect
                    text = "\n".join("".join(char["c"] for span in line["spans"] for char in span["chars"])
                                     for line in block.get("lines", []))
                    self.runs.append(TextRun(bounds, text, first.size, first.font, first.color, first.direction))
                else:
                    self.runs.extend(block_runs)
        if self.mode in ("edit", "replace"):
            for run in self.runs:
                self.add_layer(self.scene_rect(run.rect), QPen(QColor(8, 127, 112, 55), 0.8))
        if self.mode == "edit":
            for image in self.images:
                self.add_layer(self.scene_rect(image["rect"]), QPen(QColor(8, 127, 112, 75), 0.8))
        if self.mode == "link":
            for link in self.window.engine.links(self.window.page):
                self.add_layer(self.scene_rect(link["from"]), QPen(QColor("#386bdd"), 1.3), QColor(55, 110, 230, 35))
        self.fill.draw()
        self.measure.draw()

    # Continuous layouts ----------------------------------------------------------

    def reset_lazy(self):
        """Forgets the pages of the last scene. Call it before the scene is cleared."""
        self.lazy_timer.stop()
        self.lazy = False
        self.page_origin = {}
        self.page_geometry = {}
        self.page_items = {}
        self.page_cache = OrderedDict()
        self.layer_items = []
        self.pin_page = None
        self.char_cache = {}

    def build_continuous(self, origins, rects, placeholder):
        """Scene of a continuous layout: a gray placeholder of the right size for every page. Pixmaps come later, as pages are seen."""
        self.reset_lazy()
        self.scene().clear()
        self.lazy = True
        self.page_origin = origins
        self.page_geometry = rects
        self.page_rects = list(rects.values())
        self.companion_rects = []
        for rect in rects.values():
            self.scene().addRect(rect, QPen(Qt.PenStyle.NoPen), QColor(placeholder)).setZValue(-1)

    def schedule_lazy(self):
        if self.lazy and not self.lazy_timer.isActive():
            self.lazy_timer.start()

    def set_current_page(self, index):
        """Another page becomes current in a continuous layout: the text layer changes, the scene does not."""
        spans_pages = self.selection_anchor is not None and self.selection_page is not None and self.selection_page != self.selection_end_page
        saved = (self.selection_anchor, self.selection_end, self.selection_page, self.selected_text, self.selection_items, self.selection_end_page)
        self.reset_transient()
        if spans_pages:
            self.selection_anchor, self.selection_end, self.selection_page, self.selected_text, self.selection_items, self.selection_end_page = saved
        self.page_offset = self.page_origin[index]
        self.page_rect = self.page_geometry[index]
        self.populate_text()

    def visible_geometry(self):
        """Rectangles of the pages drawn in the view: every page in a continuous layout, the current one and its companion otherwise."""
        if self.page_geometry:
            return self.page_geometry
        found = {self.window.page: self.page_rect} if self.page_rect is not None else {}
        found.update(dict(self.companion_rects))
        return found

    def page_index_at(self, scene_point):
        return next((index for index, rect in self.page_geometry.items() if rect.contains(scene_point)), None)

    def nearest_page(self, scene_point):
        """The page under the point or, between pages, the closest one."""
        geometry = self.visible_geometry()
        if not geometry:
            return self.window.page
        def distance(rect):
            dx = max(rect.left() - scene_point.x(), 0, scene_point.x() - rect.right())
            dy = max(rect.top() - scene_point.y(), 0, scene_point.y() - rect.bottom())
            return dy * dy * 4 + dx * dx
        return min(geometry, key=lambda index: distance(geometry[index]))

    def page_chars(self, index):
        """Characters of a page as (char, rect, line). The current page uses the text layer; others are read once and cached."""
        if index == self.window.page:
            return self.chars
        cached = self.char_cache.get(index)
        if cached is None:
            cached = []
            line_index = 0
            raw = self.window.engine.doc[index].get_text("rawdict", sort=True)
            for block in raw["blocks"]:
                for line in block.get("lines", []):
                    for span in line["spans"]:
                        cached.extend((char["c"], fitz.Rect(char["bbox"]), line_index) for char in span["chars"])
                    cached.append(("\n", None, line_index))
                    line_index += 1
            self.char_cache[index] = cached
        return cached

    def switch_page_under(self, scene_point):
        """A click on a page of a continuous layout makes that page the current one, so its text and objects are the ones edited."""
        index = self.page_index_at(scene_point)
        if index is not None and index != self.window.page:
            self.window.set_current_page(index)

    def viewport_scene_rect(self):
        return self.mapToScene(self.viewport().rect()).boundingRect()

    def onscreen_pages(self):
        viewport = self.viewport_scene_rect()
        return [index for index, rect in self.page_geometry.items() if rect.intersects(viewport)]

    def most_visible_page(self, indices):
        """The page that fills the largest part of the view."""
        viewport = self.viewport_scene_rect()
        best, area = None, 0.0
        for index in indices:
            overlap = self.page_geometry[index].intersected(viewport)
            if overlap.width() * overlap.height() > area:
                best, area = index, overlap.width() * overlap.height()
        return best

    def sync_lazy_pages(self, wanted, render, budget=LAZY_RENDER_BUDGET):
        """Shows the pixmaps of the wanted pages and removes the others. Returns True when some wanted pages still wait for a later tick."""
        scene = self.scene()
        keep = set(wanted)
        for index in [index for index in self.page_items if index not in keep]:
            item = self.page_items.pop(index)
            if self.alive(item):
                scene.removeItem(item)
        center = self.viewport_scene_rect().center().y()
        waiting = [index for index in wanted if index not in self.page_items]
        waiting.sort(key=lambda index: abs(self.page_geometry[index].center().y() - center))
        limit = max(LAZY_CACHE_SIZE, len(keep))
        rendered = 0
        for index in waiting:
            pixmap = self.page_cache.get(index)
            if pixmap is None:
                if rendered == budget:
                    return True
                pixmap = render(index)
                rendered += 1
            self.page_cache[index] = pixmap
            self.page_cache.move_to_end(index)
            while len(self.page_cache) > limit:
                self.page_cache.popitem(last=False)
            item = scene.addPixmap(pixmap)
            item.setPos(self.page_origin[index])
            self.page_items[index] = item
        return False

    def run_at(self, point):
        return next((r for r in self.runs if r.rect.contains(point)), None)

    def image_at(self, point):
        return next((image for image in reversed(self.images) if image["rect"].contains(point)), None)

    def image_corner_at(self, point):
        if self.selected_image:
            rect = self.selected_image["rect"]
            for name in ("tl", "tr", "bl", "br"):
                if abs(point - getattr(rect, name)) * self.scale_factor <= 9:
                    return name
        return None

    def clear_object_selection(self):
        self.selected_run = self.selected_image = self.selected_annot = None
        for item in [self.object_outline, *self.image_handles]:
            if item is not None and item.scene() is self.scene():
                self.scene().removeItem(item)
        self.object_outline = None
        self.image_handles = []

    def select_image(self, image):
        self.clear_object_selection()
        self.selected_image = image
        self.object_outline = self.scene().addRect(self.scene_rect(image["rect"]), QPen(QColor("#087f70"), 1.5))
        self.object_outline.setZValue(8)
        self.update_image_outline(image["rect"])
        self.window.statusBar().showMessage(_("Arrastra para mover · Arrastra una esquina para redimensionar · Doble clic para sustituir · Supr elimina") if image["editable"] else _("Esta imagen está dentro de una estructura que todavía no admite edición"))
        self.sync_format_bar()

    def update_image_outline(self, rect):
        self.object_outline.setRect(self.scene_rect(rect))
        for item in self.image_handles:
            self.scene().removeItem(item)
        self.image_handles = []
        if self.selected_image and self.selected_image["editable"]:
            for corner in (rect.tl, rect.tr, rect.bl, rect.br):
                p = self.scene_point(corner)
                item = self.scene().addRect(QRectF(p.x() - 4, p.y() - 4, 8, 8), QPen(QColor("#087f70")), QColor("white"))
                item.setZValue(9)
                self.image_handles.append(item)

    def image_target(self, point):
        original = self.drag_image["rect"]
        if self.resize_corner:
            opposite = {"tl": "br", "tr": "bl", "bl": "tr", "br": "tl"}[self.resize_corner]
            anchor = getattr(original, opposite)
            return fitz.Rect(min(anchor.x, point.x), min(anchor.y, point.y), max(anchor.x, point.x), max(anchor.y, point.y))
        delta = point - self.pdf_point(self.origin)
        return original + (delta.x, delta.y, delta.x, delta.y)

    def delete_selected_image(self):
        image = self.selected_image
        if image is not None and image["editable"]:
            self.clear_object_selection()
            self.window.run(lambda: self.window.change(lambda: self.window.engine.delete_image(self.window.page, image["index"])))

    def rotate_selected_image(self):
        image = self.selected_image
        if image is None:
            return
        if not image["editable"]:
            raise ValueError(_("Esta imagen no admite edición individual todavía."))
        self.clear_object_selection()
        self.window.run(lambda: self.window.change(lambda: self.window.engine.rotate_image(self.window.page, image["index"])))

    def set_selected_image_opacity(self, value):
        image = self.selected_image
        if not image["editable"]:
            self.window.statusBar().showMessage(_("Esta imagen no admite edición individual todavía."))
            return
        index = image["index"]
        self.window.run(lambda: self.window.change(lambda: self.window.engine.set_image_opacity(self.window.page, index, value)))
        for found in self.images:
            if found["index"] == index:
                self.select_image(found)
                break

    def replace_selected_image(self, image):
        from PySide6.QtWidgets import QFileDialog
        if not image["editable"]:
            raise ValueError(_("Esta imagen no admite edición individual todavía."))
        path, _filter = QFileDialog.getOpenFileName(self.window, _("Sustituir imagen"), "", _("Imágenes (*.png *.jpg *.jpeg *.tif *.tiff *.bmp)"))
        if path:
            self.window.change(lambda: self.window.engine.replace_image(self.window.page, image["index"], path))

    def set_mode(self, mode):
        if self.note_popover is not None:
            self.note_popover.finish()
        self.mode = mode
        self.setDragMode(self.DragMode.ScrollHandDrag if mode == "hand" else self.DragMode.NoDrag)
        self.setCursor(Qt.CursorShape.OpenHandCursor if mode == "hand" else Qt.CursorShape.ArrowCursor if mode == "edit" else Qt.CursorShape.IBeamCursor if mode in ("select", "text", "replace", "highlight", "underline", "strikeout") else Qt.CursorShape.CrossCursor)
        self.clear_object_selection()
        self.fill.set_active(mode == "fill")
        self.measure.set_active(mode == "measure")
        self.sync_format_bar()

    # Format bar -----------------------------------------------------------------

    def tool_style(self, tool):
        return tool_style(self.window.settings, tool)

    def format_profile(self):
        if self.editor is not None:
            return "text"
        if self.selected_annot is not None:
            return ANNOTATION_PROFILES.get(self.selected_annot["type"])
        if self.selected_image is not None:
            return "object"
        if self.selected_run is not None or self.mode in ("text", "replace"):
            return "text"
        if self.mode in ("highlight", "underline", "strikeout"):
            return "markup"
        if self.mode in ("rectangle", "ellipse"):
            return "shape"
        if self.mode == "ink" or self.mode in LINE_MODES:
            return "ink"
        if self.mode == "note" or self.mode == "freetext":
            return "note"
        if self.mode == "field":
            return "field"
        if self.mode == "select" and self.selected_rects:
            return "selection"
        return None

    def format_values(self, profile):
        if profile == "text":
            if self.editor is not None:
                font = self.editor.font_name
                return {"family": 1 if font.startswith("ti") else 2 if font.startswith("co") else 0,
                        "size": round(self.editor.size),
                        "bold": font in ("hebo", "hebi", "tibo", "tibi", "cobo", "cobi"),
                        "italic": font in ("heit", "hebi", "tiit", "tibi", "coit", "cobi"),
                        "align": self.editor.align,
                        "underline": self.editor.underline,
                        "spacing": self.editor.line_spacing,
                        "color": QColor.fromRgbF(*self.editor.color).name()}
            if self.selected_run is not None:
                font = self.selected_run.font
                return {"family": 1 if font.startswith("ti") else 2 if font.startswith("co") else 0,
                        "size": round(self.selected_run.size),
                        "bold": font in ("hebo", "hebi", "tibo", "tibi", "cobo", "cobi"),
                        "italic": font in ("heit", "hebi", "tiit", "tibi", "coit", "cobi"),
                        "align": 0,
                        "color": QColor.fromRgbF(*self.selected_run.color).name()}
            return {"color": self.tool_style("text")["color"]}
        if profile == "object":
            if self.selected_annot is not None:
                return {"kind": "stamp", "opacity": self.selected_annot.get("opacity", 1.0)}
            if self.selected_image is not None:
                return {"kind": "image", "opacity": self.window.engine.image_opacity(self.window.page, self.selected_image["index"])}
            return None
        if profile == "ink" or profile == "shape" or profile == "markup" or profile == "note":
            if self.selected_annot is not None:
                info = self.selected_annot
                stroke = info.get("stroke") or (0, 0, 0)
                values = {"color": QColor.fromRgbF(*stroke).name(), "width": round(info.get("width") or 1), "opacity": info.get("opacity", 1.0), "fill": bool(info.get("fill"))}
                return values
            style = self.tool_style(self.mode)
            return {"color": style["color"], "width": style.get("width", 2), "opacity": style.get("opacity", 1.0), "fill": style.get("fill", False)}
        return None

    def sync_format_bar(self):
        profile = self.format_profile() if self.window.has_doc() and self.note_popover is None else None
        if profile is None:
            self.format_bar.hide_profile()
            return
        self.format_bar.show_profile(profile, self.format_values(profile))
        self.place_format_bar()

    def viewport_rect(self, scene_rect):
        return self.mapFromScene(scene_rect).boundingRect()

    def place_format_bar(self):
        if self.note_popover is not None and self.note_popover_rect is not None:
            self.note_popover.place(self.viewport_rect(self.scene_rect(self.note_popover_rect)))
        if not self.format_bar.isVisible():
            return
        anchor = None
        if self.editor is not None:
            anchor = self.viewport_rect(self.editor.sceneBoundingRect())
        elif self.selected_annot is not None:
            anchor = self.viewport_rect(self.scene_rect(self.selected_annot["rect"]))
        elif self.selected_image is not None:
            anchor = self.viewport_rect(self.scene_rect(self.selected_image["rect"]))
        elif self.selected_run is not None:
            anchor = self.viewport_rect(self.scene_rect(self.selected_run.rect))
        elif self.selected_rects:
            anchor = self.viewport_rect(self.scene_rect(self.selected_rects[0]))
        self.format_bar.place(anchor)

    def apply_shortcut(self, action, value):
        if action in ("bold", "italic"):
            getattr(self.format_bar, action).click()
        elif action == "align":
            self.format_bar.align_buttons[value].click()
        elif action == "step":
            self.format_action("step", value)

    def format_action(self, name, value=None):
        if name == "focus":
            self.focus_editor()
            return
        if name == "pick_color":
            self.window.choose_color(value)
            return
        if name == "copy":
            QApplication.clipboard().setText(self.selected_text)
            return
        if name.startswith("markup:"):
            kind = name.split(":", 1)[1]
            self.window.run(lambda: self.apply_text_markup(kind))
            return
        if name == "delete":
            self.delete_focused_object()
            return
        if name == "rotate":
            self.rotate_selected_image()
            return
        if name == "opacity" and self.selected_image is not None and self.selected_annot is None:
            self.set_selected_image_opacity(value)
            return
        if name == "replace" and self.selected_image is not None:
            image = self.selected_image
            self.window.run(lambda: self.replace_selected_image(image))
            return
        if name == "step":
            current = self.window.font_size.value()
            if value > 0:
                bigger = [size for size in TEXT_SIZES if size > current]
                target = min(bigger) if bigger else current
            else:
                smaller = [size for size in TEXT_SIZES if size < current]
                target = max(smaller) if smaller else current
            self.window.font_size.setValue(target)
            return
        if name == "color":
            remember_color(self.window.settings, value)
            if self.editor is None and self.selected_annot is None and self.selected_run is not None and self.format_profile() == "text":
                self.open_run_editor()
            if self.editor is not None:
                self.window.ink_color = QColor(value)
                set_tool_style(self.window.settings, "text", color=value)
                self.update_editor_style()
                return
            if self.selected_annot is not None:
                self.restyle_annotation(name, value)
                return
            self.set_tool_value(self.mode, color=value)
            return
        if self.selected_annot is not None:
            self.restyle_annotation(name, value)
            return
        if self.editor is None and self.selected_run is not None and name in TEXT_FORMAT_ACTIONS:
            self.open_run_editor()
        if self.editor is not None and name in TEXT_FORMAT_ACTIONS:
            if name == "align":
                self.editor.align = value
            else:
                self.update_editor_style()
            self.focus_editor()
            return
        if name in ("fill", "width", "opacity"):
            self.set_tool_value(self.mode, **{name: value})

    def open_run_editor(self):
        """Edit the selected block so a format change applies to it; the bar keeps what the user picked."""
        desired = self.format_bar_text_values()
        run = self.selected_run
        try:
            self.begin_editor(run=run)
        except ValueError as error:
            self.window.statusBar().showMessage(str(error))
            return
        self.format_bar.set_values("text", desired)
        self.update_editor_style()
        self.editor.align = desired.get("align", 0)

    def format_bar_text_values(self):
        bar = self.format_bar
        return {"family": bar.family.currentIndex(), "size": bar.size_spin.value(), "bold": bar.bold.isChecked(),
                "italic": bar.italic.isChecked(), "underline": bar.underline.isChecked(), "spacing": bar.line_spacing(),
                "align": next((i for i, b in enumerate(bar.align_buttons) if b.isChecked()), 0)}

    def set_tool_value(self, tool, **values):
        if tool in ("text", "replace"):
            if "color" in values:
                self.window.ink_color = QColor(values["color"])
                set_tool_style(self.window.settings, "text", color=values["color"])
                self.sync_format_bar()
            return
        if tool not in ("highlight", "underline", "strikeout", "rectangle", "ellipse", "ink", "note", "line", "arrow", "freetext"):
            return
        set_tool_style(self.window.settings, tool, **values)
        self.sync_format_bar()

    def restyle_annotation(self, name, value):
        info = self.selected_annot
        xref, page = info["xref"], self.window.page
        engine = self.window.engine
        if name == "delete":
            self.delete_focused_object()
            return
        if name == "color":
            rgb = rgb_of(value)
            if info["type"] in ("Square", "Circle") and info.get("fill"):
                self.change_annotation(lambda: engine.set_annotation_style(page, xref, color=rgb, fill=rgb, coalesce=f"color:{xref}"), xref)
            else:
                self.change_annotation(lambda: engine.set_annotation_style(page, xref, color=rgb, coalesce=f"color:{xref}"), xref)
        elif name == "width" and info["type"] in ("Square", "Circle", "Ink", "Line"):
            self.change_annotation(lambda: engine.set_annotation_style(page, xref, width=value, coalesce=f"width:{xref}"), xref)
        elif name == "opacity":
            self.change_annotation(lambda: engine.set_annotation_style(page, xref, opacity=value, coalesce=f"opacity:{xref}"), xref)
        elif name == "fill" and value and info["type"] in ("Square", "Circle"):
            rgb = tuple(info.get("stroke") or (0, 0, 0))
            self.change_annotation(lambda: engine.set_annotation_style(page, xref, fill=rgb), xref)

    def change_annotation(self, function, xref):
        self.window.run(lambda: self.window.change(function))
        self.reselect_annotation(xref)

    def reselect_annotation(self, xref):
        for info in self.window.engine.annotations(self.window.page):
            if info["xref"] == xref:
                self.select_annotation(info)
                return
        self.clear_object_selection()
        self.sync_format_bar()

    def delete_focused_object(self):
        if self.editor is not None:
            self.cancel_editor()
            return
        if self.selected_annot is not None:
            xref = self.selected_annot["xref"]
            self.clear_object_selection()
            self.window.run(lambda: self.window.change(lambda: self.window.engine.delete_annotation(self.window.page, xref)))
            return
        if self.selected_image is not None:
            self.delete_selected_image()
            return
        if self.selected_run is not None:
            rect = fitz.Rect(self.selected_run.rect)
            self.window.run(lambda: self.window.change(lambda: self.window.engine.remove_text(self.window.page, rect)))

    def annotation_at(self, point):
        for info in reversed(self.window.engine.annotations(self.window.page)):
            if (info["rect"] + (-2, -2, 2, 2)).contains(point):
                return info
        return None

    def annotation_corner_at(self, point):
        info = self.selected_annot
        if info and info["type"] in RESIZABLE_ANNOTATIONS:
            rect = info["rect"]
            for name in ("tl", "tr", "bl", "br"):
                if abs(point - getattr(rect, name)) * self.scale_factor <= 9:
                    return name
        return None

    def update_annotation_handles(self, rect):
        for item in self.image_handles:
            if item.scene() is self.scene():
                self.scene().removeItem(item)
        self.image_handles = []
        if self.selected_annot and self.selected_annot["type"] in RESIZABLE_ANNOTATIONS:
            for corner in (rect.tl, rect.tr, rect.bl, rect.br):
                p = self.scene_point(corner)
                item = self.scene().addRect(QRectF(p.x() - 4, p.y() - 4, 8, 8), QPen(QColor("#087f70")), QColor("white"))
                item.setZValue(9)
                self.image_handles.append(item)

    def select_annotation(self, info):
        self.clear_object_selection()
        self.selected_annot = info
        self.object_outline = self.scene().addRect(self.scene_rect(info["rect"]), QPen(QColor("#087f70"), 1.5))
        self.object_outline.setZValue(8)
        self.update_annotation_handles(info["rect"])
        self.window.statusBar().showMessage(_("Arrastra para mover · Esquinas para redimensionar · Supr elimina · Elige color, grosor u opacidad en la barra"))
        self.sync_format_bar()

    def annotation_target(self, info, corner, point):
        original = info["rect"]
        if corner:
            opposite = {"tl": "br", "tr": "bl", "bl": "tr", "br": "tl"}[corner]
            anchor = getattr(original, opposite)
            return fitz.Rect(min(anchor.x, point.x), min(anchor.y, point.y), max(anchor.x, point.x), max(anchor.y, point.y))
        delta = point - self.pdf_point(self.origin)
        return original + (delta.x, delta.y, delta.x, delta.y)

    def open_note_popover(self, xref, rect):
        if self.note_popover is not None:
            self.note_popover.finish()
        self.note_popover_rect = fitz.Rect(rect)
        self.note_popover = NotePopover(self, xref, self.viewport_rect(self.scene_rect(rect)))
        self.format_bar.hide_profile()

    def close_note_popover(self):
        if self.note_popover is not None:
            self.note_popover.finish()
        self.note_popover_rect = None

    def clear_text_selection(self):
        for item in self.selection_items:
            if item.scene() is self.scene():
                self.scene().removeItem(item)
        self.selection_items = []
        self.selected_rects = []
        self.selected_text = ""

    def char_boundary(self, point, chars=None):
        chars = self.chars if chars is None else chars
        candidates = [(index, rect) for index, (_, rect, _) in enumerate(chars) if rect is not None]
        if not candidates:
            return 0
        def distance(entry):
            r = entry[1]
            dx = max(r.x0 - point.x, 0, point.x - r.x1)
            dy = max(r.y0 - point.y, 0, point.y - r.y1)
            return dy * dy * 4 + dx * dx
        index, rect = min(candidates, key=distance)
        return index + int(point.x > (rect.x0 + rect.x1) / 2)

    def boundary_at(self, scene_point, across=True):
        """Character boundary under a scene point and the page it belongs to. With across, pages other than the current one count."""
        page = self.nearest_page(scene_point) if across else self.window.page
        point = self.pdf_point(scene_point, page)
        return self.char_boundary(point, self.page_chars(page)), page

    def update_text_selection(self, end, end_page=None):
        self.selection_end = end
        self.clear_text_selection()
        if self.selection_anchor is None:
            return
        anchor_page = self.window.page if self.selection_page is None else self.selection_page
        end_page = anchor_page if end_page is None else end_page
        self.selection_end_page = end_page
        first, last = sorted(((anchor_page, self.selection_anchor), (end_page, end)))
        pieces = []
        for page in range(first[0], last[0] + 1):
            chars = self.page_chars(page)
            lo = first[1] if page == first[0] else 0
            hi = last[1] if page == last[0] else len(chars)
            pieces.append((page, chars[lo:hi]))
        self.selected_text = "".join(c[0] for _page, selected in pieces for c in selected)
        single = first[0] == last[0] == self.window.page
        for page, selected in pieces:
            lines = {}
            for _page, rect, number in selected:
                if rect is not None:
                    if number in lines:
                        lines[number] |= rect
                    else:
                        lines[number] = fitz.Rect(rect)
            for rect in lines.values():
                item = self.scene().addRect(self.scene_rect(rect, page), QPen(Qt.PenStyle.NoPen), QColor(55, 135, 235, 90))
                item.setZValue(5)
                self.selection_items.append(item)
                if single:
                    self.selected_rects.append(rect)
        self.window.statusBar().showMessage(_("{n} caracteres seleccionados · Ctrl+C para copiar", n=len(self.selected_text)))

    def select_word(self, point):
        index = min(self.char_boundary(point), max(0, len(self.chars) - 1))
        if index and (index == len(self.chars) or self.chars[index][0].isspace()):
            index -= 1
        lo = hi = index
        while lo > 0 and not self.chars[lo - 1][0].isspace():
            lo -= 1
        while hi < len(self.chars) and not self.chars[hi][0].isspace():
            hi += 1
        self.selection_anchor = lo
        self.selection_page = None
        self.update_text_selection(hi)

    def select_run(self, run):
        self.clear_object_selection()
        self.selected_run = run
        if self.object_outline is not None:
            self.scene().removeItem(self.object_outline)
        self.object_outline = self.scene().addRect(self.scene_rect(run.rect), QPen(QColor("#087f70"), 1.5))
        self.object_outline.setZValue(8)
        self.window.statusBar().showMessage(_("Arrastra para mover · Doble clic o F2 para editar · Supr para eliminar"))
        self.sync_format_bar()

    def begin_editor(self, point=None, run=None, rect=None):
        if self.editor and not self.commit_editor():
            return
        page = self.window.engine.doc[self.window.page]
        bounds = page.rect * page.derotation_matrix
        if run and run.direction != (1.0, 0.0):
            raise ValueError(_("Este bloque tiene texto inclinado. Su edición directa todavía no está disponible."))
        if run:
            box = fitz.Rect(run.rect.x0, run.rect.y0, bounds.x1 - 12, bounds.y1 - 5)
            text, size, font, color = run.text, run.size, run.font, run.color
        else:
            point = point or fitz.Point(rect.x0, rect.y0)
            box = fitz.Rect(point.x, point.y, min(bounds.x1 - 5, point.x + 380), bounds.y1 - 5)
            if rect is not None and rect.width > 10:
                box.x1 = min(bounds.x1 - 5, rect.x1)
            text, size, color = "", self.window.font_size.value(), rgb_of(self.tool_style("text")["color"])
            font = self.window.current_font() if hasattr(self.window, "current_font") else "helv"
        if box.width < 10 or box.height < size * 1.5:
            raise ValueError(_("Haz clic un poco más lejos del borde de la página."))
        self.clear_text_selection()
        self.editor = InlineText(self, box, text, size, font, color, run)
        self.editor.underline = self.format_bar.underline.isChecked()
        self.editor.line_spacing = self.format_bar.line_spacing()
        self.editor.apply_layout()
        self.scene().addItem(self.editor)
        self.editor.setFocus(Qt.FocusReason.MouseFocusReason)
        cursor = self.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.editor.setTextCursor(cursor)
        self.window.update_history_actions()
        self.window.ink_color = QColor.fromRgbF(*color)
        self.sync_format_bar()
        self.window.statusBar().showMessage(_("Escribe directamente · Ctrl+Enter para aplicar · Esc para cancelar · Clic fuera para aplicar"))

    def commit_editor(self):
        editor = self.editor
        if editor is None:
            return True
        text = editor.toPlainText()
        original = editor.original
        field = getattr(editor, "field", None)
        if not text and original is None and field is None:
            self.cancel_editor()
            return True
        if original and text == original.text and editor.size == original.size and editor.color == original.color and editor.font_name == original.font and editor.align == 0 and not editor.underline and editor.line_spacing == 1.0:
            self.cancel_editor()
            return True
        rect = fitz.Rect(editor.pdf_rect)
        rect.y1 = min(rect.y1, rect.y0 + editor.document().size().height() + editor.size * 1.5)
        try:
            if field is not None:
                self.window.engine.fill_form(field[0], field[1], text)
            elif original:
                self.window.engine.replace_text(self.window.page, original.rect, text, editor.size, editor.color, target_rect=rect, fontname=editor.font_name, align=editor.align,
                                                underline=editor.underline, line_spacing=editor.line_spacing)
            else:
                self.window.engine.add_text(self.window.page, rect, text, editor.size, editor.color, fontname=editor.font_name, align=editor.align,
                                            underline=editor.underline, line_spacing=editor.line_spacing)
        except Exception as error:
            QMessageBox.warning(self.window, _("El texto no se ha aplicado"), str(error))
            editor.setFocus()
            return False
        self.editor = None
        self.window.search_results = []
        self.window.refresh()
        self.window.set_mode("select" if field is not None else "edit")
        # Select the resulting object so it can be moved immediately.
        matching = [r for r in self.runs if abs(r.rect.x0 - rect.x0) < 3 and abs(r.rect.y0 - rect.y0) < editor.size * 2]
        if matching:
            self.select_run(matching[0])
        return True

    def field_elsewhere(self, scene_point):
        """Fills a form field on a visible page other than the current one, without making that page current. False when there is nothing to do here."""
        window = self.window
        index = next((i for i, rect in self.visible_geometry().items() if rect.contains(scene_point)), None)
        if index is None or index == window.page:
            return False
        point = self.pdf_point(scene_point, index)
        for widget in window.engine.doc[index].widgets() or ():
            if not widget.rect.contains(point):
                continue
            if widget.field_flags & 1:
                window.statusBar().showMessage(_("Este campo es de solo lectura"))
            elif widget.field_type == fitz.PDF_WIDGET_TYPE_CHECKBOX:
                checked = widget.field_value not in (None, "", "Off")
                window.run(lambda: window.change(lambda: window.engine.fill_form(index, widget.xref, not checked)))
            elif widget.field_type == fitz.PDF_WIDGET_TYPE_TEXT:
                self.begin_form_editor(widget, index)
            elif widget.field_type == fitz.PDF_WIDGET_TYPE_RADIOBUTTON:
                window.run(lambda: window.change(lambda: window.engine.select_radio(index, widget.xref)))
            else:
                return False
            return True
        return False

    def begin_form_editor(self, widget, page=None):
        if self.editor and not self.commit_editor():
            return
        rect = fitz.Rect(widget.rect)
        color = tuple(widget.text_color or (0, 0, 0))
        if len(color) != 3:
            color = (0, 0, 0)
        self.editor = InlineText(self, rect, str(widget.field_value or ""), widget.text_fontsize or 12, "helv", color, page=page)
        self.editor.field = (self.window.page if page is None else page, widget.xref)
        self.scene().addItem(self.editor)
        self.editor.setFocus()
        cursor = self.editor.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        self.editor.setTextCursor(cursor)
        self.window.statusBar().showMessage(_("Campo {name} · escribe el valor · Ctrl+Enter aplica · Esc cancela", name=widget.field_name))

    def cancel_editor(self):
        editor, self.editor = self.editor, None
        if editor is not None and editor.scene() is self.scene():
            self.scene().removeItem(editor)
        self.setFocus()
        self.window.update_history_actions()
        self.sync_format_bar()

    def update_editor_style(self):
        if self.editor:
            self.editor.size = self.window.font_size.value()
            self.editor.font_name = self.window.current_font()
            self.editor.color = self.window.color_tuple()
            self.editor.setFont(qt_font(self.editor.font_name, self.editor.size))
            self.editor.setDefaultTextColor(QColor.fromRgbF(*self.editor.color))
            self.editor.underline = self.format_bar.underline.isChecked()
            self.editor.line_spacing = self.format_bar.line_spacing()
            self.editor.apply_layout()
            self.format_bar.set_values("text", {"color": QColor.fromRgbF(*self.editor.color).name()})

    def focus_editor(self):
        if self.editor:
            self.setFocus()
            self.editor.setFocus()

    def apply_text_markup(self, kind):
        if not self.selected_rects:
            return False
        rects = [fitz.Rect(r) for r in self.selected_rects]
        style = self.tool_style(kind)
        color = rgb_of(style["color"])
        self.window.change(lambda: self.window.engine.annotate_text(self.window.page, rects, kind, color=color, opacity=style["opacity"]))
        return True

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or not self.window.has_doc():
            return super().mousePressEvent(event)
        scene_point = self.mapToScene(event.position().toPoint())
        self.pin_page = None
        if self.mode == "select" and self.editor is None and self.field_elsewhere(scene_point):
            return
        if self.lazy and self.editor is None:
            self.switch_page_under(scene_point)
        if self.mode == "fill":
            if self.note_popover is not None:
                self.note_popover.finish()
            if self.fill.press(scene_point):
                return
            return super().mousePressEvent(event)
        if self.note_popover is not None:
            self.note_popover.finish()
        if self.editor:
            if self.editor.contains(self.editor.mapFromScene(scene_point)):
                return super().mousePressEvent(event)
            if not self.commit_editor():
                return
            if self.lazy:
                self.switch_page_under(scene_point)
        # A click on another visible page (two-page view) makes that page the current one.
        for index, rect in self.companion_rects:
            if rect.contains(scene_point):
                self.window.run(lambda index=index: self.window.goto(index))
                return
        if self.mode == "hand":
            return super().mousePressEvent(event)
        if not (self.page_rect if self.page_rect is not None else self.scene().sceneRect()).contains(scene_point):
            self.clear_text_selection()
            return
        point = self.pdf_point(scene_point)
        self.setFocus()
        if self.mode == "measure":
            return self.measure.press(scene_point, point)
        if self.mode == "link":
            link = next((link for link in self.window.engine.links(self.window.page) if link["from"].contains(point)), None)
            if link:
                self.window.run(lambda: self.window.edit_link(link=link))
                return
        if self.mode in ("select", "highlight", "underline", "strikeout"):
            # AcroForm fields can be edited directly from the selection tool.
            if self.mode == "select" and hasattr(self.window, "edit_field_at") and self.window.edit_field_at(point):
                return
            self.selection_anchor = self.char_boundary(point)
            self.selection_page = self.window.page
            self.update_text_selection(self.selection_anchor)
            self.origin = scene_point
            return
        if self.mode == "text":
            self.window.run(lambda: self.begin_editor(point=point))
            return
        if self.mode in ("edit", "replace"):
            if self.mode == "edit":
                handle = self.annotation_corner_at(point)
                if handle:
                    self.annot_drag = (self.selected_annot, handle)
                    self.origin = scene_point
                    return
                annot = self.annotation_at(point)
                if annot:
                    self.select_annotation(annot)
                    if annot["type"] in MOVABLE_ANNOTATIONS:
                        self.annot_drag = (annot, None)
                        self.origin = scene_point
                    return
            corner = self.image_corner_at(point) if self.mode == "edit" else None
            if corner:
                self.drag_image = self.selected_image
                self.resize_corner = corner
                self.origin = scene_point
                return
            run = self.run_at(point)
            if run:
                if self.mode == "replace":
                    self.window.run(lambda: self.begin_editor(run=run))
                else:
                    self.select_run(run)
                    self.drag_run = run
                    self.origin = scene_point
                return
            image = self.image_at(point) if self.mode == "edit" else None
            if image:
                self.select_image(image)
                if image["editable"]:
                    self.drag_image = image
                    self.resize_corner = None
                    self.origin = scene_point
                return
            self.clear_object_selection()
            return
        self.origin = scene_point
        self.ink = [point]
        if self.mode in LINE_MODES:
            self.preview = self.scene().addLine(scene_point.x(), scene_point.y(), scene_point.x(), scene_point.y(), QPen(QColor("#087f70"), 1.5))
        else:
            self.preview = self.scene().addRect(QRectF(scene_point, scene_point), QPen(QColor("#087f70"), 1.5))

    def mouseMoveEvent(self, event):
        if self.window.isFullScreen() and event.position().y() < 48:
            self.window.show_fullscreen_bar()
        scene_point = self.mapToScene(event.position().toPoint())
        if self.mode == "fill" and self.window.has_doc():
            self.fill.move(scene_point)
            return super().mouseMoveEvent(event)
        if self.mode == "measure" and self.window.has_doc() and self.measure.points:
            return self.measure.move(self.pdf_point(scene_point))
        if self.window.has_doc() and self.origin is not None:
            point = self.pdf_point(scene_point)
            if self.annot_drag and self.object_outline is not None:
                info, corner = self.annot_drag
                self.object_outline.setRect(self.scene_rect(self.annotation_target(info, corner, point)))
                return
            if self.mode in ("select", "highlight", "underline", "strikeout"):
                if self.mode == "select":
                    self.update_text_selection(*self.boundary_at(scene_point))
                else:
                    self.update_text_selection(self.char_boundary(point))
                return
            if self.drag_image:
                self.update_image_outline(self.image_target(point))
                return
            if self.drag_run:
                delta = point - self.pdf_point(self.origin)
                moved = self.drag_run.rect + (delta.x, delta.y, delta.x, delta.y)
                if self.object_outline:
                    self.object_outline.setRect(self.scene_rect(moved))
                if self.ghost is None:
                    self.ghost = QGraphicsTextItem(self.drag_run.text)
                    self.ghost.setFont(qt_font(self.drag_run.font, self.drag_run.size))
                    self.ghost.setScale(self.scale_factor)
                    self.ghost.setRotation(self.window.engine.doc[self.window.page].rotation)
                    self.ghost.setOpacity(0.65)
                    self.ghost.setZValue(10)
                    self.scene().addItem(self.ghost)
                self.ghost.setPos(self.scene_point(moved.tl))
                return
            if self.mode == "ink":
                previous = self.ink[-1]
                self.ink.append(point)
                a, b = self.scene_point(previous), self.scene_point(point)
                style = self.tool_style("ink")
                self.scene().addLine(a.x(), a.y(), b.x(), b.y(), QPen(QColor(style["color"]), style["width"]))
            elif self.preview and self.mode in LINE_MODES:
                self.preview.setLine(self.origin.x(), self.origin.y(), scene_point.x(), scene_point.y())
            elif self.preview:
                self.preview.setRect(QRectF(self.origin, scene_point).normalized())
            return
        if self.window.has_doc() and not self.editor and self.mode in ("edit", "replace"):
            point = self.pdf_point(scene_point)
            corner = self.image_corner_at(point) if self.mode == "edit" else None
            cursor = Qt.CursorShape.SizeFDiagCursor if corner in ("tl", "br") else Qt.CursorShape.SizeBDiagCursor if corner else Qt.CursorShape.SizeAllCursor if self.run_at(point) or (self.mode == "edit" and self.image_at(point)) else Qt.CursorShape.ArrowCursor
            self.setCursor(cursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.mode == "fill":
            self.fill.release(self.mapToScene(event.position().toPoint()))
            return super().mouseReleaseEvent(event)
        if self.mode == "measure":
            scene_point = self.mapToScene(event.position().toPoint())
            return self.measure.release(scene_point, self.pdf_point(scene_point))
        if self.origin is None:
            return super().mouseReleaseEvent(event)
        start = self.origin
        end = self.mapToScene(event.position().toPoint())
        if self.drag_image:
            image = self.drag_image
            target = self.image_target(self.pdf_point(end))
            self.origin = self.drag_image = self.resize_corner = None
            if (end - start).manhattanLength() >= 5:
                if target.width < 2 or target.height < 2:
                    self.window.statusBar().showMessage(_("La imagen es demasiado pequeña"))
                else:
                    self.window.run(lambda: self.window.change(lambda: self.window.engine.transform_image(self.window.page, image["index"], target)))
                self.window.render_page()
            return
        if self.annot_drag:
            info, corner = self.annot_drag
            target = self.annotation_target(info, corner, self.pdf_point(end)) if (end - start).manhattanLength() >= 5 else None
            self.annot_drag = None
            self.origin = None
            if target is not None:
                if target.width < 2 or target.height < 2:
                    self.window.statusBar().showMessage(_("La anotación es demasiado pequeña"))
                    self.sync_format_bar()
                else:
                    engine, page = self.window.engine, self.window.page
                    self.change_annotation(lambda: engine.set_annotation_rect(page, info["xref"], target), info["xref"])
            return
        self.origin = None
        if self.mode in ("select", "highlight", "underline", "strikeout"):
            if self.mode == "select":
                self.update_text_selection(*self.boundary_at(end))
            else:
                self.update_text_selection(self.char_boundary(self.pdf_point(end)))
            if self.mode != "select" and self.selected_rects:
                self.window.run(lambda: self.apply_text_markup(self.mode))
            self.sync_format_bar()
            return
        if self.drag_run:
            run, self.drag_run = self.drag_run, None
            if (end - start).manhattanLength() >= 5:
                delta = self.pdf_point(end) - self.pdf_point(start)
                target = run.rect + (delta.x, delta.y, delta.x, delta.y)
                bounds = self.window.engine.doc[self.window.page].rect * self.window.engine.doc[self.window.page].derotation_matrix
                if not bounds.contains(target):
                    self.window.statusBar().showMessage(_("El texto debe quedar dentro de la página"))
                    self.window.render_page()
                else:
                    self.window.run(lambda: self.window.change(lambda: self.window.engine.replace_text(self.window.page, run.rect, run.text, run.size, run.color, target_rect=target, fontname=run.font)))
            else:
                if self.ghost:
                    self.scene().removeItem(self.ghost)
                    self.ghost = None
                if self.object_outline:
                    self.object_outline.setRect(self.scene_rect(run.rect))
            return
        a, b = self.pdf_point(start), self.pdf_point(end)
        rect = fitz.Rect(min(a.x, b.x), min(a.y, b.y), max(a.x, b.x), max(a.y, b.y))
        if self.preview:
            self.scene().removeItem(self.preview)
            self.preview = None
        clicked = (end - start).manhattanLength() < 6
        self.last_drag = (a, b)
        self.window.perform_selection(self.mode, rect, a, clicked, self.ink)

    def mouseDoubleClickEvent(self, event):
        if not self.window.has_doc() or self.editor:
            return super().mouseDoubleClickEvent(event)
        if self.mode == "measure":
            return self.measure.double_click()
        point = self.pdf_point(self.mapToScene(event.position().toPoint()))
        self.origin = None
        if self.mode == "select":
            self.select_word(point)
        elif self.mode in ("edit", "replace"):
            annot = self.annotation_at(point) if self.mode == "edit" else None
            if annot and annot["type"] == "Text":
                self.open_note_popover(annot["xref"], annot["rect"])
                return
            run = self.run_at(point)
            if run:
                self.window.run(lambda: self.begin_editor(run=run))
            elif self.mode == "edit":
                image = self.image_at(point)
                if image:
                    self.drag_image = None
                    self.window.run(lambda: self.replace_selected_image(image))
        else:
            super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        self.pin_page = None
        if self.editor:
            return super().keyPressEvent(event)
        if self.mode == "fill" and self.fill.key(event):
            return
        if self.mode == "measure" and self.measure.key(event):
            return
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.key() == Qt.Key.Key_C:
                QApplication.clipboard().setText(self.selected_text)
                return
            if event.key() == Qt.Key.Key_A and self.chars:
                self.selection_anchor = 0
                self.update_text_selection(len(self.chars))
                return
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.selected_annot:
            self.delete_focused_object()
            return
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.selected_image:
            self.delete_selected_image()
            return
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.selected_run:
            rect = fitz.Rect(self.selected_run.rect)
            self.window.run(lambda: self.window.change(lambda: self.window.engine.remove_text(self.window.page, rect)))
            return
        if event.key() == Qt.Key.Key_F2 and self.selected_run:
            self.window.run(lambda: self.begin_editor(run=self.selected_run))
            return
        if event.key() == Qt.Key.Key_Escape and self.window.isFullScreen():
            self.window.toggle_fullscreen()
            return
        if event.key() == Qt.Key.Key_Escape:
            self.clear_text_selection()
            self.clear_object_selection()
            self.window.render_page()
            return
        if event.key() == Qt.Key.Key_PageDown:
            self.window.goto(self.window.page + 1)
            return
        if event.key() == Qt.Key.Key_PageUp:
            self.window.goto(self.window.page - 1)
            return
        if event.key() == Qt.Key.Key_Home and self.window.has_doc():
            self.window.goto(0)
            return
        if event.key() == Qt.Key.Key_End and self.window.has_doc():
            self.window.goto(self.window.engine.page_count - 1)
            return
        if event.key() == Qt.Key.Key_Down and not self.lazy and self.at_edge(1):
            self.window.turn_page(1)
            return
        if event.key() == Qt.Key.Key_Up and not self.lazy and self.at_edge(-1):
            self.window.turn_page(-1)
            return
        if event.key() in (Qt.Key.Key_Right, Qt.Key.Key_Left) and not self.lazy and self.horizontalScrollBar().maximum() == self.horizontalScrollBar().minimum():
            self.window.turn_page(1 if event.key() == Qt.Key.Key_Right else -1)
            return
        letter = event.text().upper() if not event.modifiers() else ""
        if letter in TOOL_LETTERS and self.window.has_doc():
            self.window.set_mode(TOOL_LETTERS[letter])
            return
        super().keyPressEvent(event)

    def at_edge(self, direction):
        """True when the view is scrolled to the bottom (direction 1) or the top (direction -1)."""
        bar = self.verticalScrollBar()
        return bar.value() >= bar.maximum() if direction > 0 else bar.value() <= bar.minimum()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if self.commit_editor():
                # Zoom keeps the point under the pointer still.
                pos = event.position().toPoint()
                anchor = self.mapToScene(pos)
                before = self.scale_factor
                self.window.set_zoom(self.window.zoom.value() + (10 if event.angleDelta().y() > 0 else -10))
                if self.scale_factor != before:
                    ratio = self.scale_factor / before
                    moved = self.mapFromScene(QPointF(anchor.x() * ratio, anchor.y() * ratio))
                    self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + moved.x() - pos.x())
                    self.verticalScrollBar().setValue(self.verticalScrollBar().value() + moved.y() - pos.y())
            event.accept()
            return
        direction = -1 if event.angleDelta().y() > 0 else 1
        self.pin_page = None
        if event.angleDelta().y() and not self.lazy and self.window.has_doc() and self.at_edge(direction):
            # Scrolling past the top or bottom edge turns the page; a short pause avoids skipping several pages at once.
            now = time.monotonic()
            if now - self.last_wheel_turn >= 0.3:
                self.last_wheel_turn = now
                self.window.turn_page(direction)
            event.accept()
            return
        super().wheelEvent(event)

    def contextMenuEvent(self, event):
        if self.editor:
            return super().contextMenuEvent(event)
        if not self.window.has_doc():
            return
        menu = QMenu(self)
        copy = menu.addAction(_("Copiar texto seleccionado"), lambda: QApplication.clipboard().setText(self.selected_text))
        copy.setEnabled(bool(self.selected_text))
        def select_all():
            self.selection_anchor = 0
            self.selection_page = None
            self.update_text_selection(len(self.chars))
        menu.addAction(_("Seleccionar todo el texto"), select_all)
        run = self.run_at(self.pdf_point(self.mapToScene(event.pos())))
        if run:
            menu.addSeparator()
            menu.addAction(_("Editar este texto"), lambda: self.window.run(lambda: self.begin_editor(run=run)))
            menu.addAction(_("Mover texto"), lambda: self.window.set_mode("edit"))
            menu.addAction(_("Eliminar este texto"), lambda: self.window.run(lambda: self.window.change(lambda: self.window.engine.remove_text(self.window.page, run.rect))))
        point = self.pdf_point(self.mapToScene(event.pos()))
        image = self.image_at(point)
        if image:
            menu.addSeparator()
            menu.addAction(_("Seleccionar imagen"), lambda: (self.window.set_mode("edit"), self.select_image(image)))
            replace = menu.addAction(_("Sustituir esta imagen…"), lambda: self.window.run(lambda: self.replace_selected_image(image)))
            remove = menu.addAction(_("Eliminar esta imagen"), lambda: self.window.run(lambda: self.window.change(lambda: self.window.engine.delete_image(self.window.page, image["index"]))))
            replace.setEnabled(image["editable"])
            remove.setEnabled(image["editable"])
        link = next((link for link in self.window.engine.links(self.window.page) if link["from"].contains(point)), None)
        if link:
            menu.addSeparator()
            menu.addAction(_("Abrir destino del enlace"), lambda: self.window.run(lambda: self.window.open_link(link)))
            menu.addAction(_("Editar enlace…"), lambda: self.window.run(lambda: self.window.edit_link(link=link)))
            menu.addAction(_("Eliminar enlace"), lambda: self.window.run(lambda: self.window.change(lambda: self.window.engine.delete_link(self.window.page, link["xref"]))))
        menu.exec(event.globalPos())
