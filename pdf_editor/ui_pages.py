from __future__ import annotations

from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMenu,
    QPushButton, QRadioButton, QSpinBox, QToolButton, QVBoxLayout, QWidget,
)
from pathlib import Path

from .lang import _, N_, ntext
from .pages_panel import MergeDialog, moved_order, notify
from .toast import notify_folder
from .ui_support import CANCELLED

IMAGE_FILTER = N_("Imágenes (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp)")


class SplitDialog(QDialog):
    """Options for splitting the document: values() -> engine.split_by arguments plus 'folder'."""
    MODES = [("each", N_("Una página por archivo")), ("every", N_("Cada N páginas")),
             ("bookmarks", N_("Por marcadores (nivel 1)")), ("ranges", N_("Por rangos"))]

    def __init__(self, page_count=1, folder="", parent=None):
        super().__init__(parent)
        self.setObjectName("SplitDialog")
        self.setWindowTitle(_("Dividir en archivos"))
        self.setModal(True)
        self.setMinimumWidth(480)
        self.page_count = max(1, page_count)
        layout = QVBoxLayout(self)
        self.group = QButtonGroup(self)
        self.buttons = {}
        for key, label in self.MODES:
            self.buttons[key] = QRadioButton(_(label))
            self.group.addButton(self.buttons[key])
            layout.addWidget(self.buttons[key])
        self.buttons["each"].setChecked(True)
        self.every = QSpinBox()
        self.every.setRange(1, self.page_count)
        self.every.setValue(min(2, self.page_count))
        self.ranges = QLineEdit()
        self.ranges.setPlaceholderText(_("Ejemplo: 1-3, 4-8"))
        self.prefix = QLineEdit("pagina")
        self.folder = QLineEdit(str(folder))
        browse = QPushButton(_("Examinar…"))
        browse.clicked.connect(self.browse)
        folder_row = QHBoxLayout()
        folder_row.addWidget(self.folder, 1)
        folder_row.addWidget(browse)
        form = QFormLayout()
        form.addRow(_("Páginas por archivo"), self.every)
        form.addRow(_("Rangos"), self.ranges)
        form.addRow(_("Prefijo del nombre"), self.prefix)
        form.addRow(_("Carpeta"), folder_row)
        layout.addLayout(form)
        self.error = QLabel("")
        self.error.setObjectName("caption")
        self.error.setProperty("state", "error")
        self.error.setWordWrap(True)
        self.error.hide()
        layout.addWidget(self.error)
        boxes = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        boxes.button(QDialogButtonBox.StandardButton.Ok).setText(_("Dividir"))
        boxes.button(QDialogButtonBox.StandardButton.Ok).setProperty("primary", True)
        boxes.accepted.connect(self.accept)
        boxes.rejected.connect(self.reject)
        layout.addWidget(boxes)
        self.group.buttonToggled.connect(self._sync)
        self._sync()

    def _mode(self):
        return next(key for key, button in self.buttons.items() if button.isChecked())

    def _sync(self, *_):
        mode = self._mode()
        self.every.setEnabled(mode == "every")
        self.ranges.setEnabled(mode == "ranges")

    def browse(self):
        folder = QFileDialog.getExistingDirectory(self, _("Carpeta para los archivos"), self.folder.text())
        if folder:
            self.folder.setText(folder)

    def accept(self):
        if not self.folder.text().strip():
            self.error.setText(_("Elige la carpeta donde se guardarán los archivos."))
            self.error.show()
            return
        if self._mode() == "ranges" and not self.ranges.text().strip():
            self.error.setText(_("Escribe al menos un rango, por ejemplo 1-3, 4-8."))
            self.error.show()
            return
        super().accept()

    def values(self):
        return {
            "folder": self.folder.text().strip(),
            "mode": self._mode(),
            "pages_per_file": self.every.value(),
            "ranges": self.ranges.text(),
            "prefix": self.prefix.text(),
        }


