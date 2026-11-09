from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QStyle, QStyledItemDelegate
from pathlib import Path

from . import icons, theme


class RailButton(QPushButton):
    """Tool row for the left rail; the active tool gets a soft fill plus an accent bar on its left edge."""

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.isCheckable() and self.isChecked() and self.isEnabled():
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.current_tokens()["accent"]))
            painter.drawRoundedRect(QRectF(0, 7, 3.5, max(8, self.height() - 14)), 1.75, 1.75)
            painter.end()


class ThumbnailDelegate(QStyledItemDelegate):
    """Page card: soft shadow under the thumbnail, page number caption, accent outline when selected."""

    def paint(self, painter, option, index):
        tokens = theme.current_tokens()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        card = QRectF(option.rect).adjusted(8, 3, -8, -3)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        view = self.parent()
        thumb = getattr(view, "thumb_size", QSize(104, 145))
        current = view is not None and view.currentRow() == index.row()
        if selected or hovered:
            painter.setPen(QPen(QColor(tokens["accent"]), 2) if selected else Qt.PenStyle.NoPen)
            painter.setBrush(QColor(tokens["accentsoft"] if selected else tokens["surface2"]))
            painter.drawRoundedRect(card.adjusted(1, 1, -1, -1), 10, 10)
        if current and not selected:
            painter.setPen(QPen(QColor(tokens["accent"]), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(card.adjusted(1, 1, -1, -1), 10, 10)
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        area = QRectF(card.left(), card.top() + 10, card.width(), card.height() - 40)
        size = QSize(thumb)
        if isinstance(icon, QIcon) and not icon.isNull():
            size = icon.actualSize(QSize(thumb))
        page = QRectF(area.center().x() - size.width() / 2, area.center().y() - size.height() / 2, size.width(), size.height())
        shadow = QColor(tokens["shadow"])
        for step in range(5):
            shadow.setAlpha(round(34 * (1 - step / 5) ** 2))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(shadow)
            painter.drawRoundedRect(page.adjusted(-step, -step + 2, step, step + 2), 2 + step, 2 + step)
        if isinstance(icon, QIcon) and not icon.isNull():
            icon.paint(painter, page.toRect())
        else:
            painter.setBrush(QColor("#FFFFFF"))
            painter.setPen(QPen(QColor(tokens["border"]), 1))
            painter.drawRect(page)
        edge = QColor(tokens["shadow"])
        edge.setAlpha(50)
        painter.setPen(QPen(edge, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(page)
        font = QFont(option.font)
        font.setPointSizeF(max(8.0, option.font.pointSizeF() - 1))
        font.setWeight(QFont.Weight.DemiBold if selected else QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(QColor(tokens["accent"] if selected else tokens["inkmuted"]))
        caption = QRectF(card.left(), card.bottom() - 26, card.width(), 20)
        painter.drawText(caption, Qt.AlignmentFlag.AlignCenter, str(index.data(Qt.ItemDataRole.UserRole) or index.row() + 1))
        drop = getattr(view, "pending_drop", None)
        if drop is not None:
            if index.row() == drop:
                line_y = option.rect.top() + 1
            elif drop == view.count() and index.row() == drop - 1:
                line_y = option.rect.bottom() - 1
            else:
                line_y = None
            if line_y is not None:
                painter.setPen(QPen(QColor(tokens["accent"]), 3))
                painter.drawLine(QRectF(option.rect).left() + 8, line_y, QRectF(option.rect).right() - 8, line_y)
        painter.restore()

    def sizeHint(self, option, index):
        view = self.parent()
        if view is not None and hasattr(view, "item_size"):
            return view.item_size()
        return QSize(140, 188)


class RecentDelegate(QStyledItemDelegate):
    """Recent file row: file glyph in a soft tile, bold name, folder underneath."""

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
        tile = QRectF(row.left() + 10, row.center().y() - 18, 36, 36)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(tokens["accentsoft"]))
        painter.drawRoundedRect(tile, 9, 9)
        ratio = painter.device().devicePixelRatioF()
        glyph = icons.pixmap("file", tokens["accent"], 20, ratio)
        painter.drawPixmap(QRectF(tile.center().x() - 10, tile.center().y() - 10, 20, 20).toRect(), glyph)
        text_left = tile.right() + 12
        width = row.right() - text_left - 8
        path = str(index.data(Qt.ItemDataRole.UserRole) or "")
        name_font = QFont(option.font)
        name_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(name_font)
        painter.setPen(QColor(tokens["ink"]))
        name = painter.fontMetrics().elidedText(str(index.data(Qt.ItemDataRole.DisplayRole)), Qt.TextElideMode.ElideMiddle, int(width))
        painter.drawText(QRectF(text_left, row.top() + 7, width, 20), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, name)
        small = QFont(option.font)
        small.setPointSizeF(max(8.0, option.font.pointSizeF() - 1))
        painter.setFont(small)
        painter.setPen(QColor(tokens["inkmuted"]))
        folder = painter.fontMetrics().elidedText(str(Path(path).parent), Qt.TextElideMode.ElideLeft, int(width))
        painter.drawText(QRectF(text_left, row.top() + 26, width, 18), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, folder)
        painter.restore()

    def sizeHint(self, option, index):
        return QSize(100, 52)


def make_pill(*widgets, name="Pill"):
    """Rounded group that holds related controls (page navigator, zoom)."""
    frame = QFrame()
    frame.setObjectName(name)
    row = QHBoxLayout(frame)
    row.setContentsMargins(3, 2, 3, 2)
    row.setSpacing(0)
    for widget in widgets:
        row.addWidget(widget)
    return frame
