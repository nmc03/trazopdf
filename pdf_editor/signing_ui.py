"""Fill and sign directly on the page: form fields, quick marks, dates and saved signatures."""
from __future__ import annotations

import datetime
import uuid
from pathlib import Path

import pymupdf as fitz
from PySide6.QtCore import QPointF, QRect, QRectF, QSize, QStandardPaths, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetrics, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFrame, QGraphicsPixmapItem,
    QGraphicsRectItem, QGraphicsScene, QGraphicsView, QHBoxLayout, QSpinBox, QLabel, QLineEdit, QPushButton, QTabWidget, QToolButton,
    QVBoxLayout, QWidget,
)

from . import toast
from .lang import _, N_
from .theme import current_tokens

FIELD_KINDS = {"Text": "text", "CheckBox": "check", "RadioButton": "radio", "ComboBox": "choice", "ListBox": "choice"}
SIGNATURE_WIDTH = 180.0
HANDWRITING_FONTS = ("Segoe Script", "Lucida Handwriting", "Brush Script MT", "Ink Free", "Segoe Print", "Comic Sans MS")
TOOL_LABELS = (("text", N_("Texto"), N_("Escribe texto libre sobre la página")), ("check", "✓", N_("Marca de verificación")),
               ("cross", "✗", N_("Marca de cancelación")), ("date", N_("Fecha"), N_("Fecha de hoy (dd/mm/aaaa)")),
               ("signature", N_("Firma"), N_("Elegir o crear una firma")))


# Signature storage -----------------------------------------------------------

def signature_root():
    """Folder with the saved signatures. Lives outside any PDF until a signature is placed."""
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    return Path(base) / "signatures"


def list_signatures():
    root = signature_root()
    if not root.is_dir():
        return []
    return sorted(root.glob("*.png"), key=lambda path: path.stat().st_mtime)


def save_signature(image):
    if image is None or image.isNull():
        raise ValueError(_("La firma está vacía."))
    root = signature_root()
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{uuid.uuid4().hex}.png"
    if not image.save(str(path), "PNG"):
        raise ValueError(_("No se pudo guardar la firma."))
    return path


def delete_signature(path):
    path = Path(path).resolve()
    root = signature_root().resolve()
    if root not in path.parents:
        raise ValueError(_("Esa firma no está en la carpeta de firmas."))
    path.unlink(missing_ok=True)


# Image helpers ---------------------------------------------------------------

def handwriting_families(available):
    """Up to four handwriting-style families that the system offers, in preference order."""
    found = [name for name in HANDWRITING_FONTS if name in set(available)]
    return found[:4]


def crop_to_alpha(image):
    """Crop a transparent image to its visible pixels; None when nothing is visible."""
    width, height = image.width(), image.height()
    left, top, right, bottom = width, height, -1, -1
    for y in range(height):
        for x in range(width):
            if image.pixelColor(x, y).alpha() > 0:
                left, top, right, bottom = min(left, x), min(top, y), max(right, x), max(bottom, y)
    if right < 0:
        return None
    return image.copy(QRect(left, top, right - left + 1, bottom - top + 1))


def remove_white_background(image):
    """Turn near-white pixels transparent so a scanned signature can sit on the page."""
    picture = image.convertToFormat(QImage.Format.Format_ARGB32)
    for y in range(picture.height()):
        for x in range(picture.width()):
            color = picture.pixelColor(x, y)
            lowest = min(color.red(), color.green(), color.blue())
            if lowest >= 235:
                alpha = 0
            elif lowest >= 180:
                alpha = round(255 * (235 - lowest) / 55)
            else:
                alpha = 255
            color.setAlpha(alpha)
            picture.setPixelColor(x, y, color)
    return crop_to_alpha(picture)


def scaled_for_preview(image, width=160, height=64):
    return QPixmap.fromImage(image).scaled(width, height, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)


# Drawn and typed signatures --------------------------------------------------

