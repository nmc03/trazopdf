"""Accessibility dialog: result list with per-row fix button and text export."""
from pathlib import Path

from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from . import accessibility as acc
from .lang import _
from .toast import notify


class AccessibilityDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.owner = window
        self.setWindowTitle(_("Accesibilidad"))
        self.resize(720, 400)
        layout = QVBoxLayout(self)
        self.summary = QLabel()
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([_("Estado"), _("Elemento"), _("Detalle"), ""])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.language = QComboBox()
        for code, name in acc.LANGUAGES:
            self.language.addItem(f"{name} ({code})", code)
        row.addWidget(QLabel(_("Idioma al corregir:")))
        row.addWidget(self.language)
        row.addStretch()
        export = QPushButton(_("Exportar informe…"))
        export.clicked.connect(self.export_report)
        close = QPushButton(_("Cerrar"))
        close.clicked.connect(self.accept)
        row.addWidget(export)
        row.addWidget(close)
        layout.addLayout(row)
        self.refresh()

    def refresh(self):
        self.results = acc.check(self.owner.engine.doc)
        self.table.setRowCount(len(self.results))
        for index, result in enumerate(self.results):
            for column, text in enumerate((_(acc.STATUS_TEXT[result["status"]]), _(result["label"]), _(result["detail"]))):
                self.table.setItem(index, column, QTableWidgetItem(text))
            if result["fix"]:
                button = QPushButton(_("Corregir"))
                button.clicked.connect(lambda checked=False, kind=result["fix"]: self.fix(kind))
                self.table.setCellWidget(index, 3, button)
            else:
                self.table.removeCellWidget(index, 3)
        errors = acc.error_count(self.results)
        self.summary.setText(_("Sin errores de accesibilidad.") if not errors else _("{errors} error(es) por corregir.", errors=errors))
        self.table.resizeRowsToContents()

    def fix(self, kind):
        engine = self.owner.engine
        if kind == "title":
            self.owner.change(lambda: acc.fix_title(engine))
        else:
            self.owner.change(lambda: acc.fix_language(engine, self.language.currentData()))
        self.refresh()

    def export_report(self):
        path, _filter = QFileDialog.getSaveFileName(self, _("Exportar informe"), "informe-accesibilidad.txt", _("Texto (*.txt)"))
        if path:
            engine = self.owner.engine
            Path(path).write_text(acc.report_text(self.results, Path(engine.path).name if engine.path else ""), encoding="utf-8")
            notify(self.owner, _("Informe guardado."))


def open_accessibility(window):
    dialog = AccessibilityDialog(window)
    dialog.setModal(False)
    dialog.show()
    window.accessibility_dialog = dialog
    return dialog
