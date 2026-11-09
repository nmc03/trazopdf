"""Dialog "Procesar varios PDFs": pick files, a recipe of steps, run it in a thread and watch the results."""
from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QListWidget, QMenu, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QHeaderView, QAbstractItemView,
)

from . import batch
from .lang import _, N_

NEW_RECIPE = N_("(receta nueva)")
STATUS_TEXT = {batch.OK: N_("Correcto"), batch.SKIPPED: N_("Omitido"), batch.ERROR: N_("Error"), batch.CANCELLED_STATUS: N_("Cancelado")}
CONFLICT_TEXT = {"renombrar": N_("Renombrar la salida"), "omitir": N_("Omitir el archivo"), "sobrescribir": N_("Sobrescribir la salida")}


class ParamsDialog(QDialog):
    """Edit the parameters of one step with widgets built from its parameter list."""

    def __init__(self, key, params, parent=None):
        super().__init__(parent)
        self.setWindowTitle(batch.step_label(key))
        self.key = key
        self.widgets = {}
        layout = QVBoxLayout(self)
        form = QFormLayout()
        spec = batch.STEPS[key].params
        if not spec:
            layout.addWidget(QLabel(_("Este paso no tiene parámetros.")))
        for param in spec:
            value = params.get(param.key, param.default)
            widget = self._widget(param, value)
            self.widgets[param.key] = widget
            form.addRow(_(param.label), getattr(widget, "row", widget))
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _widget(self, param, value):
        if param.kind == "bool":
            widget = QCheckBox()
            widget.setChecked(bool(value))
        elif param.kind == "int":
            widget = QSpinBox()
            widget.setRange(int(param.low if param.low is not None else -10**9), int(param.high if param.high is not None else 10**9))
            widget.setValue(int(value))
        elif param.kind == "float":
            widget = QDoubleSpinBox()
            widget.setRange(param.low if param.low is not None else -1e9, param.high if param.high is not None else 1e9)
            widget.setValue(float(value))
        elif param.kind == "lines":
            widget = QPlainTextEdit("\n".join(value))
            widget.setFixedHeight(64)
        elif param.kind == "choice":
            widget = QComboBox()
            for choice in param.choices:
                widget.addItem(str(choice), choice)
            widget.setCurrentIndex(max(0, widget.findData(value)))
        elif param.kind == "path":
            widget = QLineEdit(str(value))
            browse = QPushButton(_("Examinar…"))
            browse.clicked.connect(lambda: self._browse(widget))
            row = QWidget_with(widget, browse)
            widget.row = row
            return widget
        else:
            widget = QLineEdit(str(value))
        return widget

    def _browse(self, edit):
        path, _filter = QFileDialog.getOpenFileName(self, _("Certificado"), edit.text(), _("Certificados (*.p12 *.pfx)"))
        if path:
            edit.setText(path)

    def values(self):
        out = {}
        for param in batch.STEPS[self.key].params:
            widget = self.widgets[param.key]
            if param.kind == "bool":
                out[param.key] = widget.isChecked()
            elif param.kind in ("int", "float"):
                out[param.key] = widget.value()
            elif param.kind == "lines":
                out[param.key] = [line for line in widget.toPlainText().splitlines() if line.strip()]
            elif param.kind == "choice":
                out[param.key] = widget.currentData()
            else:
                out[param.key] = widget.text()
        return out


def QWidget_with(edit, button):
    """Replace a path edit by an edit + button row inside its form (done lazily by the parent form)."""
    from PySide6.QtWidgets import QWidget
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(edit)
    layout.addWidget(button)
    return row


class BatchThread(QThread):
    """Runs run_batch off the interface thread; results and progress arrive as signals."""
    progressed = Signal(int, int, str)
    resulted = Signal(object)
    finished_report = Signal(object)
    failed = Signal(str)

    def __init__(self, inputs, output, recipe, recursive, conflict, password, parent=None):
        super().__init__(parent)
        self.args = (inputs, output, recipe)
        self.options = dict(recursive=recursive, on_conflict=conflict, password=password)
        self.stop = threading.Event()

    def run(self):
        try:
            report = batch.run_batch(*self.args, **self.options, cancelled=self.stop.is_set,
                                     progress=lambda d, t, n: self.progressed.emit(d, t, n), on_result=self.resulted.emit)
            self.finished_report.emit(report)
        except Exception as error:
            self.failed.emit(str(error) or type(error).__name__)


