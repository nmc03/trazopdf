"""Page-by-page raster comparison, with images loaded only for the current page."""
from pathlib import Path
import shutil

from .lang import _
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QListWidget, QSplitter, QScrollArea, QWidget, QFileDialog, QMessageBox)


class ComparisonDialog(QDialog):
    def __init__(self, report, folder, parent=None):
        super().__init__(parent)
        self.report = report
        self.folder = Path(folder)
        self.setWindowTitle(_("Comparación visual de PDFs"))
        self.resize(1280, 820)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        summary = QLabel(_("{changed} de {total} páginas con cambios · comparación por número de página", changed=len(report['changed_pages']), total=report['total_pages']))
        summary.setObjectName("brand")
        layout.addWidget(summary)
        description = QLabel(_("Compara la apariencia rasterizada; las diferencias se marcan en magenta. No verifica metadatos, enlaces, firmas ni contenido oculto."))
        description.setWordWrap(True)
        description.setObjectName("caption")
        layout.addWidget(description)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.zoom = QComboBox()
        self.zoom.addItems([_("Ajustar"), "50%", "75%", "100%", "150%", "200%"])
        self.zoom.currentIndexChanged.connect(self.render_current)
        row.addWidget(QLabel(_("Vista")))
        row.addWidget(self.zoom)
        next_change = QPushButton(_("Siguiente cambio"))
        next_change.clicked.connect(self.next_change)
        next_change.setEnabled(bool(report["changed_pages"]))
        row.addWidget(next_change)
        export = QPushButton(_("Exportar informe ZIP…"))
        export.clicked.connect(self.export_report)
        row.addWidget(export)
        row.addStretch()
        close = QPushButton(_("Cerrar"))
        close.clicked.connect(self.accept)
        row.addWidget(close)
        layout.addLayout(row)
        splitter = QSplitter()
        self.pages = QListWidget()
        self.pages.setObjectName("ComparisonPages")
        self.pages.setMaximumWidth(225)
        labels = {"equal": _("Sin cambios"), "changed": _("Modificada"), "added": _("Añadida"), "removed": _("Eliminada")}
        for page in report["pages"]:
            self.pages.addItem(f"{page['page']} · {labels.get(page['status'], page['status'])} ({page['changed_percent']:.2f}%)")
        self.pages.currentRowChanged.connect(self.render_current)
        splitter.addWidget(self.pages)
        self.panels = []
        for title in (_("Documento actual"), _("Otro documento"), _("Diferencias")):
            widget = QWidget()
            column = QVBoxLayout(widget)
            column.setContentsMargins(6, 0, 6, 0)
            heading = QLabel(title)
            heading.setObjectName("section")
            column.addWidget(heading)
            area = QScrollArea()
            area.setObjectName("ComparisonPanel")
            area.setAlignment(Qt.AlignmentFlag.AlignCenter)
            image = QLabel()
            image.setAlignment(Qt.AlignmentFlag.AlignCenter)
            area.setWidget(image)
            column.addWidget(area)
            splitter.addWidget(widget)
            self.panels.append((area, image))
        # At a fixed zoom, keep the corresponding regions aligned.
        for axis in ("horizontalScrollBar", "verticalScrollBar"):
            for area, _image in self.panels:
                bar = getattr(area, axis)()
                bar.valueChanged.connect(lambda value, source=bar, axis=axis: self.sync_scroll(source, axis, value))
        self._syncing = False
        self._pixmaps = []
        self._page_row = -1
        splitter.setSizes([200, 350, 350, 350])
        layout.addWidget(splitter, 1)
        self.pages.setCurrentRow(0)

    def sync_scroll(self, source, axis, value):
        if self._syncing:
            return
        self._syncing = True
        try:
            for area, _image in self.panels:
                bar = getattr(area, axis)()
                if bar is not source:
                    bar.setValue(value)
        finally:
            self._syncing = False

    def render_current(self, *_args):
        row = self.pages.currentRow()
        if row < 0:
            return
        if row != self._page_row:
            self._page_row = row
            page = self.report["pages"][row]
            self._pixmaps = []
            for key in ("left_image", "right_image", "diff_image"):
                name = page.get(key)
                self._pixmaps.append(QPixmap(str(self.folder / Path(name).name)) if name else QPixmap())
        for (area, label), pixmap in zip(self.panels, self._pixmaps):
            if pixmap.isNull():
                label.clear()
                label.setText(_("Página ausente"))
                label.adjustSize()
                continue
            if self.zoom.currentIndex() == 0:
                size = area.viewport().size() - QSize(8, 8)
                scaled = pixmap.scaled(size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            else:
                scale = float(self.zoom.currentText().rstrip("%")) / 100
                scaled = pixmap.scaledToWidth(max(1, round(pixmap.width() * scale)), Qt.TransformationMode.SmoothTransformation)
            label.setPixmap(scaled)
            label.resize(scaled.size())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "panels") and self.zoom.currentIndex() == 0:
            self.render_current()

    def next_change(self):
        changed = [i for i, page in enumerate(self.report["pages"]) if page["status"] != "equal"]
        if changed:
            row = next((i for i in changed if i > self.pages.currentRow()), changed[0])
            self.pages.setCurrentRow(row)

    def export_report(self):
        path, _filter = QFileDialog.getSaveFileName(self, _("Exportar comparación"), "Comparación.zip", _("Archivo ZIP (*.zip)"))
        if path:
            try:
                import tempfile
                with tempfile.TemporaryDirectory(prefix="pdf-editor-report-") as temporary:
                    archive = shutil.make_archive(str(Path(temporary) / "report"), "zip", self.folder)
                    from .engine import PDFEngine
                    PDFEngine._atomic_write(path, Path(archive).read_bytes())
            except Exception as error:
                QMessageBox.warning(self, _("No se pudo exportar"), str(error))
