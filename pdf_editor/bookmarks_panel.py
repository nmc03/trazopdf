from __future__ import annotations

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QMenu, QToolButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from .lang import _


class BookmarkTree(QTreeWidget):
    """Árbol editable de marcadores. Cada cambio se guarda con commitRequested (un paso de deshacer)."""

    commitRequested = Signal(list)   # tabla [nivel, título, página] con páginas desde 1
    pageRequested = Signal(int)      # página (desde 0) a la que saltar

    def __init__(self, parent=None):
        super().__init__(parent)
        self.page_provider = lambda: 0
        self._commit_pending = False
        self.setObjectName("BookmarkTree")
        self.setAccessibleName(_("Marcadores del documento"))
        self.setHeaderLabels([_("Marcador"), _("Pág.")])
        self.setColumnCount(2)
        self.setRootIsDecorated(True)
        self.setUniformRowHeights(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.header().setStretchLastSection(False)
        self.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)
        self.itemChanged.connect(lambda *_: self.schedule_commit())
        self.itemDelegate().closeEditor.connect(lambda *_: self.schedule_commit())
        self.itemClicked.connect(lambda item, _: self.pageRequested.emit(item.data(0, Qt.ItemDataRole.UserRole)))

    def new_item(self, title, page):
        item = QTreeWidgetItem([title, str(page + 1)])
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsDropEnabled)
        item.setData(0, Qt.ItemDataRole.UserRole, page)
        return item

    def make_item(self, parent, title, page):
        item = self.new_item(title, page)
        parent.addChild(item)
        return item

    def set_toc(self, toc):
        """Carga la tabla de marcadores del documento sin disparar guardados."""
        self.blockSignals(True)
        try:
            self.clear()
            stack = [self.invisibleRootItem()]
            for entry in toc:
                level, title, page = int(entry[0]), str(entry[1]), int(entry[2])
                depth = min(max(level, 1), len(stack))
                item = self.make_item(stack[depth - 1], title, page - 1)
                del stack[depth:]
                stack.append(item)
            self.expandAll()
        finally:
            self.blockSignals(False)

    def to_toc(self):
        toc = []

        def walk(parent, depth):
            for row in range(parent.childCount()):
                child = parent.child(row)
                title = child.text(0).strip() or "Marcador"
                toc.append([depth + 1, title, child.data(0, Qt.ItemDataRole.UserRole) + 1])
                walk(child, depth + 1)

        walk(self.invisibleRootItem(), 0)
        return toc

    def schedule_commit(self):
        # Deferred and coalesced: the window rebuilds this tree while saving, so that must not
        # happen inside this tree's own signals or while a rename editor is still open.
        if self._commit_pending:
            return
        self._commit_pending = True
        QTimer.singleShot(0, self._emit_commit)

    def _emit_commit(self):
        self._commit_pending = False
        self.commitRequested.emit(self.to_toc())

    def add_marker(self, page, child=False):
        """Crea un marcador en la página indicada: subnivel del seleccionado, o hermano tras él."""
        selected = self.currentItem()
        item = self.new_item(_("Marcador nuevo"), page)
        if selected is not None and child:
            selected.addChild(item)
            selected.setExpanded(True)
        elif selected is not None:
            parent = selected.parent() or self.invisibleRootItem()
            parent.insertChild(parent.indexOfChild(selected) + 1, item)
        else:
            self.invisibleRootItem().addChild(item)
        self.setCurrentItem(item)
        self.editItem(item, 0)  # saved when the name is confirmed (closeEditor)
        return item

    def delete_selected(self):
        items = self.selectedItems()
        for item in items:
            parent = item.parent()
            if parent is not None and parent.isSelected():
                continue  # removed together with its selected ancestor
            (parent or self.invisibleRootItem()).removeChild(item)
        if items:
            self.schedule_commit()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Delete:
            self.delete_selected()
            event.accept()
            return
        super().keyPressEvent(event)

    def dropEvent(self, event):
        super().dropEvent(event)
        self.schedule_commit()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        page = self.page_provider()
        menu.addAction(_("Marcador aquí"), lambda: self.add_marker(page))
        if self.currentItem() is not None:
            menu.addAction(_("Nuevo subnivel"), lambda: self.add_marker(page, child=True))
            menu.addAction(_("Renombrar"), lambda: self.editItem(self.currentItem(), 0))
            menu.addSeparator()
            menu.addAction(_("Eliminar"), self.delete_selected)
        menu.exec(event.globalPos())


class BookmarksPanel(QWidget):
    """Pestaña Marcadores: barra con «+ marcador aquí» y el árbol editable."""

    addRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("BookmarksPanel")
        self.tree = BookmarkTree(self)
        self.add_button = QToolButton()
        self.add_button.setText(_("+ Marcador aquí"))
        self.add_button.setToolTip(_("Añadir un marcador en la página actual"))
        self.add_button.setAccessibleName(_("Añadir marcador aquí"))
        self.add_button.setAutoRaise(True)
        self.add_button.clicked.connect(lambda _=False: self.addRequested.emit())
        bar = QHBoxLayout()
        bar.setContentsMargins(6, 4, 6, 4)
        bar.addWidget(self.add_button)
        bar.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(bar)
        layout.addWidget(self.tree, 1)