class DrawPad(QWidget):
    """Freehand strokes with undo. Exported as a transparent PNG cropped to the ink."""

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(170)
        self.strokes = []
        self.current = None
        self.ink = QColor("#000000")

    def set_ink(self, color):
        self.ink = QColor(color)
        self.update()

    def undo(self):
        if self.strokes:
            self.strokes.pop()
            self.update()

    def clear(self):
        self.strokes = []
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#ffffff"))
        painter.setPen(QPen(QColor("#9aa3ad"), 1, Qt.PenStyle.DashLine))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        if not self.strokes:
            painter.setPen(QColor("#7b8590"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, _("Dibuja tu firma aquí"))
        painter.setPen(QPen(self.ink, 2.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        for stroke in self.strokes:
            painter.drawPath(smooth_path(stroke))
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.current = [QPointF(event.position())]
            self.strokes.append(self.current)

    def mouseMoveEvent(self, event):
        if self.current is not None:
            self.current.append(QPointF(event.position()))
            self.update()

    def mouseReleaseEvent(self, event):
        self.current = None

    def image(self, scale=2):
        points = [p for stroke in self.strokes for p in stroke]
        if not points:
            return None
        left = min(p.x() for p in points) - 10
        top = min(p.y() for p in points) - 10
        width = max(p.x() for p in points) + 10 - left
        height = max(p.y() for p in points) + 10 - top
        picture = QImage(max(1, round(width * scale)), max(1, round(height * scale)), QImage.Format.Format_ARGB32)
        picture.fill(QColor(0, 0, 0, 0))
        painter = QPainter(picture)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(scale, scale)
        painter.translate(-left, -top)
        painter.setPen(QPen(self.ink, 2.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        for stroke in self.strokes:
            painter.drawPath(smooth_path(stroke))
        painter.end()
        return picture


def smooth_path(points):
    path = QPainterPath()
    if not points:
        return path
    path.moveTo(points[0])
    for previous, current in zip(points, points[1:]):
        middle = QPointF((previous.x() + current.x()) / 2, (previous.y() + current.y()) / 2)
        path.quadTo(previous, middle)
    path.lineTo(points[-1])
    return path


class DrawTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.color = QComboBox()
        self.color.addItem(_("Negro"), "#000000")
        self.color.addItem(_("Azul"), "#1f3fbf")
        self.color.currentIndexChanged.connect(lambda _index: self.pad.set_ink(self.color.currentData()))
        undo = QPushButton(_("Deshacer"))
        undo.clicked.connect(lambda: self.pad.undo())
        clear = QPushButton(_("Borrar"))
        clear.clicked.connect(lambda: self.pad.clear())
        row.addWidget(QLabel(_("Color")))
        row.addWidget(self.color)
        row.addStretch(1)
        row.addWidget(undo)
        row.addWidget(clear)
        self.pad = DrawPad()
        layout.addLayout(row)
        layout.addWidget(self.pad, 1)

    def image(self):
        return self.pad.image()


class TypeTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        self.name = QLineEdit()
        self.name.setPlaceholderText(_("Escribe tu nombre"))
        self.font = QComboBox()
        families = handwriting_families(QFontDatabase.families())
        self.font.addItems(families or [_("Cursiva del sistema")])
        self.preview = QLabel()
        self.preview.setMinimumHeight(110)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name.textChanged.connect(self.refresh)
        self.font.currentIndexChanged.connect(lambda _index: self.refresh())
        layout.addWidget(self.name)
        layout.addWidget(self.font)
        layout.addWidget(self.preview, 1)
        self.refresh()

    def font_for_text(self):
        families = handwriting_families(QFontDatabase.families())
        font = QFont(self.font.currentText() if families else "Segoe UI", 40)
        font.setItalic(not families)
        return font

    def image(self):
        text = self.name.text().strip()
        if not text:
            return None
        font = self.font_for_text()
        metrics = QFontMetrics(font)
        box = metrics.tightBoundingRect(text)
        margin = 8
        picture = QImage(box.width() + 2 * margin, box.height() + 2 * margin, QImage.Format.Format_ARGB32)
        picture.fill(QColor(0, 0, 0, 0))
        painter = QPainter(picture)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setFont(font)
        painter.setPen(QColor("#000000"))
        painter.drawText(QPointF(margin - box.x(), margin - box.y()), text)
        painter.end()
        return picture

    def refresh(self):
        picture = self.image()
        self.preview.setPixmap(scaled_for_preview(picture, 320, 96) if picture is not None else QPixmap())


class ImageTab(QWidget):
    def __init__(self):
        super().__init__()
        self.source = None
        layout = QVBoxLayout(self)
        self.choose = QPushButton(_("Elegir imagen…"))
        self.choose.clicked.connect(self.pick)
        self.white = QCheckBox(_("Quitar el fondo blanco"))
        self.white.setChecked(True)
        self.preview = QLabel(_("Elige una foto o un escaneo de tu firma, de preferencia sobre papel blanco."))
        self.preview.setWordWrap(True)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(110)
        layout.addWidget(self.choose)
        layout.addWidget(self.white)
        layout.addWidget(self.preview, 1)

    def pick(self):
        path, _filter = QFileDialog.getOpenFileName(self, _("Elegir imagen de firma"), "", _("Imágenes (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)"))
        if path:
            self.load(path)

    def load(self, path):
        picture = QImage(path)
        if picture.isNull():
            self.source = None
            self.preview.setText(_("No se pudo leer esa imagen."))
            return
        if max(picture.width(), picture.height()) > 600:
            picture = picture.scaled(600, 600, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.source = picture
        self.preview.setPixmap(scaled_for_preview(picture, 320, 110))

    def image(self):
        if self.source is None:
            return None
        return remove_white_background(self.source) if self.white.isChecked() else self.source


class SignatureDialog(QDialog):
    """Create a signature with three tabs: draw, type or import an image."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Crear firma"))
        self.saved_path = None
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.draw_tab = DrawTab()
        self.type_tab = TypeTab()
        self.image_tab = ImageTab()
        self.tabs.addTab(self.draw_tab, _("Dibujar"))
        self.tabs.addTab(self.type_tab, _("Escribir"))
        self.tabs.addTab(self.image_tab, _("Imagen"))
        self.message = QLabel()
        self.message.setObjectName("DialogNote")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(_("Guardar"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(_("Cancelar"))
        buttons.accepted.connect(self.accept_signature)
        buttons.rejected.connect(self.reject)
        layout.addWidget(self.tabs)
        layout.addWidget(self.message)
        layout.addWidget(buttons)
        self.resize(520, 380)

    def current_image(self):
        tab = self.tabs.currentWidget()
        return tab.image() if hasattr(tab, "image") else None

    def accept_signature(self):
        image = self.current_image()
        if image is None or image.isNull():
            self.message.setText(_("Dibuja, escribe o elige una imagen antes de guardar."))
            return
        self.saved_path = save_signature(image)
        self.accept()


class SignatureRow(QFrame):
    def __init__(self, path, choose, remove):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        pick = QToolButton()
        pick.setIcon(QIcon(scaled_for_preview(QImage(str(path)), 120, 44)))
        pick.setIconSize(QSize(120, 44))
        pick.setToolTip(_("Usar esta firma"))
        pick.setAccessibleName(_("Usar esta firma"))
        pick.clicked.connect(lambda: choose(path))
        delete = QToolButton()
        delete.setText("×")
        delete.setToolTip(_("Borrar firma"))
        delete.setAccessibleName(_("Borrar firma"))
        delete.clicked.connect(lambda: remove(path))
        layout.addWidget(pick, 1)
        layout.addWidget(delete)


class SignatureSelector(QFrame):
    """Popover anchored to the Firma button: saved signatures, create, remember."""

    def __init__(self, fill, anchor):
        super().__init__(None, Qt.WindowType.Popup)
        self.fill = fill
        self.setObjectName("Pill")
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(10, 10, 10, 10)
        self.layout_.addWidget(QLabel(_("Firmas guardadas")))
        self.rows = QVBoxLayout()
        self.layout_.addLayout(self.rows)
        create = QPushButton(_("+ Crear firma"))
        create.clicked.connect(self.create)
        self.layout_.addWidget(create)
        self.remember = QCheckBox(_("Recordar firma"))
        self.remember.setChecked(fill.remember_enabled())
        self.remember.toggled.connect(fill.set_remember)
        self.layout_.addWidget(self.remember)
        self.refresh()
        self.move(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def refresh(self):
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        paths = list_signatures()
        if not paths:
            self.rows.addWidget(QLabel(_("Todavía no hay firmas guardadas.")))
        for path in paths:
            self.rows.addWidget(SignatureRow(path, self.choose, self.remove))
        self.adjustSize()

    def choose(self, path):
        self.close()
        self.fill.set_signature(path)

    def remove(self, path):
        try:
            delete_signature(path)
        except ValueError as error:
            toast.notify(self.fill.window, str(error), kind="error")
        self.refresh()

    def create(self):
        self.close()
        dialog = SignatureDialog(self.fill.window)
        if dialog.exec() and dialog.saved_path is not None:
            self.fill.set_signature(dialog.saved_path)


class ChoicePopup(QComboBox):
    """Drop-down anchored on a list or combo field; it removes itself once the popup closes."""

    def hidePopup(self):
        super().hidePopup()
        QTimer.singleShot(0, self.deleteLater)


def open_choice(view, page, xref, rect, choices, value):
    """Open a drop-down over a form field of the page, applying the chosen value."""
    combo = ChoicePopup(view.viewport())
    combo.addItems([str(choice) for choice in choices])
    combo.setCurrentText(str(value or ""))
    top_left = view.mapFromScene(view.scene_rect(rect).topLeft())
    bottom_right = view.mapFromScene(view.scene_rect(rect).bottomRight())
    combo.setGeometry(QRect(top_left, bottom_right).normalized())
    combo.setMinimumHeight(24)

    def apply(index):
        window = view.window
        value_chosen = combo.itemText(index)
        window.run(lambda: window.change(lambda: window.engine.fill_form(page, xref, value_chosen)))

    combo.activated.connect(apply)
    combo.show()
    combo.showPopup()
    return combo


class FillPalette(QFrame):
    """Quick marks shown over a PDF without form fields."""

    def __init__(self, fill):
        super().__init__(fill.view.viewport())
        self.fill = fill
        self.setObjectName("Pill")
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 4, 6, 4)
        self.buttons = {}
        for key, label, tip in TOOL_LABELS:
            button = QToolButton()
            button.setText(_(label))
            button.setCheckable(True)
            button.setToolTip(_(tip))
            button.setAccessibleName(_(tip))
            button.clicked.connect(lambda _checked=False, k=key: fill.choose_tool(k))
            self.buttons[key] = button
            row.addWidget(button)
    def mark(self, key):
        for name, button in self.buttons.items():
            button.setChecked(name == key)

    def place(self):
        # Bottom center, so the banner that floats at the top never covers it.
        self.adjustSize()
        host = self.parentWidget()
        self.move(max(8, (host.width() - self.width()) // 2), max(8, host.height() - self.height() - 16))


def use_canvas_banner(window):
    """Kept for ui_dialogs, which still calls it. Banners already float over the page through toast.banner_for."""
    toast.banner_for(window)


class FillMode:
    """Controller for the "Rellenar y firmar" mode of the page view."""

    def __init__(self, view):
        self.view = view
        self.tool = None
        self.signature = None
        self.focus = None
        self.drag_start = None
        self.items = []
        self.ghost = None
        self.rubber = None
        self.banner = None
        self.palette = None
        self.selector = None

    @property
    def window(self):
        return self.view.window

    # State --------------------------------------------------------------

    def remember_enabled(self):
        return self.window.settings.value("signing/remember", False, type=bool)

    def set_remember(self, enabled):
        self.window.settings.setValue("signing/remember", bool(enabled))
        if not enabled:
            self.window.settings.remove("signing/remembered")

    def fields(self):
        if not self.window.has_doc():
            return []
        found = [f for f in self.window.engine.forms() if f["page"] == self.window.page and str(f.get("type")) in FIELD_KINDS]
        return sorted(found, key=lambda f: (round(f["rect"][1]), f["rect"][0]))

    def set_active(self, on):
        self.close_choice()
        self.drag_start = None
        self._remove_items()
        if not on:
            self.tool = None
            self.signature = None
            self.focus = None
            self._hide_palette()
            if self.banner is not None:
                self.banner.dismiss()
                self.banner = None
            return
        fields = self.fields()
        self.focus = None
        remembered = self.window.settings.value("signing/remembered", "", type=str)
        if self.remember_enabled() and remembered and Path(remembered).is_file():
            self.signature, self.tool = remembered, "signature"
        else:
            self.signature, self.tool = None, None
        self._show_palette(not fields)
        self.draw()
        if fields:
            self.banner = toast.notify(self.window, _("Este formulario tiene {n} campos · Tab pasa al siguiente · Intro confirma", n=len(fields)), timeout=0,
                                       actions=[(_("Lista de campos"), self.window.forms_dialog)])
        else:
            self.banner = toast.notify(self.window, _("Este PDF no tiene campos. Usa la paleta para escribir, marcar, fechar o firmar sobre la página."))

    def _remove_items(self):
        for item in self.items + [self.ghost, self.rubber]:
            if item is None:
                continue
            try:
                if item.scene() is not None:
                    item.scene().removeItem(item)
            except RuntimeError:
                pass
        self.items = []
        self.ghost = None
        self.rubber = None

    def draw(self):
        self._remove_items()
        if self.view.mode != "fill" or not self.window.has_doc():
            return
        scene = self.view.scene()
        tokens = current_tokens()
        for field in self.fields():
            rect = self.view.scene_rect(fitz.Rect(field["rect"]))
            focused = field["xref"] == self.focus
            fill = QColor(tokens["accentsoft"])
            fill.setAlpha(220 if focused else 150)
            item = scene.addRect(rect, QPen(QColor(tokens["accent"]), 1.8 if focused else 0.9), fill)
            item.setZValue(4)
            self.items.append(item)
        if self.palette is not None and self.palette.isVisible():
            self.palette.place()

    # Palette and tools --------------------------------------------------

    def _show_palette(self, show):
        if not show:
            self._hide_palette()
            return
        if self.palette is None:
            self.palette = FillPalette(self)
        self.palette.mark(self.tool)
        self.palette.show()
        self.palette.raise_()
        self.palette.place()

    def _hide_palette(self):
        if self.palette is not None:
            self.palette.hide()

    def choose_tool(self, key):
        self.commit_editor()
        if key == "signature":
            self.open_selector()
            return
        self.tool = None if self.tool == key else key
        self.signature = None
        if self.palette is not None:
            self.palette.mark(self.tool)

    def open_selector(self):
        anchor = self.palette.buttons["signature"] if self.palette is not None else self.view
        self.selector = SignatureSelector(self, anchor)
        self.selector.show()

    def set_signature(self, path):
        self.signature = str(path)
        self.tool = "signature"
        if self.remember_enabled():
            self.window.settings.setValue("signing/remembered", self.signature)
        if self.palette is not None:
            self.palette.mark("signature")
        self.draw()

    def close_choice(self):
        for child in self.view.viewport().findChildren(ChoicePopup):
            child.deleteLater()

    # Mouse and keyboard, called from PageView ---------------------------

    def press(self, scene_point):
        """Return False when the click belongs to the inline editor, so the view can place the caret."""
        view = self.view
        self.close_choice()
        if view.editor is not None:
            if view.editor.contains(view.editor.mapFromScene(scene_point)):
                return False
            if not self.commit_editor():
                return True
        point = view.pdf_point(scene_point)
        field = self.field_at(point)
        if field is not None:
            self.focus = field["xref"]
            self.draw()
            self.activate(field)
            return True
        self.focus = None
        if self.tool == "signature" and self.signature:
            self.drag_start = scene_point
        elif self.tool == "text":
            self.begin_quick_text(point)
        elif self.tool in ("check", "cross"):
            self.place_mark(point, self.tool)
        elif self.tool == "date":
            self.place_text(point, datetime.date.today().strftime("%d/%m/%Y"), "helv", 11)
        self.draw()
        return True

    def move(self, scene_point):
        if self.tool != "signature" or not self.signature:
            return
        if self.drag_start is not None:
            if self.rubber is None:
                self.rubber = QGraphicsRectItem()
                self.rubber.setPen(QPen(QColor(current_tokens()["accent"]), 1, Qt.PenStyle.DashLine))
                self.rubber.setZValue(10)
                self.view.scene().addItem(self.rubber)
            self.rubber.setRect(QRectF(self.drag_start, scene_point).normalized())
            return
        if self.ghost is None:
            pixmap = QPixmap(self.signature).scaledToWidth(max(1, round(SIGNATURE_WIDTH * self.view.scale_factor)), Qt.TransformationMode.SmoothTransformation)
            self.ghost = QGraphicsPixmapItem(pixmap)
            self.ghost.setOpacity(0.6)
            self.ghost.setZValue(10)
            self.view.scene().addItem(self.ghost)
        size = self.ghost.pixmap().size()
        self.ghost.setPos(scene_point - QPointF(size.width() / 2, size.height() / 2))

    def release(self, scene_point):
        if self.drag_start is None:
            return
        start, self.drag_start = self.drag_start, None
        if self.rubber is not None:
            self._remove_items()
            self.draw()
        view = self.view
        if (scene_point - start).manhattanLength() < 6:
            center = view.pdf_point(scene_point)
            width = SIGNATURE_WIDTH
            height = self.signature_height(width)
            rect = fitz.Rect(center.x - width / 2, center.y - height / 2, center.x + width / 2, center.y + height / 2)
        else:
            a, b = view.pdf_point(start), view.pdf_point(scene_point)
            rect = fitz.Rect(min(a.x, b.x), min(a.y, b.y), max(a.x, b.x), max(a.y, b.y))
        self.place_signature(rect)

    def signature_height(self, width):
        picture = QImage(self.signature)
        if picture.isNull() or picture.width() == 0:
            return width / 3
        return width * picture.height() / picture.width()

    def place_signature(self, rect):
        page = self.window.engine.doc[self.window.page]
        bounds = page.rect * page.derotation_matrix
        rect = rect & bounds
        if rect.is_empty or rect.width < 4 or rect.height < 4:
            toast.notify(self.window, _("La firma debe quedar dentro de la página."), kind="error")
            return
        path = self.signature
        try:
            self.window.change(lambda: self.window.engine.add_image(self.window.page, rect, path))
        except Exception as error:
            toast.notify(self.window, _("No se pudo colocar la firma."), kind="error", details=str(error))
            return
        if not self.remember_enabled():
            self.tool = None
            self.signature = None
            if self.palette is not None:
                self.palette.mark(None)
        self.draw()

    def begin_quick_text(self, point):
        from .canvas import InlineText
        view = self.view
        page = self.window.engine.doc[self.window.page]
        bounds = page.rect * page.derotation_matrix
        box = fitz.Rect(point.x, point.y, min(bounds.x1 - 5, point.x + 260), bounds.y1 - 5)
        if box.width < 10 or box.height < 12 * 1.5:
            toast.notify(self.window, _("Haz clic un poco más lejos del borde de la página."), kind="error")
            return
        editor = InlineText(view, box, "", 12, "helv", (0, 0, 0))
        editor.field = None
        view.editor = editor
        view.scene().addItem(editor)
        editor.setFocus(Qt.FocusReason.MouseFocusReason)

    def place_text(self, point, text, fontname, size):
        page = self.window.engine.doc[self.window.page]
        bounds = page.rect * page.derotation_matrix
        rect = fitz.Rect(point.x, point.y, min(bounds.x1 - 5, point.x + size * 4), min(bounds.y1 - 5, point.y + size * 1.6))
        try:
            self.window.change(lambda: self.window.engine.add_text(self.window.page, rect, text, size, (0, 0, 0), fontname=fontname))
        except Exception as error:
            toast.notify(self.window, _("No se pudo colocar la marca."), kind="error", details=str(error))

    def place_mark(self, point, kind, side=16):
        """Vector ✓ or ✗ of side points, so it never depends on a font."""
        page = self.window.engine.doc[self.window.page]
        bounds = page.rect * page.derotation_matrix
        rect = fitz.Rect(point.x, point.y, min(bounds.x1 - 5, point.x + side), min(bounds.y1 - 5, point.y + side))
        try:
            self.window.change(lambda: self.window.engine.add_mark(self.window.page, rect, kind))
        except Exception as error:
            toast.notify(self.window, _("No se pudo colocar la marca."), kind="error", details=str(error))

    def commit_editor(self):
        """Apply the inline editor: a field value or a quick text. Keeps the fill mode."""
        view = self.view
        editor = view.editor
        if editor is None:
            return True
        text = editor.toPlainText()
        field = getattr(editor, "field", None)
        try:
            if field is not None:
                if text != getattr(editor, "original_value", None):
                    self.window.engine.fill_form(field[0], field[1], text)
            elif text:
                rect = fitz.Rect(editor.pdf_rect)
                rect.y1 = min(rect.y1, rect.y0 + editor.document().size().height() + editor.size * 1.5)
                self.window.engine.add_text(self.window.page, rect, text, editor.size, editor.color, fontname=editor.font_name)
        except Exception as error:
            toast.notify(self.window, _("El valor no se ha aplicado"), kind="error", details=str(error))
            editor.setFocus()
            return False
        view.cancel_editor()
        self.window.search_results = []
        self.window.refresh()
        return True

    def field_at(self, point):
        return next((f for f in self.fields() if fitz.Rect(f["rect"]).contains(point)), None)

    def widget(self, field):
        page = self.window.engine.doc[field["page"]]
        return page.load_widget(int(field["xref"]))

    def activate(self, field):
        kind = FIELD_KINDS[str(field["type"])]
        page, xref = field["page"], field["xref"]
        engine = self.window.engine
        try:
            if kind == "text":
                widget = self.widget(field)
                if widget is not None:
                    self.view.begin_form_editor(widget)
                    self.view.editor.original_value = str(field.get("value") or "")
            elif kind == "check":
                checked = field.get("value") not in (None, "", "Off")
                self.window.change(lambda: engine.fill_form(page, xref, not checked))
            elif kind == "radio":
                self.window.change(lambda: engine.select_radio(page, xref))
            elif kind == "choice":
                open_choice(self.view, page, xref, fitz.Rect(field["rect"]), field.get("choices") or [], field.get("value"))
        except ValueError as error:
            toast.notify(self.window, str(error), kind="error")

    def move(self, step):
        fields = self.fields()
        if not fields:
            return
        xrefs = [f["xref"] for f in fields]
        if self.focus in xrefs:
            index = (xrefs.index(self.focus) + step) % len(fields)
        else:
            index = 0 if step > 0 else len(fields) - 1
        self.focus = xrefs[index]
        self.draw()
        self.view.setFocus()
        field = fields[index]
        if FIELD_KINDS[str(field["type"])] == "text":
            self.activate(field)

    def editor_key(self, event):
        """Keys inside the inline editor of this mode. Returns True when the key was consumed."""
        key = event.key()
        if key not in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            return False
        field = getattr(self.view.editor, "field", None)
        if not self.commit_editor():
            return True
        if field is None:
            return True
        step = -1 if key == Qt.Key.Key_Backtab or event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
        self.move(step)
        return True

    def key(self, event):
        key = event.key()
        shift = event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        if key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            self.move(-1 if key == Qt.Key.Key_Backtab or shift else 1)
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            fields = {f["xref"]: f for f in self.fields()}
            if self.focus in fields:
                self.activate(fields[self.focus])
                return True
            return False
        if key == Qt.Key.Key_Escape:
            if self.tool or self.signature:
                self.tool = None
                self.signature = None
                if self.palette is not None:
                    self.palette.mark(None)
                self.draw()
            elif self.focus is not None:
                self.focus = None
                self.draw()
            return True
        return False



# Certificate signing: options and visible appearance --------------------------

class SigningOptionsDialog(QDialog):
    def __init__(self, parent=None, settings=None):
        super().__init__(parent)
        from .signing import HELP, SETTINGS_ENABLED, SETTINGS_URL
        self._keys = (SETTINGS_ENABLED, SETTINGS_URL)
        self.setWindowTitle(_("Opciones de firma"))
        self.setMinimumWidth(420)
        self.settings = settings
        layout = QVBoxLayout(self)
        self.use_timestamp = QCheckBox(_("Añadir sello de tiempo"))
        self.url = QLineEdit()
        self.url.setPlaceholderText(_("https://dirección-de-la-autoridad"))
        self.url.setAccessibleName(_("Dirección de la autoridad de sellado"))
        note = QLabel(_(HELP))
        note.setWordWrap(True)
        layout.addWidget(self.use_timestamp)
        layout.addWidget(self.url)
        layout.addWidget(note)
        if settings is not None:
            self.use_timestamp.setChecked(settings.value(SETTINGS_ENABLED, False, type=bool))
            self.url.setText(settings.value(SETTINGS_URL, "", type=str))
        self.use_timestamp.toggled.connect(self.url.setEnabled)
        self.url.setEnabled(self.use_timestamp.isChecked())
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(_("Continuar"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(_("Cancelar"))
        buttons.accepted.connect(self.accept_options)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept_options(self):
        if self.use_timestamp.isChecked() and not self.url.text().strip().lower().startswith(("http://", "https://")):
            self.url.setFocus()
            self.url.setPlaceholderText(_("Escribe una dirección que empiece por https://"))
            self.url.setStyleSheet("border: 1px solid #c0392b;")
            return
        if self.settings is not None:
            self.settings.setValue(self._keys[0], self.use_timestamp.isChecked())
            self.settings.setValue(self._keys[1], self.url.text().strip())
        self.accept()

    def timestamp_url(self):
        return self.url.text().strip() if self.use_timestamp.isChecked() else None


class PlacementView(QGraphicsView):
    """One page as a picture; drag to draw the signature rectangle. rect() is in page points (top left origin)."""
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setAccessibleName(_("Página para colocar la firma"))
        self.zoom = 1.0
        self.origin = None
        self.box = None
        self.selection = None
        self.pixmap_item = None

    def show_page(self, doc, index, max_width=520):
        page = doc[index]
        self.zoom = min(max_width / page.rect.width, 1.5)
        pix = page.get_pixmap(matrix=fitz.Matrix(self.zoom, self.zoom), alpha=False)
        image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888).copy()
        self.scene().clear()
        self.selection = None
        self.pixmap_item = self.scene().addPixmap(QPixmap.fromImage(image))
        self.scene().setSceneRect(self.pixmap_item.boundingRect())
        self.box = None
        self.changed.emit()

    def rect(self):
        if self.box is None:
            return None
        r = self.box.normalized()
        return (r.left() / self.zoom, r.top() / self.zoom, r.right() / self.zoom, r.bottom() / self.zoom)

    def set_rect(self, rect):
        z = self.zoom
        self.box = QRectF(rect[0] * z, rect[1] * z, (rect[2] - rect[0]) * z, (rect[3] - rect[1]) * z)
        self._draw()

    def _draw(self):
        if self.selection is not None:
            self.scene().removeItem(self.selection)
        self.selection = self.scene().addRect(self.box.normalized(), QPen(QColor("#087f70"), 1.5), QColor(8, 127, 112, 50))
        self.changed.emit()

    def _clamped(self, event):
        point = self.mapToScene(event.position().toPoint())
        bounds = self.scene().sceneRect()
        return QPointF(min(max(point.x(), bounds.left()), bounds.right()), min(max(point.y(), bounds.top()), bounds.bottom()))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.origin = self._clamped(event)
            self.box = QRectF(self.origin, self.origin)
            self._draw()

    def mouseMoveEvent(self, event):
        if self.origin is not None:
            self.box = QRectF(self.origin, self._clamped(event))
            self._draw()

    def mouseReleaseEvent(self, event):
        self.origin = None


class SignatureAppearanceDialog(QDialog):
    """Choose invisible or visible signature: page, rectangle, and what the stamp says."""

    def __init__(self, parent, doc, existing=0, signer_name=""):
        super().__init__(parent)
        self.doc = doc
        self.setWindowTitle(_("Apariencia de la firma"))
        layout = QVBoxLayout(self)
        if existing:
            warning = QLabel(_("Este documento ya tiene {n} firma(s). Tu firma se añadirá como una revisión nueva y las firmas anteriores seguirán siendo válidas. Si lo editas después, dejarán de serlo.", n=existing))
            warning.setWordWrap(True)
            warning.setStyleSheet("color: #8a5a00;")
            layout.addWidget(warning)
        self.visible = QCheckBox(_("Firma visible en la página"))
        self.visible.setToolTip(_("Sin marcar, la firma es invisible: solo queda constancia en el archivo."))
        layout.addWidget(self.visible)
        self.panel = QWidget()
        inner = QVBoxLayout(self.panel)
        row = QHBoxLayout()
        row.addWidget(QLabel(_("Página:")))
        self.page = QSpinBox()
        self.page.setRange(1, max(1, doc.page_count))
        self.page.setAccessibleName(_("Página de la firma"))
        row.addWidget(self.page)
        row.addStretch(1)
        inner.addLayout(row)
        hint = QLabel(_("Arrastra sobre la página para dibujar el rectángulo de la firma."))
        hint.setWordWrap(True)
        inner.addWidget(hint)
        self.view = PlacementView()
        self.view.setMinimumSize(540, 360)
        inner.addWidget(self.view, 1)
        self.name = QCheckBox(_("Nombre del firmante: {name}", name=signer_name or _("el del certificado")))
        self.name.setChecked(True)
        self.date = QCheckBox(_("Fecha y hora"))
        self.date.setChecked(True)
        self.reason = QLineEdit()
        self.reason.setPlaceholderText(_("Motivo (opcional)"))
        self.reason.setAccessibleName(_("Motivo de la firma"))
        self.location = QLineEdit()
        self.location.setPlaceholderText(_("Lugar (opcional)"))
        self.location.setAccessibleName(_("Lugar de la firma"))
        self.image = QComboBox()
        self.image.setAccessibleName(_("Imagen de firma"))
        self.image.addItem(_("Sin imagen"), None)
        for path in list_signatures():
            self.image.addItem(path.stem[:8], str(path))
        for widget in (self.name, self.date, self.reason, self.location, self.image):
            inner.addWidget(widget)
        layout.addWidget(self.panel)
        self.error = QLabel("")
        self.error.setStyleSheet("color: #c0392b;")
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(_("Continuar"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(_("Cancelar"))
        buttons.accepted.connect(self.accept_choice)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.visible.toggled.connect(self.panel.setVisible)
        self.panel.setVisible(False)
        self.page.valueChanged.connect(self.load_page)
        if doc.page_count:
            self.load_page()

    def load_page(self):
        self.view.show_page(self.doc, self.page.value() - 1)

    def accept_choice(self):
        if self.visible.isChecked():
            rect = self.view.rect()
            if rect is None or rect[2] - rect[0] < 20 or rect[3] - rect[1] < 12:
                self.error.setText(_("Dibuja sobre la página el rectángulo donde irá la firma."))
                return
        self.accept()

    def field_spec(self):
        from .signing import FieldSpec
        if not self.visible.isChecked():
            return None
        return FieldSpec(page=self.page.value() - 1, rect=self.view.rect())

    def appearance(self):
        from .signing import Appearance
        return Appearance(show_name=self.name.isChecked(), show_date=self.date.isChecked(), reason=self.reason.text().strip(),
                          location=self.location.text().strip(), image_path=self.image.currentData())
