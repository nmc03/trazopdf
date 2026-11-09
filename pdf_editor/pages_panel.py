from __future__ import annotations

from PySide6.QtCore import QEvent, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout,
                               QLabel, QListWidget, QListWidgetItem, QListView, QMessageBox, QPushButton, QSlider,
                               QToolTip, QVBoxLayout)
from pathlib import Path
import pymupdf as fitz

from . import theme
from .lang import _
from .ui_widgets import ThumbnailDelegate

COMMENTS_ROLE = Qt.ItemDataRole.UserRole + 1    # annotations on the page (int)
ROTATION_ROLE = Qt.ItemDataRole.UserRole + 2    # page rotation in degrees (int)
LABEL_ROLE = Qt.ItemDataRole.UserRole + 3       # custom page label, empty when it is the plain number


class BadgeDelegate(ThumbnailDelegate):
    """Thumbnail card plus small badges (comments, rotation, label) and a placeholder while the page renders."""

    def badges(self, index):
        """(corner, text, tooltip) per badge; pages without comments, rotation or label get none."""
        found = []
        comments = index.data(COMMENTS_ROLE) or 0
        rotation = index.data(ROTATION_ROLE) or 0
        label = index.data(LABEL_ROLE) or ""
        if comments:
            found.append(("tr", str(comments), _("{n} comentario(s) o anotación(es)", n=comments)))
        if rotation:
            found.append(("tl", f"{rotation}°", _("Girada {rotation}°", rotation=rotation)))
        if label:
            found.append(("bl", label, _("Etiqueta de página: {label}", label=label)))
        return found

    def page_rect(self, option):
        card = QRectF(option.rect).adjusted(8, 3, -8, -3)
        area = QRectF(card.left(), card.top() + 10, card.width(), card.height() - 40)
        size = getattr(self.parent(), "thumb_size", QSize(104, 145))
        return QRectF(area.center().x() - size.width() / 2, area.center().y() - size.height() / 2,
                      size.width(), size.height())

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        tokens = theme.current_tokens()
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        page = self.page_rect(option)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not (isinstance(icon, QIcon) and not icon.isNull()):
            painter.fillRect(page.adjusted(1, 1, -1, -1), QColor(tokens["surface2"]))
            painter.setPen(QColor(tokens["inkmuted"]))
            painter.drawText(page, Qt.AlignmentFlag.AlignCenter, "…")
        font = QFont(option.font)
        font.setPointSizeF(max(7.0, option.font.pointSizeF() - 2))
        font.setBold(True)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        for corner, text, _tip in self.badges(index):
            text = metrics.elidedText(text, Qt.TextElideMode.ElideRight, max(20, int(page.width() / 2)))
            box = QRectF(0, 0, max(metrics.horizontalAdvance(text) + 10, 16), 16)
            if corner == "tr":
                box.moveTopRight(page.topRight())
                box.translate(-3, 3)
            elif corner == "tl":
                box.moveTopLeft(page.topLeft())
                box.translate(3, 3)
            else:
                box.moveBottomLeft(page.bottomLeft())
                box.translate(3, -3)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(tokens["accent"]))
            painter.drawRoundedRect(box, 8, 8)
            painter.setPen(QColor(tokens["onaccent"]))
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()

    def helpEvent(self, event, view, option, index):
        tips = [tip for _corner, _text, tip in self.badges(index)]
        if tips and event.type() == QEvent.Type.ToolTip:
            QToolTip.showText(event.globalPos(), "\n".join(tips), view)
            return True
        return super().helpEvent(event, view, option, index)


def notify(window, texto, accion_etiqueta=None, accion=None):
    """Aviso no modal con una acción opcional (por ejemplo, Deshacer)."""
    from .toast import notify as show

    actions = [(accion_etiqueta, accion)] if accion_etiqueta and accion else []
    show(window, texto, actions=actions)


def moved_order(count, selected, target):
    """Page order after moving the ``selected`` pages in front of the old position ``target``."""
    chosen = sorted(set(selected))
    rest = [index for index in range(count) if index not in chosen]
    before = sum(1 for index in rest if index < target)
    return rest[:before] + chosen + rest[before:]


def page_count_of(path):
    with fitz.open(path) as document:
        return None if document.needs_pass else len(document)