class UiPagesMixin:
    """Page operations on the thumbnail selection: rotate, delete, duplicate, move, insert, merge, extract."""

    def selected_pages(self):
        return sorted(self.thumbnails.row(item) for item in self.thumbnails.selectedItems()) or [self.page]

    def rotate(self):
        self.rotate_selected(90)

    def rotate_selected(self, angle):
        self.change(lambda: self.engine.rotate(self.selected_pages(), angle))

    def delete_pages(self):
        pages = self.selected_pages()
        self.change(lambda: self.engine.delete_pages(pages))
        count = len(pages)
        notify(self, ntext(count, "1 página eliminada", "{n} páginas eliminadas"), _("Deshacer"), self.undo)

    def duplicate_pages_selected(self):
        pages = self.selected_pages()
        self.change(lambda: self.engine.duplicate_selected(pages))
        notify(self, _("{n} página(s) duplicada(s)", n=len(pages)), _("Deshacer"), self.undo)

    def insert_blank_here(self):
        after = self.page
        rect = self.engine.doc[after].rect
        self.change(lambda: self.engine.insert_blank_page(after, size="Personalizado", width=rect.width, height=rect.height))
        self.goto(after + 1)

    def insert_image_here(self):
        path, _filter = QFileDialog.getOpenFileName(self, _("Insertar imagen como página"), "", _(IMAGE_FILTER))
        if path:
            after = self.page
            index = self.change(lambda: self.engine.insert_image_page(after, path))
            self.goto(index)

    def extract(self):
        pages = self.selected_pages()
        if self.confirm_unprotected_output(_("El archivo con las páginas extraídas")):
            path, _filter = QFileDialog.getSaveFileName(self, _("Guardar páginas extraídas"), _("Páginas.pdf"), "PDF (*.pdf)")
            if path and self.with_redaction_gate(lambda allow: self.engine.extract(pages, path, allow_pending_redactions=allow), N_("Continuar de todos modos")) is not CANCELLED:
                self.statusBar().showMessage(_("Páginas extraídas: {path}", path=path))

    def move_pages(self, selected, target):
        """Moves the selected pages in front of old position ``target`` as one undo step."""
        if not self.has_doc():
            return
        count = self.engine.page_count
        order = moved_order(count, selected, target)
        if order == list(range(count)):
            return
        current = self.page
        moved = [order.index(index) for index in sorted(set(selected))]

        def apply():
            self.engine.reorder(order)
            self.page = order.index(current)

        self.change(apply)
        self.thumbnails.clearSelection()
        for index in moved:
            self.thumbnails.item(index).setSelected(True)

    def merge(self):
        dialog = MergeDialog(self.page, self)
        if not dialog.exec():
            return
        paths, where = dialog.values()
        if not paths:
            return
        if where == "new":
            self.merge_as_new_document(paths)
        else:
            self.insert_files(paths, self.engine.page_count if where == "end" else self.page + 1)

    def insert_files(self, paths, at):
        before = self.engine.page_count
        self.change(lambda: self.engine.merge(paths, at))
        added = self.engine.page_count - before
        notify(self, _("{n} página(s) insertadas", n=added), _("Deshacer"), self.undo)
        self.goto(at)

    def merge_as_new_document(self, paths):
        self.remember_view()
        with self.new_tab():
            self.engine.new()
            self.engine.merge(paths, 0)
            self.engine.delete_pages([self.engine.page_count - 1])
            self.engine.dirty = True
        self.refresh()
        self.statusBar().showMessage(_("Documento nuevo con {n} página(s)", n=self.engine.page_count))

    def dropped_files(self, paths, at):
        if not self.has_doc():
            self.run(lambda: self.open_path(paths[0]))
            return
        self.insert_files(paths, at)

    def page_actions(self):
        """Actions on the thumbnail selection, shared by the context menu and the mini bar. None is a separator."""
        return [
            (_("Girar 90° a la izquierda"), lambda: self.rotate_selected(-90)),
            (_("Girar 90° a la derecha"), lambda: self.rotate_selected(90)),
            (_("Duplicar"), self.duplicate_pages_selected),
            (_("Insertar en blanco aquí"), self.insert_blank_here),
            (_("Insertar desde imagen…"), self.insert_image_here),
            None,
            (_("Extraer seleccionadas…"), self.extract),
            (_("Eliminar"), self.delete_pages),
            None,
            (_("Etiquetas de página…"), self.page_labels),
        ]

    def thumbnail_menu(self, point):
        if not self.has_doc():
            return
        menu = QMenu(self)
        for entry in self.page_actions():
            if entry is None:
                menu.addSeparator()
            else:
                label, handler = entry
                menu.addAction(label, lambda _=False, h=handler: self.run(h))
        menu.exec(self.thumbnails.viewport().mapToGlobal(point))

    def build_page_bar(self):
        bar = QWidget()
        bar.setObjectName("PageBar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(6, 4, 6, 4)
        row.setSpacing(0)
        short = {_("Girar 90° a la derecha"): _("Girar"), _("Duplicar"): _("Copiar"), _("Eliminar"): _("Borrar"), _("Extraer seleccionadas…"): _("Extraer")}
        for entry in self.page_actions():
            if entry is None or entry[0] not in short:
                continue
            label, handler = entry
            button = QToolButton()
            button.setText(short[label])
            button.setToolTip(label)
            button.setAccessibleName(label)
            button.setAutoRaise(True)
            button.setStyleSheet("QToolButton { padding: 3px 3px; }")
            button.clicked.connect(lambda _=False, h=handler: self.run(h))
            row.addWidget(button)
        row.addStretch(1)
        self.page_bar = bar
        return bar

    def focus_bookmarks(self):
        if not self.has_doc():
            return
        if self.pages_collapsed:
            self.toggle_pages()
        self.left_tabs.setCurrentWidget(self.bookmark_panel)
        self.bookmark_list.setFocus()

    def save_bookmarks(self, toc):
        current = [[level, title, page] for level, title, page, *_rest in self.engine.bookmarks()] if self.has_doc() else []
        if self.has_doc() and toc != current:
            self.change(lambda: self.engine.set_bookmarks(toc))

    def split(self):
        if not self.confirm_unprotected_output(_("Los archivos resultantes")):
            return
        default = str(Path(self.engine.path).parent) if self.engine.path else ""
        dialog = SplitDialog(self.engine.page_count, default, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        options = dialog.values()
        folder = options.pop("folder")
        created = self.with_redaction_gate(lambda allow: self.busy(_("Dividiendo documento…"), lambda: self.engine.split_by(folder, allow_pending_redactions=allow, **options)), N_("Continuar de todos modos"))
        if created is not CANCELLED:
            self.statusBar().showMessage(_("Documento dividido en {n} archivos: {folder}", n=len(created), folder=folder))
            notify_folder(self, _("Documento dividido en {n} archivos", n=len(created)), folder)
