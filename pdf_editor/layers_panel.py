from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QLabel, QStackedLayout, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from .lang import _
NUMBER_ROLE = Qt.ItemDataRole.UserRole


class LayersPanel(QWidget):
    """Pestaña Capas: una casilla por capa (con jerarquía) y la opción de recordar el estado al guardar."""

    layerToggled = Signal(int, bool)   # número de capa, visible
    rememberChanged = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("LayersPanel")
        self.tree = QTreeWidget()
        self.tree.setObjectName("LayersTree")
        self.tree.setAccessibleName(_("Capas del documento"))
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.itemChanged.connect(self._item_changed)
        self.empty = QLabel(_("Este documento no tiene capas"))
        self.empty.setObjectName("LayersEmpty")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        self.remember = QCheckBox(_("Recordar al guardar"))
        self.remember.setToolTip(_("Guarda en el archivo qué capas están visibles. Si no lo marcas, el PDF conserva su estado original."))
        self.remember.toggled.connect(self.rememberChanged)
        holder = QWidget()
        self.stack = QStackedLayout(holder)
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.tree)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        layout.addWidget(holder, 1)
        layout.addWidget(self.remember)

    def set_layers(self, rows, remembered=False):
        """Rellena el árbol sin disparar cambios."""
        self.tree.blockSignals(True)
        self.remember.blockSignals(True)
        try:
            self.tree.clear()
            stack = [self.tree.invisibleRootItem()]
            for row in rows:
                depth = min(max(int(row.get("depth", 0)), 0), len(stack) - 1)
                item = QTreeWidgetItem([str(row.get("text") or _("Capa sin nombre"))])
                item.setData(0, NUMBER_ROLE, int(row["number"]))
                if row.get("type") == "label":
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                else:
                    flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable
                    if row.get("locked"):
                        flags = Qt.ItemFlag.NoItemFlags
                    item.setFlags(flags)
                    item.setCheckState(0, Qt.CheckState.Checked if row.get("on") else Qt.CheckState.Unchecked)
                stack[depth].addChild(item)
                del stack[depth + 1:]
                stack.append(item)
            self.tree.expandAll()
            self.remember.setChecked(bool(remembered))
        finally:
            self.tree.blockSignals(False)
            self.remember.blockSignals(False)
        self.stack.setCurrentWidget(self.tree if rows else self.empty)
        self.remember.setEnabled(bool(rows))

    def _item_changed(self, item, column):
        if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
            self.layerToggled.emit(item.data(0, NUMBER_ROLE), item.checkState(0) == Qt.CheckState.Checked)
