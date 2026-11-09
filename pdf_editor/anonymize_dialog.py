"""Dialog for the "Anonimizar documento" assistant: detect, review, anonymise, verify, save the report."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPlainTextEdit, QPushButton, QWidget,
)

from . import anonymize
from .doctools_dialogs import _ToolDialog, _caption, _section
from .lang import _, N_


class AnonymizeDialog(_ToolDialog):
    """Works on a file on disk (``source``) and writes a new copy; never modifies the open document."""
    ACCEPT_TEXT = N_("Anonimizar")

    def __init__(self, source, parent=None):
        super().__init__(_("Anonimizar documento"), "AnonymizeDialog", parent, 680)
        self.source = Path(source)
        self.matches = []
        self.report = None
        self.body.addWidget(_caption(_("Todo se hace en este equipo. Se crea una copia nueva: el original no se modifica.")))
        self.body.addWidget(_section(_("QUÉ BUSCAR")))
        row = QWidget()
        grid = QHBoxLayout(row)
        grid.setContentsMargins(0, 0, 0, 0)
        from PySide6.QtWidgets import QVBoxLayout
        cols = [QVBoxLayout(), QVBoxLayout()]
        self.pattern_checks = {}
        for i, (key, label) in enumerate(anonymize.pattern_choices()):
            check = QCheckBox(label)
            check.setObjectName(f"pattern_{key}")
            check.setChecked(True)
            self.pattern_checks[key] = check
            cols[i % 2].addWidget(check)
        for col in cols:
            grid.addLayout(col)
        self.body.addWidget(row)
        form = QFormLayout()
        self.terms = QPlainTextEdit()
        self.terms.setPlaceholderText(_("Un término por línea (nombres, direcciones, referencias…)"))
        self.terms.setFixedHeight(56)
        self.regexes = QPlainTextEdit()
        self.regexes.setPlaceholderText(_("Una expresión regular por línea"))
        self.regexes.setFixedHeight(40)
        self.case = QCheckBox(_("Distinguir mayúsculas y minúsculas"))
        self.word = QCheckBox(_("Solo palabras completas"))
        form.addRow(_("Términos"), self.terms)
        form.addRow(_("Expresiones"), self.regexes)
        form.addRow("", self.case)
        form.addRow("", self.word)
        self.body.addLayout(form)
        buttons = QHBoxLayout()
        self.search_button = QPushButton(_("Buscar coincidencias"))
        self.search_button.clicked.connect(self.search)
        self.select_all = QPushButton(_("Marcar todo"))
        self.select_none = QPushButton(_("Desmarcar todo"))
        self.select_all.clicked.connect(lambda: self.set_all_checked(True))
        self.select_none.clicked.connect(lambda: self.set_all_checked(False))
        buttons.addWidget(self.search_button)
        buttons.addStretch()
        buttons.addWidget(self.select_all)
        buttons.addWidget(self.select_none)
        self.body.addLayout(buttons)
        self.results = QListWidget()
        self.results.setMinimumHeight(150)
        self.results.itemChanged.connect(lambda _i: self._update_state())
        self.body.addWidget(self.results)
        self.summary = _caption(_("Pulsa Buscar coincidencias para revisarlas. También se eliminarán metadatos, adjuntos, scripts, marcadores y anotaciones que citen los datos."))
        self.body.addWidget(self.summary)
        out_row = QHBoxLayout()
        self.output = QLineEdit(str(self.source.with_name(self.source.stem + "-anonimizado.pdf")))
        self.output.setAccessibleName(_("Archivo de salida"))
        browse = QPushButton(_("Examinar…"))
        browse.clicked.connect(self.browse)
        out_row.addWidget(QLabel(_("Guardar copia en")))
        out_row.addWidget(self.output, 1)
        out_row.addWidget(browse)
        self.body.addLayout(out_row)
        self.report_view = QPlainTextEdit()
        self.report_view.setReadOnly(True)
        self.report_view.setMinimumHeight(140)
        self.report_view.hide()
        self.body.addWidget(self.report_view)
        self.save_report_button = QPushButton(_("Guardar informe…"))
        self.save_report_button.clicked.connect(self.save_report)
        self.save_report_button.hide()
        self.body.addWidget(self.save_report_button)
        self._finish_layout()
        self.ok_button.setEnabled(False)
        self.ok_button.clicked.disconnect()
        self.ok_button.clicked.connect(self.run_anonymize)

    # ---- rules
    def rules(self, exclude=()):
        lines = lambda edit: tuple(t.strip() for t in edit.toPlainText().splitlines() if t.strip())
        return anonymize.Rules(
            patterns=tuple(k for k, c in self.pattern_checks.items() if c.isChecked()),
            terms=lines(self.terms), regexes=lines(self.regexes), case_sensitive=self.case.isChecked(),
            whole_word=self.word.isChecked(), exclude=frozenset(exclude))

    def excluded_ids(self):
        return [m["id"] for i, m in enumerate(self.matches) if self.results.item(i).checkState() != Qt.Checked]

    def search(self):
        self.set_error("")
        self.results.clear()
        self.matches = []
        try:
            self.matches = anonymize.preview(self.source, self.rules())
        except ValueError as exc:
            self.set_error(str(exc))
        self.results.blockSignals(True)
        for match in self.matches:
            item = QListWidgetItem(_("Pág. {page} · {label} · {found}", page=match["page"] + 1, label=match["label"], found=match["text"]))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.results.addItem(item)
        self.results.blockSignals(False)
        self._update_state()

    def set_all_checked(self, checked):
        for i in range(self.results.count()):
            self.results.item(i).setCheckState(Qt.Checked if checked else Qt.Unchecked)

    def _update_state(self):
        chosen = len(self.matches) - len(self.excluded_ids())
        self.summary.setText(_("{chosen} de {total} coincidencias en el texto seleccionadas. Las que aparezcan en metadatos, adjuntos o anotaciones se eliminan siempre.", chosen=chosen, total=len(self.matches)))
        self.ok_button.setEnabled(bool(self.matches) or bool(self.terms.toPlainText().strip() or self.regexes.toPlainText().strip()))

    def browse(self):
        path, _filter = QFileDialog.getSaveFileName(self, _("Guardar copia anonimizada"), self.output.text(), "PDF (*.pdf)")
        if path:
            self.output.setText(path if path.lower().endswith(".pdf") else path + ".pdf")

    # ---- run
    def run_anonymize(self):
        self.set_error("")
        try:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                self.report = anonymize.anonymize(self.source, self.output.text().strip(), self.rules(self.excluded_ids()))
            finally:
                QApplication.restoreOverrideCursor()
        except (ValueError, OSError) as exc:
            self.set_error(str(exc))
            return
        self.report_view.setPlainText(self.report.to_text())
        self.report_view.show()
        self.save_report_button.show()
        self.ok_button.setEnabled(False)
        if not self.report.ok:
            self.set_error(_("La verificación ha fallado: no se ha guardado ningún archivo."))
        else:
            self.summary.setText(_("Copia anonimizada y verificada guardada en {path}", path=self.report.output))
        self.cancel_button.setText(_("Cerrar"))

    def save_report(self):
        if self.report is None:
            return
        path, _filter = QFileDialog.getSaveFileName(self, _("Guardar informe"), str(self.source.with_name("informe-anonimizacion.txt")), _("Texto (*.txt);;JSON (*.json)"))
        if path:
            try:
                anonymize.write_report(self.report, path)
            except OSError as exc:
                self.set_error(str(exc))

    def values(self):
        return {"report": self.report}
