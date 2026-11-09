from __future__ import annotations

from PySide6.QtCore import QTimer, QUrl, Qt
from PySide6.QtGui import QDesktopServices, QKeySequence, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView, QAbstractSpinBox, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QTableWidget, QTableWidgetItem, QTextEdit,
    QVBoxLayout, QWidget,
)
from pathlib import Path
import pymupdf as fitz

from . import __version__, icons, toast
from .doctools_dialogs import format_size
from .lang import _, N_
from .layers_panel import LayersPanel
from .signing_ui import open_choice, use_canvas_banner
from .ui_support import ROOT


class UiDialogsMixin:
    """Information dialogs: about, bookmarks, comments, attachments, links, metadata, forms."""

    def metadata(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(_("Propiedades del documento"))
        form = QFormLayout(dialog)
        data = self.engine.metadata()
        fields = {}
        for key, label in [("title", _("Título")), ("author", _("Autor")), ("subject", _("Asunto")), ("keywords", _("Palabras clave"))]:
            fields[key] = QLineEdit(data.get(key, ""))
            form.addRow(label, fields[key])
        form.addRow(_("Páginas"), QLabel(str(self.engine.page_count)))
        form.addRow(_("Tamaño"), QLabel(format_size(len(self.engine._bytes()))))
        form.addRow(_("Versión PDF"), QLabel(data.get("format") or _("Desconocida")))
        form.addRow(_("Cifrado"), QLabel(_("Sí: protegido con contraseña") if self.engine.is_protected else _("No")))
        form.addRow(_("Archivo"), QLabel(self.engine.path or _("Sin guardar")))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(_("Guardar"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(_("Cancelar"))
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec():
            updated = {k: v for k, v in data.items() if k in {"title", "author", "subject", "keywords", "creator", "producer", "creationDate", "modDate", "trapped"}}
            updated.update({key: value.text() for key, value in fields.items()})
            self.change(lambda: self.engine.set_metadata(updated))

    def forms_dialog(self):
        """Optional field list. Filling directly on the page (Rellenar y firmar) is the main path."""
        fields = self.engine.forms()
        if not fields:
            use_canvas_banner(self)
            toast.notify(self, _("Este PDF no tiene campos de formulario. Usa Rellenar y firmar para escribir sobre la página."))
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(_("Lista de campos"))
        dialog.setModal(False)
        dialog.resize(650, 450)
        layout = QVBoxLayout(dialog)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        form = QFormLayout(content)
        editors = []
        for field in fields:
            value = field.get("value", "")
            kind = str(field.get("type", ""))
            if kind.lower() == "signature" or kind == str(fitz.PDF_WIDGET_TYPE_SIGNATURE):
                continue
            if kind.lower() == "checkbox" or kind == str(fitz.PDF_WIDGET_TYPE_CHECKBOX):
                editor = QCheckBox(_("Marcada"))
                editor.setChecked(bool(value and str(value) != "Off"))
            elif field.get("choices"):
                editor = QComboBox()
                editor.addItems([str(x) for x in field["choices"]])
                editor.setCurrentText(str(value or ""))
            else:
                editor = QLineEdit(str(value or ""))
            form.addRow(_("{name} · pág. {n}", name=field['name'], n=field['page'] + 1), editor)
            editors.append((field, editor))
        scroll.setWidget(content)
        layout.addWidget(scroll)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        def fill():
            edits = []
            for field, editor in editors:
                value = editor.isChecked() if isinstance(editor, QCheckBox) else editor.currentText() if isinstance(editor, QComboBox) else editor.text()
                edits.append((field["page"], field["xref"], value))
            self.engine.fill_forms(edits)
        dialog.accepted.connect(lambda: self.run(lambda: self.change(fill)))
        self.field_list_dialog = dialog
        dialog.show()

    def edit_field_at(self, point):
        for widget in self.engine.doc[self.page].widgets() or ():
            if not widget.rect.contains(point):
                continue
            if widget.field_flags & 1:
                self.statusBar().showMessage(_("Este campo es de solo lectura"))
            elif widget.field_type == fitz.PDF_WIDGET_TYPE_CHECKBOX:
                checked = widget.field_value not in (None, "", "Off")
                self.change(lambda: self.engine.fill_form(self.page, widget.xref, not checked))
            elif widget.field_type == fitz.PDF_WIDGET_TYPE_TEXT:
                self.view.begin_form_editor(widget)
            elif widget.field_type == fitz.PDF_WIDGET_TYPE_RADIOBUTTON:
                self.run(lambda: self.change(lambda: self.engine.select_radio(self.page, widget.xref)))
            elif widget.field_type in (fitz.PDF_WIDGET_TYPE_COMBOBOX, fitz.PDF_WIDGET_TYPE_LISTBOX):
                open_choice(self.view, self.page, widget.xref, fitz.Rect(widget.rect), widget.choice_values or [], widget.field_value)
            elif widget.field_type == fitz.PDF_WIDGET_TYPE_SIGNATURE:
                self.statusBar().showMessage(_("Usa Seguridad → Firmar con certificado para las firmas digitales"))
            else:
                self.forms_dialog()
            return True
        return False

    def attachments_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(_("Archivos adjuntos"))
        dialog.resize(550, 360)
        layout = QVBoxLayout(dialog)
        listing = QListWidget()
        layout.addWidget(listing)
        def refresh():
            listing.clear()
            for entry in self.engine.attachments():
                name = entry if isinstance(entry, str) else entry.get("name", entry.get("filename", ""))
                listing.addItem(name)
        refresh()
        row = QHBoxLayout()
        def add():
            path, _filter = QFileDialog.getOpenFileName(dialog, _("Adjuntar archivo"))
            if path:
                self.change(lambda: self.engine.attach(path))
                refresh()
        def extract():
            item = listing.currentItem()
            if item:
                path, _filter = QFileDialog.getSaveFileName(dialog, _("Guardar adjunto"), Path(item.text()).name)
                if path:
                    self.engine.extract_attachment(item.text(), path)
        def remove():
            item = listing.currentItem()
            if item:
                self.change(lambda: self.engine.remove_attachment(item.text()))
                refresh()
        for title, handler in [(_("Añadir"), add), (_("Extraer"), extract), (_("Eliminar"), remove)]:
            button = QPushButton(title)
            button.clicked.connect(lambda _, f=handler: self.run(f))
            row.addWidget(button)
        layout.addLayout(row)
        dialog.exec()

    def bookmarks_dialog(self):
        text = "\n".join(f"{level}|{page}|{title}" for level, title, page, *_rest in self.engine.bookmarks())
        dialog = QDialog(self)
        dialog.setWindowTitle(_("Editar marcadores"))
        dialog.resize(600, 430)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(_("Una línea por marcador: nivel|página|título. Ejemplo: 1|3|Introducción")))
        editor = QTextEdit()
        editor.setPlainText(text)
        layout.addWidget(editor)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec():
            toc = []
            for line in editor.toPlainText().splitlines():
                if line.strip():
                    level, number, title = line.split("|", 2)
                    toc.append([int(level), title.strip(), int(number)])
            self.change(lambda: self.engine.set_bookmarks(toc))

    def comments_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(_("Comentarios y anotaciones"))
        dialog.resize(780, 450)
        layout = QVBoxLayout(dialog)
        table = QTableWidget(0, 3)
        table.setHorizontalHeaderLabels([_("Página"), _("Tipo"), _("Comentario")])
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        entries = []
        for number, page in enumerate(self.engine.doc):
            for annot in page.annots() or []:
                entries.append((number, annot.xref))
                row = table.rowCount()
                table.insertRow(row)
                for column, value in enumerate([str(number + 1), annot.type[1], annot.info.get("content", "")]):
                    table.setItem(row, column, QTableWidgetItem(value))
        layout.addWidget(table)
        row = QHBoxLayout()
        def locate():
            index = table.currentRow()
            if index >= 0:
                self.goto(entries[index][0])
                dialog.accept()
        def remove():
            index = table.currentRow()
            if index >= 0:
                number, xref = entries[index]
                self.engine.delete_annotation(number, xref)
                self.refresh()
                dialog.accept()
        for title, handler in [(_("Ir a la página"), locate), (_("Eliminar anotación"), remove)]:
            button = QPushButton(title)
            button.clicked.connect(lambda _, f=handler: self.run(f))
            row.addWidget(button)
        layout.addLayout(row)
        dialog.exec()

    def edit_link(self, rect=None, link=None):
        dialog = QDialog(self)
        dialog.setWindowTitle(_("Editar enlace") if link else _("Crear enlace"))
        form = QFormLayout(dialog)
        kind = QComboBox()
        kind.addItems([_("Web o correo"), _("Página de este PDF")])
        uri = QLineEdit(link.get("uri", "https://") if link else "https://")
        target = QSpinBox()
        target.setRange(1, self.engine.page_count)
        if link and link.get("kind") == fitz.LINK_GOTO:
            kind.setCurrentIndex(1)
            target.setValue(link.get("page", 0) + 1)
        box = fitz.Rect(rect if rect is not None else link["from"])
        controls = []
        for label, value in zip((_("X (pt)"), _("Y (pt)"), _("Anchura (pt)"), _("Altura (pt)")), (box.x0, box.y0, box.width, box.height)):
            control = QDoubleSpinBox()
            control.setRange(0, 20000)
            control.setDecimals(2)
            control.setValue(value)
            controls.append(control)
            form.addRow(label, control)
        form.addRow(_("Destino"), kind)
        form.addRow(_("Dirección"), uri)
        form.addRow(_("Página"), target)
        def update_kind():
            uri.setEnabled(kind.currentIndex() == 0)
            target.setEnabled(kind.currentIndex() == 1)
        kind.currentIndexChanged.connect(update_kind)
        update_kind()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        def apply():
            x, y, width, height = (control.value() for control in controls)
            try:
                self.engine.set_link(self.page, (x, y, x + width, y + height),
                    uri=uri.text() if kind.currentIndex() == 0 else None,
                    target_page=target.value() - 1 if kind.currentIndex() == 1 else None,
                    xref=link["xref"] if link else None)
            except Exception as error:
                QMessageBox.warning(dialog, _("No se ha guardado el enlace"), str(error))
                return
            self.search_results = []
            self.refresh()
            dialog.accept()
        buttons.accepted.connect(apply)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        return dialog.exec()

    def open_link(self, link):
        if link.get("kind") == fitz.LINK_GOTO and link.get("page", -1) >= 0:
            self.goto(link["page"])
        elif link.get("kind") == fitz.LINK_URI:
            uri = self.engine.validate_uri(link.get("uri", ""))
            QDesktopServices.openUrl(QUrl(uri))
        else:
            raise ValueError(_("Este tipo de enlace no se puede abrir desde TrazoPDF."))

    def links_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(_("Enlaces del documento"))
        dialog.resize(780, 470)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(_("Selecciona un enlace para abrirlo, editarlo o eliminarlo. Para crear uno, arrastra con la herramienta Enlace.")))
        table = QTableWidget(0, 3)
        table.setHorizontalHeaderLabels([_("Página"), _("Tipo"), _("Destino")])
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(table)
        entries = []
        def populate():
            entries.clear()
            for page in range(self.engine.page_count):
                entries.extend((page, link) for link in self.engine.links(page))
            table.setRowCount(len(entries))
            for row, (page, link) in enumerate(entries):
                destination = link.get("uri", "") if link.get("kind") == fitz.LINK_URI else _("Página {n}", n=link['page'] + 1) if link.get("kind") == fitz.LINK_GOTO and link.get("page", -1) >= 0 else _("Destino no editable")
                for column, text in enumerate((str(page + 1), _("Web / correo") if "uri" in link else _("Interno") if link.get("kind") == fitz.LINK_GOTO else _("Otro"), destination)):
                    table.setItem(row, column, QTableWidgetItem(text))
            if entries:
                table.selectRow(0)
        def selected(operation):
            row = table.currentRow()
            if not 0 <= row < len(entries):
                return
            page, link = entries[row]
            if operation == "open":
                self.run(lambda: self.open_link(link))
            elif operation == "edit":
                if link.get("kind") not in (fitz.LINK_URI, fitz.LINK_GOTO):
                    QMessageBox.information(dialog, _("Enlace"), _("Puedes eliminar este enlace, pero su tipo de destino no admite edición."))
                    return
                self.goto(page)
                self.edit_link(link=link)
                populate()
            else:
                self.run(lambda: self.change(lambda: self.engine.delete_link(page, link["xref"])))
                populate()
        row = QHBoxLayout()
        for label, operation in ((_("Abrir destino"), "open"), (_("Editar"), "edit"), (_("Eliminar"), "delete")):
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, op=operation: selected(op))
            row.addWidget(button)
        close = QPushButton(_("Cerrar"))
        close.clicked.connect(dialog.accept)
        row.addWidget(close)
        layout.addLayout(row)
        populate()
        dialog.exec()

    def about(self):
        dialog = QDialog(self)
        dialog.setObjectName("AboutDialog")
        dialog.setWindowTitle(_("Acerca de TrazoPDF"))
        dialog.setMinimumWidth(520)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(0)
        head = QHBoxLayout()
        head.setSpacing(16)
        mark = QLabel()
        mark.setPixmap(icons.app_mark(64, self.devicePixelRatioF()))
        mark.setFixedSize(64, 64)
        mark.setScaledContents(True)
        mark.setAccessibleName("TrazoPDF")
        head.addWidget(mark, 0, Qt.AlignmentFlag.AlignTop)
        titles = QVBoxLayout()
        title = QLabel("TrazoPDF")
        title.setObjectName("WelcomeTitle")
        version = QLabel(_("Versión {version}", version=__version__))
        version.setObjectName("caption")
        summary = QLabel(_("Aplicación local para editar PDFs en tu equipo. Los documentos no salen de él."))
        summary.setWordWrap(True)
        titles.addWidget(title)
        titles.addWidget(version)
        titles.addSpacing(4)
        titles.addWidget(summary)
        head.addLayout(titles, 1)
        layout.addLayout(head)
        layout.addSpacing(16)

        def link(name):
            target = ROOT / name
            return f'<a href="{QUrl.fromLocalFile(str(target)).toString()}">{name}</a>' if target.is_file() else name

        license_label = QLabel(_("Licencia: AGPL-3.0-or-later · Texto completo en {license} · Licencias de las bibliotecas en {third}", license=link('LICENSE'), third=link('THIRD-PARTY.md')))
        license_label.setObjectName("AboutLicense")
        license_label.setTextFormat(Qt.TextFormat.RichText)
        license_label.setOpenExternalLinks(True)
        license_label.setWordWrap(True)
        layout.addWidget(license_label)
        layout.addSpacing(16)
        heading = QLabel(_("Programas externos"))
        heading.setObjectName("section")
        layout.addWidget(heading)
        tools = self.engine.external_tools()
        diagnostics = QLabel("\n".join([
            f"Tesseract: {tools.get('tesseract') or _('no encontrado')}",
            f"LibreOffice: {tools.get('soffice') or _('no encontrado')}"]))
        diagnostics.setObjectName("AboutTools")
        diagnostics.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        diagnostics.setWordWrap(True)
        layout.addWidget(diagnostics)
        hint = QLabel(_("Si están instalados en otra ubicación, indica su ruta con las variables de entorno PDFEDITOR_TESSERACT y PDFEDITOR_SOFFICE."))
        hint.setObjectName("caption")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addSpacing(16)
        note = QLabel(_("Motor: MuPDF · Interfaz: Qt. Las exportaciones a Office y la edición no conservan necesariamente el diseño original. La firma manuscrita es visual; usa un certificado para firmar digitalmente. Consulta docs/FEATURES.md para conocer la cobertura y las limitaciones."))
        note.setObjectName("caption")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addSpacing(16)
        row = QHBoxLayout()
        row.addStretch()
        close = QPushButton(_("Cerrar"))
        close.setProperty("primary", True)
        close.clicked.connect(dialog.accept)
        row.addWidget(close)
        layout.addLayout(row)
        dialog.exec()

    # Inline side panels (Comentarios, Adjuntos, Enlaces) and the Atajos table.

    def side_panel(self, hint, buttons):
        panel = QWidget()
        column = QVBoxLayout(panel)
        column.setContentsMargins(6, 6, 6, 6)
        column.setSpacing(6)
        note = QLabel(hint)
        note.setWordWrap(True)
        note.setObjectName("PanelHint")
        listing = QListWidget()
        listing.setWordWrap(True)
        listing.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        column.addWidget(note)
        column.addWidget(listing, 1)
        row = QHBoxLayout()
        row.setSpacing(4)
        for label, handler in buttons:
            button = QPushButton(label)
            button.clicked.connect(lambda _=False, f=handler: self.run(f))
            row.addWidget(button)
        column.addLayout(row)
        return panel, listing

    def build_side_panels(self):
        """Tabs for the left panel beyond Páginas and Marcadores: (key, title, widget)."""
        comments = self.build_comments_panel()
        attachments, self.attachment_list = self.side_panel(
            _("Archivos incrustados en el PDF."),
            [(_("Añadir…"), self.side_attachment_add), (_("Extraer…"), self.side_attachment_extract), (_("Eliminar"), self.side_attachment_remove)])
        links, self.link_list = self.side_panel(
            _("Enlaces del documento. Doble clic para abrir el destino."),
            [(_("Abrir"), self.side_link_open), (_("Editar"), self.side_link_edit), (_("Eliminar"), self.side_link_remove)])
        fields, self.field_list = self.side_panel(_("Campos de formulario. Haz clic para ir al campo."), [])
        properties, self.property_list = self.side_panel(_("Propiedades del documento (solo lectura)."), [])
        self.property_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.link_list.itemDoubleClicked.connect(lambda _: self.run(self.side_link_open))
        self.field_list.itemClicked.connect(lambda _: self.side_field_go())
        self.layers_panel = LayersPanel()
        self.layers_panel.layerToggled.connect(self.toggle_layer)
        self.layers_panel.rememberChanged.connect(self.engine_remember_layers)
        self.side_entries = {"comments": [], "attachments": [], "links": [], "fields": [], "properties": []}
        self.side_panels = {"comments": comments, "attachments": attachments, "links": links, "fields": fields, "properties": properties, "layers": self.layers_panel}
        self.side_lists = {"comments": self.comment_list, "attachments": self.attachment_list, "links": self.link_list, "fields": self.field_list, "properties": self.property_list}
        self.side_signature = None
        self.side_timer = QTimer(self)
        self.side_timer.setInterval(700)
        self.side_timer.timeout.connect(self.refresh_side_panel)
        self.side_timer.start()
        return [("comments", _("Comentarios"), comments), ("attachments", _("Adjuntos"), attachments), ("links", _("Enlaces"), links),
                ("layers", _("Capas"), self.layers_panel), ("fields", _("Campos"), fields), ("properties", _("Propiedades"), properties)]

    def refresh_side_panel(self, force=False):
        """Fill the visible side tab; a cheap signature skips the work when the document did not change."""
        widget = self.left_tabs.currentWidget()
        key = next((name for name, panel in self.side_panels.items() if panel is widget), None)
        if key is None or not self.left_tabs.isVisible():
            return
        engine = self.engine
        alive = engine.doc is not None and not engine.doc.is_closed
        signature = (key, id(engine.doc), engine.page_count if alive else 0, len(engine._undo), len(engine._redo))
        if force is not True and signature == self.side_signature:
            return
        self.side_signature = signature
        if key == "layers":
            self.layers_panel.set_layers(engine.layers() if self.has_doc() else [], engine.layers_remembered)
            return
        previous = self.side_current(key) if key == "comments" else None
        listing = self.side_lists[key]
        entries = self.side_entries[key] = []
        listing.blockSignals(True)
        listing.clear()
        if self.has_doc():
            if key in ("comments", "fields", "properties"):
                {"comments": self.fill_comments, "fields": self.fill_fields, "properties": self.fill_properties}[key](listing, entries)
            elif key == "attachments":
                for entry in engine.attachments():
                    name = entry if isinstance(entry, str) else entry.get("name", entry.get("filename", ""))
                    entries.append(name)
                    listing.addItem(name)
            else:
                for page in range(engine.page_count):
                    for link in engine.links(page):
                        if link.get("kind") == fitz.LINK_URI:
                            destination = link.get("uri", "")
                        elif link.get("kind") == fitz.LINK_GOTO and link.get("page", -1) >= 0:
                            destination = _("Página {n}", n=link['page'] + 1)
                        else:
                            destination = _("Destino no editable")
                        entries.append((page, link))
                        listing.addItem(_("Página {n} → {destination}", n=page + 1, destination=destination))
        row = next((i for i, entry in enumerate(entries) if previous and entry[1] == previous[1]), 0)
        if entries and key != "properties":
            listing.setCurrentRow(row)
        elif key != "properties":
            labels = {"comments": _("Sin comentarios."), "attachments": _("Sin adjuntos."), "links": _("Sin enlaces."), "fields": _("Sin campos de formulario.")}
            placeholder = QListWidgetItem(labels[key])
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            listing.addItem(placeholder)
        listing.blockSignals(False)
        if key == "comments":
            if not self.author_edit.hasFocus():
                self.author_edit.setText(engine.author)
            self.comment_selected(listing.currentRow() if entries else -1)

    def side_current(self, key):
        row = self.side_lists[key].currentRow()
        entries = self.side_entries[key]
        return entries[row] if 0 <= row < len(entries) else None

    def side_comment_go(self):
        entry = self.side_current("comments")
        if entry:
            self.goto(entry[0])

    def side_comment_remove(self):
        entry = self.side_current("comments")
        if entry:
            self.engine.delete_annotation(*entry)
            self.refresh()
            self.refresh_side_panel(True)

    def side_attachment_add(self):
        path, _filter = QFileDialog.getOpenFileName(self, _("Adjuntar archivo"))
        if path:
            self.change(lambda: self.engine.attach(path))
            self.refresh_side_panel(True)

    def side_attachment_extract(self):
        name = self.side_current("attachments")
        if name:
            path, _filter = QFileDialog.getSaveFileName(self, _("Guardar adjunto"), Path(name).name)
            if path:
                self.engine.extract_attachment(name, path)

    def side_attachment_remove(self):
        name = self.side_current("attachments")
        if name:
            self.change(lambda: self.engine.remove_attachment(name))
            self.refresh_side_panel(True)

    def side_link_open(self):
        entry = self.side_current("links")
        if entry:
            self.open_link(entry[1])

    def side_link_edit(self):
        entry = self.side_current("links")
        if not entry:
            return
        page, link = entry
        if link.get("kind") not in (fitz.LINK_URI, fitz.LINK_GOTO):
            self.statusBar().showMessage(_("Este enlace se puede eliminar, pero su destino no admite edición."), 5000)
            return
        self.goto(page)
        self.edit_link(link=link)
        self.refresh_side_panel(True)

    def side_link_remove(self):
        entry = self.side_current("links")
        if entry:
            self.change(lambda: self.engine.delete_link(entry[0], entry[1]["xref"]))
            self.refresh_side_panel(True)

    def select_all(self):
        """Ctrl+A: text fields select their text, the thumbnails every page, otherwise the page text."""
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)):
            focus.selectAll()
        elif focus is not None and (focus is self.thumbnails or self.thumbnails.isAncestorOf(focus)):
            self.thumbnails.selectAll()
        elif self.has_doc() and self.view.editor is not None:
            cursor = self.view.editor.textCursor()
            cursor.select(QTextCursor.SelectionType.Document)
            self.view.editor.setTextCursor(cursor)
        elif self.has_doc():
            self.view.selection_anchor = 0
            self.view.update_text_selection(len(self.view.chars))

    def shortcut_rows(self):
        """(label, shortcut) for every action with a shortcut: window.actions, the view actions and the menus."""
        seen, rows = set(), []
        candidates = list(self.actions.values()) + list(getattr(self, "view_actions", {}).values())
        candidates += [action for menu in self.menuBar().findChildren(QMenu) for action in menu.actions()]
        for action in candidates:
            if id(action) in seen or action.isSeparator() or action.menu() is not None:
                continue
            seen.add(id(action))
            keys = [sequence.toString(QKeySequence.SequenceFormat.NativeText) for sequence in action.shortcuts() if not sequence.isEmpty()]
            if keys:
                rows.append((action.text().replace("&", "").rstrip("…"), " / ".join(keys)))
        return rows

    def build_shortcuts_dialog(self):
        dialog = QDialog(self)
        dialog.setObjectName("ShortcutsDialog")
        dialog.setWindowTitle(_("Atajos de teclado"))
        dialog.resize(460, 520)
        layout = QVBoxLayout(dialog)
        rows = self.shortcut_rows()
        table = QTableWidget(len(rows), 2)
        table.setObjectName("ShortcutsTable")
        table.setHorizontalHeaderLabels([_("Acción"), _("Atajo")])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for row, (label, keys) in enumerate(rows):
            table.setItem(row, 0, QTableWidgetItem(label))
            table.setItem(row, 1, QTableWidgetItem(keys))
        layout.addWidget(table)
        close = QPushButton(_("Cerrar"))
        close.clicked.connect(dialog.accept)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
        dialog.table = table
        return dialog

    def shortcuts_dialog(self):
        self.build_shortcuts_dialog().exec()
