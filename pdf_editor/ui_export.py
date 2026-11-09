from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QCursor, QFont, QPainter
from PySide6.QtPrintSupport import QPrintPreviewDialog, QPrinter
from PySide6.QtWidgets import QDialog, QFileDialog, QMenu, QMessageBox, QPushButton, QTextEdit, QVBoxLayout
from pathlib import Path

from . import doctools_dialogs
from .lang import _
from .toast import notify_file, notify_folder
from .ui_support import CANCELLED, pixmap_for

OFFICE_SUFFIXES = (".doc", ".docx", ".odt", ".xls", ".xlsx", ".ods", ".ppt", ".pptx", ".odp", ".rtf")
# action key -> (extension, engine method) for the Archivo > Exportar como entries that write one file.
EXPORT_METHODS = {
    "export_text": ("txt", "export_text"),
    "export_docx": ("docx", "export_docx"),
    "export_xlsx": ("xlsx", "export_xlsx"),
    "export_pptx": ("pptx", "export_pptx"),
}
EXPORT_KEYS = [*EXPORT_METHODS, "export_images"]
PRINT_MIN_DPI, PRINT_MAX_DPI = 150, 600


class UiExportMixin:
    """Export, import from images/office, batch, printing and text reports."""

    def export_menu(self):
        menu = QMenu(self)
        for key in EXPORT_KEYS:
            menu.addAction(self.actions[key])
        return menu

    def export(self):
        """Rail button: the Exportar como choices at the pointer."""
        menu = self.export_menu()
        menu.exec(QCursor.pos())
        menu.deleteLater()

    def export_as(self, key):
        extension, method = EXPORT_METHODS[key]
        if not self.confirm_unprotected_output(_("El archivo exportado")):
            return
        name = Path(self.engine.path).stem if self.engine.path else "Documento"
        path, _filter = QFileDialog.getSaveFileName(self, _("Exportar"), f"{name}.{extension}", f"{extension.upper()} (*.{extension})")
        if path and self.with_redaction_gate(lambda allow: self.busy(_("Exportando documento…"), lambda: getattr(self.engine, method)(path, allow_pending_redactions=allow)), _("Continuar de todos modos")) is not CANCELLED:
            self.statusBar().showMessage(_("Exportado: {path}", path=path))
            notify_file(self, _("Guardado en {name}", name=Path(path).name), path)

    def export_images(self):
        if not self.confirm_unprotected_output(_("Las imágenes exportadas")):
            return
        dialog = doctools_dialogs.ExportImagesDialog(self.engine.page_count, self.page + 1, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        options = dialog.values()
        directory = QFileDialog.getExistingDirectory(self, _("Guardar páginas como imágenes"))
        if not directory:
            return
        written = self.with_redaction_gate(lambda allow: self.busy(_("Exportando páginas…"), lambda: self.engine.export_images(directory, allow_pending_redactions=allow, **options)), _("Continuar de todos modos"))
        if written is not CANCELLED:
            self.statusBar().showMessage(_("{n} imágenes exportadas en: {directory}", n=len(written), directory=directory))
            notify_folder(self, _("{n} imágenes guardadas", n=len(written)), directory)

    def from_images(self):
        paths, _filter = QFileDialog.getOpenFileNames(self, _("Crear PDF desde imágenes"), "", _("Imágenes (*.png *.jpg *.jpeg *.tif *.tiff *.bmp)"))
        if paths:
            self.remember_view()
            with self.new_tab():
                self.engine.from_images(paths)
            self.refresh()
            QTimer.singleShot(0, self.fit_width)

    def from_office(self):
        path, _filter = QFileDialog.getOpenFileName(self, _("Convertir Office a PDF"), "", "Office (*.doc *.docx *.odt *.xls *.xlsx *.ods *.ppt *.pptx *.odp *.rtf)")
        if path and not path.lower().endswith(OFFICE_SUFFIXES):
            # A PDF here would replace the open document with an untitled copy: refuse before touching it.
            QMessageBox.warning(self, _("Convertir Office a PDF"), _("Elige un documento de Word, Excel, PowerPoint, OpenDocument o RTF. El documento abierto no se ha cambiado; para abrir un PDF usa Abrir."))
            return
        if path:
            data = self.external_job("office", _("Convirtiendo con LibreOffice"), path=path)
            if data is not None:
                self.remember_view()
                with self.new_tab():
                    self.engine.from_pdf_bytes(data)
                self.refresh()
                QTimer.singleShot(0, self.fit_width)

    def batch(self):
        """Procesar varios PDFs: recipes of steps applied to files or folders (see batch_dialog)."""
        from .batch_dialog import BatchDialog
        BatchDialog(self).exec()

    def print_document(self):
        self.show_print_preview(QPrinter(QPrinter.PrinterMode.HighResolution))

    def show_print_preview(self, printer):
        preview = QPrintPreviewDialog(printer, self)
        preview.setWindowTitle(_("Vista previa de impresión"))
        preview.paintRequested.connect(self.paint_pages)
        preview.exec()

    def paint_pages(self, printer):
        """Draw the pages (within the printer's range) fitted to each printed page, at the printer's resolution."""
        dpi = min(max(printer.resolution(), PRINT_MIN_DPI), PRINT_MAX_DPI)
        start = max(1, printer.fromPage()) - 1 if printer.fromPage() else 0
        end = min(self.engine.page_count, printer.toPage() or self.engine.page_count)
        painter = QPainter(printer)
        try:
            for index in range(start, end):
                if index > start:
                    printer.newPage()
                pix = pixmap_for(self.engine.render(index, dpi / 72))
                viewport = painter.viewport()
                size = pix.size()
                size.scale(viewport.size(), Qt.AspectRatioMode.KeepAspectRatio)
                painter.drawPixmap((viewport.width() - size.width()) // 2, (viewport.height() - size.height()) // 2, size.width(), size.height(), pix)
        finally:
            painter.end()

    def text_report(self, title, text):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(850, 650)
        layout = QVBoxLayout(dialog)
        editor = QTextEdit()
        editor.setReadOnly(True)
        editor.setFont(QFont("Consolas", 10))
        editor.setPlainText(str(text))
        layout.addWidget(editor)
        save = QPushButton(_("Guardar informe…"))
        def save_report():
            path, _filter = QFileDialog.getSaveFileName(dialog, _("Guardar informe"), "Informe.txt", _("Texto (*.txt)"))
            if path:
                Path(path).write_text(str(text), encoding="utf-8")
        save.clicked.connect(lambda: self.run(save_report))
        layout.addWidget(save)
        dialog.exec()