class ThumbnailList(QListWidget):
    """Miniaturas de páginas: reordenar arrastrando, soltar PDFs, Supr y tamaño con Ctrl+rueda."""

    reorderRequested = Signal(list, int)   # páginas seleccionadas, posición de destino (antes de esa página)
    filesDropped = Signal(list, int)       # rutas de PDF, posición de destino
    deleteRequested = Signal()
    sizeChanged = Signal()

    MIN_WIDTH = 72
    MAX_WIDTH = 200

    def __init__(self, parent=None):
        super().__init__(parent)
        self.thumb_size = QSize(104, 145)
        self.pending_drop = None
        self.setObjectName("ThumbnailList")
        self.setAccessibleName(_("Miniaturas de páginas"))
        self.setItemDelegate(BadgeDelegate(self))
        self.preferred_width = self.thumb_size.width()
        self.settings = None
        self.slider = QSlider(Qt.Orientation.Horizontal, self)
        self.slider.setObjectName("ThumbnailSize")
        self.slider.setAccessibleName(_("Tamaño de las miniaturas"))
        self.slider.setToolTip(_("Tamaño de las miniaturas"))
        self.slider.setRange(self.MIN_WIDTH, self.MAX_WIDTH)
        self.slider.setValue(self.preferred_width)
        self.slider.valueChanged.connect(lambda value: self.set_thumb_width(value))
        self.setViewportMargins(0, 0, 0, 26)
        self.setIconSize(self.thumb_size)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setFlow(QListView.Flow.TopToBottom)
        self.setWrapping(False)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Snap)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setSpacing(2)
        self.setMouseTracking(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

    def item_size(self):
        return QSize(self.thumb_size.width() + 36, self.thumb_size.height() + 43)

    def bind_settings(self, settings):
        """Restores the saved thumbnail size and keeps saving the user's choice."""
        self.settings = settings
        try:
            saved = int(settings.value("thumbWidth", self.preferred_width))
        except (TypeError, ValueError):
            saved = self.preferred_width
        self.set_thumb_width(saved)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.slider.setGeometry(8, self.height() - 24, max(40, self.viewport().width() - 16), 20)
        fit = max(self.MIN_WIDTH, min(self.preferred_width, self.viewport().width() - 44))
        if fit != self.thumb_size.width():
            self.apply_width(fit)

    def set_thumb_width(self, width):
        """The user's choice: remembered, and shown as long as the panel is wide enough."""
        width = max(self.MIN_WIDTH, min(self.MAX_WIDTH, int(width)))
        self.preferred_width = width
        if self.settings is not None:
            self.settings.setValue("thumbWidth", width)
        if self.slider.value() != width:
            self.slider.blockSignals(True)
            self.slider.setValue(width)
            self.slider.blockSignals(False)
        self.apply_width(width)

    def apply_width(self, width):
        self.thumb_size = QSize(width, round(width * 145 / 104))
        self.setIconSize(self.thumb_size)
        for row in range(self.count()):
            item = self.item(row)
            item.setSizeHint(self.item_size())
            item.setIcon(QIcon())
        self.sizeChanged.emit()

    def drop_row(self, point):
        """Index before which a drop lands; a single column, so only the height matters."""
        for row in range(self.count()):
            if point.y() < self.visualItemRect(self.item(row)).center().y():
                return row
        return self.count()

    def wheelEvent(self, event):
        step = event.angleDelta().y()
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier and step:
            self.set_thumb_width(self.thumb_size.width() + (8 if step > 0 else -8))
            event.accept()
            return
        super().wheelEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Delete:
            self.deleteRequested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def dragEnterEvent(self, event):
        if event.source() is self or event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.pending_drop = self.drop_row(event.position().toPoint())
        self.viewport().update()
        event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self.pending_drop = None
        self.viewport().update()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        target = self.drop_row(event.position().toPoint())
        self.pending_drop = None
        self.viewport().update()
        if event.source() is self:
            selected = [self.row(item) for item in self.selectedItems()]
            # Copy action: the list must not remove its own items after the drag; the window redraws them.
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            QTimer.singleShot(0, lambda: self.reorderRequested.emit(selected, target))
            return
        paths = [url.toLocalFile() for url in event.mimeData().urls()
                 if url.isLocalFile() and url.toLocalFile().lower().endswith(".pdf")]
        if not paths:
            event.ignore()
            return
        event.acceptProposedAction()
        QTimer.singleShot(0, lambda: self.filesDropped.emit(paths, target))


class MergeDialog(QDialog):
    """Combinar archivos: lista reordenable de PDF y posición de inserción."""

    def __init__(self, current, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Combinar archivos"))
        self.setObjectName("MergeDialog")
        self.resize(560, 420)
        self.files = QListWidget()
        self.files.setAccessibleName(_("Archivos a combinar"))
        self.files.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.files.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.files.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.files.model().rowsMoved.connect(lambda *_: self.refresh_buttons())
        self.files.model().rowsInserted.connect(lambda *_: self.refresh_buttons())
        self.files.model().rowsRemoved.connect(lambda *_: self.refresh_buttons())
        self.add_button = QPushButton(_("Añadir…"))
        self.remove_button = QPushButton(_("Quitar"))
        self.up_button = QPushButton(_("Subir"))
        self.down_button = QPushButton(_("Bajar"))
        self.position = QComboBox()
        self.position.addItem(_("Al final"), "end")
        self.position.addItem(_("Tras la página actual ({n})", n=current + 1), "after")
        self.position.addItem(_("Documento nuevo"), "new")
        self.hint = QLabel(_("Arrastra los archivos para cambiar su orden. Cada uno se añade con todas sus páginas."))
        self.hint.setWordWrap(True)
        self.summary = QLabel()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.merge_button = buttons.addButton(_("Combinar"), QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.rejected.connect(self.reject)
        self.merge_button.clicked.connect(self.accept)
        self.add_button.clicked.connect(self.choose_files)
        self.remove_button.clicked.connect(self.remove_selected)
        self.up_button.clicked.connect(lambda: self.move_selected(-1))
        self.down_button.clicked.connect(lambda: self.move_selected(1))
        row = QHBoxLayout()
        for widget in (self.add_button, self.remove_button, self.up_button, self.down_button):
            row.addWidget(widget)
        layout = QVBoxLayout(self)
        layout.addWidget(self.hint)
        layout.addLayout(row)
        layout.addWidget(self.files, 1)
        layout.addWidget(self.summary)
        place = QHBoxLayout()
        place.addWidget(QLabel(_("Posición:")))
        place.addWidget(self.position, 1)
        layout.addLayout(place)
        layout.addWidget(buttons)
        self.refresh_buttons()

    def add_files(self, paths):
        for path in paths:
            try:
                count = page_count_of(path)
            except Exception:
                count = None
            if count is None:
                QMessageBox.warning(self, _("No se puede combinar"), _("El archivo no es un PDF legible o está protegido: {name}", name=Path(path).name))
                continue
            item = QListWidgetItem(_("{name}  ·  {count} página(s)", name=Path(path).name, count=count))
            item.setToolTip(path)
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setData(Qt.ItemDataRole.UserRole + 1, count)
            self.files.addItem(item)
        self.refresh_buttons()

    def choose_files(self):
        paths, _filter = QFileDialog.getOpenFileNames(self, _("Añadir PDF para combinar"), "", "PDF (*.pdf)")
        if paths:
            self.add_files(paths)

    def remove_selected(self):
        for item in self.files.selectedItems():
            self.files.takeItem(self.files.row(item))
        self.refresh_buttons()

    def move_selected(self, step):
        rows = sorted(self.files.row(item) for item in self.files.selectedItems())
        if not rows or (step < 0 and rows[0] == 0) or (step > 0 and rows[-1] == self.files.count() - 1):
            return
        for row in (rows if step < 0 else reversed(rows)):
            item = self.files.takeItem(row)
            self.files.insertItem(row + step, item)
            item.setSelected(True)
        self.refresh_buttons()

    def refresh_buttons(self):
        has_files = self.files.count() > 0
        has_selection = bool(self.files.selectedItems())
        self.remove_button.setEnabled(has_selection)
        self.up_button.setEnabled(has_selection)
        self.down_button.setEnabled(has_selection)
        self.merge_button.setEnabled(has_files)
        pages = sum(self.files.item(row).data(Qt.ItemDataRole.UserRole + 1) or 0 for row in range(self.files.count()))
        self.summary.setText(_("{files} archivo(s) · {pages} página(s) en total", files=self.files.count(), pages=pages) if has_files else _("Añade uno o varios PDF"))

    def values(self):
        paths = [self.files.item(row).data(Qt.ItemDataRole.UserRole) for row in range(self.files.count())]
        return paths, self.position.currentData()