class BatchDialog(QDialog):
    def __init__(self, parent=None, recipes_folder=None):
        super().__init__(parent)
        self.setObjectName("BatchDialog")
        self.setWindowTitle(_("Procesar varios PDFs"))
        self.resize(860, 760)
        self.recipes_folder = recipes_folder
        self.thread = None
        self.steps = []
        self.report = None
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(_("Archivos y carpetas a procesar (los originales no se modifican):")))
        self.inputs = QListWidget()
        self.inputs.setObjectName("inputs")
        self.inputs.setMaximumHeight(110)
        layout.addWidget(self.inputs)
        row = QHBoxLayout()
        add_files = QPushButton(_("Añadir archivos…"))
        add_files.clicked.connect(self.add_files)
        add_folder = QPushButton(_("Añadir carpeta…"))
        add_folder.clicked.connect(self.add_folder)
        remove = QPushButton(_("Quitar"))
        remove.clicked.connect(lambda: [self.inputs.takeItem(self.inputs.row(i)) for i in self.inputs.selectedItems()])
        self.recursive = QCheckBox(_("Incluir subcarpetas"))
        for widget in (add_files, add_folder, remove, self.recursive):
            row.addWidget(widget)
        row.addStretch()
        layout.addLayout(row)

        form = QFormLayout()
        out_row = QHBoxLayout()
        self.output = QLineEdit()
        self.output.setObjectName("output")
        browse = QPushButton(_("Examinar…"))
        browse.clicked.connect(self.choose_output)
        out_row.addWidget(self.output)
        out_row.addWidget(browse)
        form.addRow(_("Carpeta de salida"), out_row)
        self.conflict = QComboBox()
        for key in batch.CONFLICT_MODES:
            self.conflict.addItem(_(CONFLICT_TEXT[key]), key)
        form.addRow(_("Si el archivo de salida ya existe"), self.conflict)
        recipe_row = QHBoxLayout()
        self.recipe_combo = QComboBox()
        self.recipe_combo.setObjectName("recipes")
        self.recipe_combo.currentIndexChanged.connect(self.load_selected)
        recipe_row.addWidget(self.recipe_combo, 1)
        for text, handler in ((_("Guardar receta…"), self.save_recipe), (_("Importar…"), self.import_recipe), (_("Exportar…"), self.export_recipe)):
            button = QPushButton(text)
            button.clicked.connect(handler)
            recipe_row.addWidget(button)
        form.addRow(_("Receta"), recipe_row)
        layout.addLayout(form)

        steps_row = QHBoxLayout()
        self.steps_list = QListWidget()
        self.steps_list.setObjectName("steps")
        self.steps_list.itemDoubleClicked.connect(lambda _item: self.edit_step())
        steps_row.addWidget(self.steps_list, 1)
        buttons = QVBoxLayout()
        self.add_button = QPushButton(_("Añadir paso"))
        menu = QMenu(self.add_button)
        for key in batch.STEPS:
            menu.addAction(batch.step_label(key), lambda key=key: self.add_step(key))
        self.add_button.setMenu(menu)
        buttons.addWidget(self.add_button)
        for text, handler in ((_("Parámetros…"), self.edit_step), (_("Quitar paso"), self.remove_step), (_("Subir"), lambda: self.move_step(-1)), (_("Bajar"), lambda: self.move_step(1))):
            button = QPushButton(text)
            button.clicked.connect(handler)
            buttons.addWidget(button)
        buttons.addStretch()
        steps_row.addLayout(buttons)
        layout.addLayout(steps_row)

        self.progress = QProgressBar()
        self.progress.setObjectName("progress")
        layout.addWidget(self.progress)
        self.table = QTableWidget(0, 3)
        self.table.setObjectName("results")
        self.table.setHorizontalHeaderLabels([_("Archivo"), _("Estado"), _("Resultado")])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table, 1)
        self.summary = QLabel("")
        layout.addWidget(self.summary)
        bottom = QHBoxLayout()
        bottom.addStretch()
        self.run_button = QPushButton(_("Procesar"))
        self.run_button.setObjectName("run")
        self.run_button.clicked.connect(self.start)
        self.cancel_button = QPushButton(_("Cancelar"))
        self.cancel_button.setObjectName("cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel)
        self.close_button = QPushButton(_("Cerrar"))
        self.close_button.clicked.connect(self.close)
        for widget in (self.run_button, self.cancel_button, self.close_button):
            bottom.addWidget(widget)
        layout.addLayout(bottom)
        self.reload_recipes()

    # ------------------------------------------------------------ inputs
    def add_files(self):
        paths, _filter = QFileDialog.getOpenFileNames(self, _("Seleccionar PDFs para procesar"), "", "PDF (*.pdf)")
        self.add_inputs(paths)

    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, _("Carpeta con PDFs"))
        if folder:
            self.add_inputs([folder])

    def add_inputs(self, paths):
        have = {self.inputs.item(i).text() for i in range(self.inputs.count())}
        for path in paths:
            if path not in have:
                self.inputs.addItem(path)

    def choose_output(self):
        folder = QFileDialog.getExistingDirectory(self, _("Carpeta de salida"))
        if folder:
            self.output.setText(folder)

    # ------------------------------------------------------------ recipes
    def reload_recipes(self, select=None):
        self.recipe_combo.blockSignals(True)
        self.recipe_combo.clear()
        self.recipe_combo.addItem(_(NEW_RECIPE), None)
        for recipe in batch.builtin_recipes():
            self.recipe_combo.addItem(_(recipe["name"]), recipe)
        for _path, recipe in batch.list_user_recipes(self.recipes_folder):
            self.recipe_combo.addItem(recipe["name"], recipe)
        index = 0
        if select:
            index = max(0, next((i for i in range(self.recipe_combo.count()) if (self.recipe_combo.itemData(i) or {}).get("name") == select), 0))
        self.recipe_combo.setCurrentIndex(index)
        self.recipe_combo.blockSignals(False)
        self.load_selected()

    def load_selected(self):
        recipe = self.recipe_combo.currentData()
        self.steps = [{"step": s["step"], "params": dict(s["params"])} for s in recipe["steps"]] if recipe else []
        self.refresh_steps()

    def refresh_steps(self, select=None):
        self.steps_list.clear()
        for index, item in enumerate(self.steps):
            self.steps_list.addItem(f"{index + 1}. {batch.step_label(item['step'])}")
        if select is not None and self.steps:
            self.steps_list.setCurrentRow(min(max(select, 0), len(self.steps) - 1))

    def current_name(self):
        data = self.recipe_combo.currentData()
        return data["name"] if data else ""

    def current_recipe(self, name=None):
        return batch.make_recipe(name if name is not None else self.current_name(), self.steps)

    def warn(self, error):
        QMessageBox.warning(self, _("Procesar varios PDFs"), str(error))

    def add_step(self, key):
        self.steps.append(batch.new_step(key))
        self.refresh_steps(len(self.steps) - 1)
        if batch.STEPS[key].params:
            self.edit_step()

    def edit_step(self):
        row = self.steps_list.currentRow()
        if row < 0:
            return
        item = self.steps[row]
        dialog = ParamsDialog(item["step"], item["params"], self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            item["params"] = dialog.values()

    def remove_step(self):
        row = self.steps_list.currentRow()
        if row >= 0:
            del self.steps[row]
            self.refresh_steps(row)

    def move_step(self, delta):
        row = self.steps_list.currentRow()
        target = row + delta
        if row >= 0 and 0 <= target < len(self.steps):
            self.steps[row], self.steps[target] = self.steps[target], self.steps[row]
            self.refresh_steps(target)

    def save_recipe(self):
        name, ok = QInputDialog.getText(self, _("Guardar receta"), _("Nombre de la receta:"), text=self.current_name())
        if not ok or not name.strip():
            return
        try:
            batch.save_user_recipe(self.current_recipe(name.strip()), self.recipes_folder)
        except (ValueError, OSError) as error:
            self.warn(error)
            return
        self.reload_recipes(select=name.strip())

    def import_recipe(self):
        path, _filter = QFileDialog.getOpenFileName(self, _("Importar receta"), "", _("Receta (*.json)"))
        if not path:
            return
        try:
            recipe = batch.load_recipe(path)
            batch.save_user_recipe(recipe, self.recipes_folder)
        except (ValueError, OSError) as error:
            self.warn(error)
            return
        self.reload_recipes(select=recipe["name"])

    def export_recipe(self):
        path, _filter = QFileDialog.getSaveFileName(self, _("Exportar receta"), (self.current_name() or "receta") + ".json", _("Receta (*.json)"))
        if not path:
            return
        try:
            batch.save_recipe(self.current_recipe(), path)
        except (ValueError, OSError) as error:
            self.warn(error)

    # ------------------------------------------------------------- running
    def set_running(self, running):
        for widget in (self.run_button, self.add_button, self.inputs, self.steps_list, self.recipe_combo, self.output, self.conflict, self.recursive):
            widget.setEnabled(not running)
        self.cancel_button.setEnabled(running)

    def start(self):
        if self.thread is not None:
            return
        inputs = [self.inputs.item(i).text() for i in range(self.inputs.count())]
        if not inputs:
            self.warn(_("Añade al menos un archivo o una carpeta."))
            return
        if not self.output.text().strip():
            self.warn(_("Elige la carpeta de salida."))
            return
        try:
            recipe = self.current_recipe()
        except ValueError as error:
            self.warn(error)
            return
        password = None
        if batch.needs_password(recipe):
            password, ok = QInputDialog.getText(self, _("Contraseña del certificado"), _("Contraseña (no se guarda en la receta):"), QLineEdit.EchoMode.Password)
            if not ok:
                return
        self.table.setRowCount(0)
        self.summary.setText("")
        self.progress.setRange(0, 0)
        self.report = None
        thread = BatchThread(inputs, self.output.text().strip(), recipe, self.recursive.isChecked(), self.conflict.currentData(), password, self)
        thread.progressed.connect(self.on_progress)
        thread.resulted.connect(self.on_result)
        thread.finished_report.connect(self.on_finished)
        thread.failed.connect(self.on_failed)
        thread.finished.connect(self.on_thread_done)
        self.thread = thread
        self.set_running(True)
        thread.start()

    def on_progress(self, done, total, name):
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(done)

    def on_result(self, result):
        row = self.table.rowCount()
        self.table.insertRow(row)
        detail = result.message or (Path(result.output).name if result.output else "")
        for column, text in enumerate((Path(result.source).name, _(STATUS_TEXT[result.status]), detail)):
            self.table.setItem(row, column, QTableWidgetItem(text))

    def on_finished(self, report):
        self.report = report
        self.summary.setText(report.to_text().splitlines()[-1])
        try:
            batch.write_report(report, self.output.text().strip())
        except OSError:
            pass

    def on_failed(self, message):
        self.warn(message)

    def on_thread_done(self):
        thread, self.thread = self.thread, None
        if thread is not None:
            thread.deleteLater()
        self.progress.setRange(0, 1)
        self.progress.setValue(1 if self.report and not self.report.cancelled else 0)
        self.set_running(False)

    def cancel(self):
        if self.thread is not None:
            self.thread.stop.set()
            self.cancel_button.setEnabled(False)
            self.summary.setText(_("Cancelando…"))

    def done(self, result):
        if self.thread is not None:
            self.thread.stop.set()
            self.thread.wait(30000)
        super().done(result)
