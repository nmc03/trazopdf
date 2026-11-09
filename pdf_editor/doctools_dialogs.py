"""Qt dialogs for the document tools in :mod:`pdf_editor.doctools`.

Every dialog only collects parameters: ``dialog.values()`` returns a dict whose keys
match the keyword arguments of the corresponding doctools function, so the caller can
run ``doctools.fn(doc, **dialog.values())`` (exceptions: see each class). Dialogs never
modify the document. Styling hooks follow theme.py (``primary`` property on the accept
button, ``section`` / ``caption`` label object names).
"""
from __future__ import annotations

import pymupdf as fitz
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QRadioButton, QSlider, QSpinBox,
    QTableWidget, QVBoxLayout, QWidget, QGroupBox, QTreeWidget, QTreeWidgetItem, QHeaderView,
)

from . import doctools
from .lang import _, N_

IMAGE_FILTER = N_("Imágenes (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp);;Todos los archivos (*)")


def _section(text):
    label = QLabel(text)
    label.setObjectName("section")
    return label


def _caption(text=""):
    label = QLabel(text)
    label.setObjectName("caption")
    label.setWordWrap(True)
    return label


class ColorButton(QPushButton):
    """Button showing the chosen colour; ``rgb()`` returns floats in 0..1."""
    changed = Signal()

    def __init__(self, rgb=(0.0, 0.0, 0.0), parent=None):
        super().__init__(parent)
        self._color = QColor()
        self.set_rgb(rgb)
        self.clicked.connect(self._pick)
        self.setToolTip(_("Elegir color"))

    def set_rgb(self, rgb):
        self._color = QColor.fromRgbF(*[max(0.0, min(1.0, float(v))) for v in rgb])
        self.setText(self._color.name().upper())
        fg = "#FFFFFF" if self._color.lightness() < 128 else "#000000"
        self.setStyleSheet(f"QPushButton {{ background: {self._color.name()}; color: {fg}; }}")
        self.changed.emit()

    def rgb(self):
        return (round(self._color.redF(), 4), round(self._color.greenF(), 4), round(self._color.blueF(), 4))

    def _pick(self):
        chosen = QColorDialog.getColor(self._color, self, _("Elegir color"))
        if chosen.isValid():
            self.set_rgb((chosen.redF(), chosen.greenF(), chosen.blueF()))


class _ToolDialog(QDialog):
    """Common frame: title, content layout, error line and Cancelar / Aceptar buttons."""
    ACCEPT_TEXT = N_("Aceptar")

    def __init__(self, title, object_name, parent=None, width=480):
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(width)
        self.body = QVBoxLayout(self)
        self.error = QLabel("")
        self.error.setObjectName("caption")
        self.error.setProperty("state", "error")
        self.error.setWordWrap(True)
        self.error.hide()
        self.cancel_button = QPushButton(_("Cancelar"))
        self.cancel_button.clicked.connect(self.reject)
        self.ok_button = QPushButton(_(self.ACCEPT_TEXT))
        self.ok_button.setProperty("primary", True)
        self.ok_button.setDefault(True)
        self.ok_button.clicked.connect(self.accept)
        self._buttons_row = QHBoxLayout()

    def _finish_layout(self):
        self.body.addWidget(self.error)
        self._buttons_row.addStretch()
        self._buttons_row.addWidget(self.cancel_button)
        self._buttons_row.addWidget(self.ok_button)
        self.body.addLayout(self._buttons_row)

    def validate(self):
        """Return a Spanish error message, or None when the fields are valid."""
        return None

    def set_error(self, message):
        self.error.setText(message or "")
        self.error.setVisible(bool(message))

    def accept(self):
        message = self.validate()
        self.set_error(message)
        if message:
            return
        super().accept()

    def values(self):
        raise NotImplementedError


def _pages_edit(page_count):
    edit = QLineEdit()
    edit.setPlaceholderText(_("Todas (1-{page_count}). Ejemplo: 1-3, 5, 8-", page_count=page_count))
    return edit


def _pages_value(edit, page_count):
    """None for 'all pages', else a list of zero based indices. Raises ValueError."""
    text = edit.text().strip()
    return doctools.parse_page_range(text, page_count) if text else None


# ----------------------------------------------------- headers and footers

class HeaderFooterDialog(_ToolDialog):
    """values(): header, footer (3-tuples), fontsize, color, margin_top, margin_bottom,
    margin_side, pages (list|None), filename  -> doctools.add_header_footer(doc, **values)."""

    def __init__(self, page_count=1, filename="", parent=None, date=None):
        super().__init__(_("Encabezado y pie de página"), "HeaderFooterDialog", parent, 560)
        self.page_count, self.filename, self.date = max(1, page_count), filename, date
        self.header = [QLineEdit() for _i in range(3)]
        self.footer = [QLineEdit() for _i in range(3)]
        grid = QFormLayout()
        self.body.addWidget(_section(_("ENCABEZADO")))
        for label, edit in zip((N_("Izquierda"), N_("Centro"), N_("Derecha")), self.header):
            grid.addRow(_(label), edit)
        self.body.addLayout(grid)
        grid2 = QFormLayout()
        self.body.addWidget(_section(_("PIE DE PÁGINA")))
        for label, edit in zip((N_("Izquierda"), N_("Centro"), N_("Derecha")), self.footer):
            grid2.addRow(_(label), edit)
        self.body.addLayout(grid2)
        self.body.addWidget(_caption(_("Variables: {page} página actual, {pages} total, {date} fecha, {filename} nombre del archivo.")))
        self.body.addWidget(_section(_("VISTA PREVIA (PÁGINA 1)")))
        self.preview = QLabel()
        self.preview.setObjectName("HeaderFooterPreview")
        self.preview.setTextFormat(Qt.PlainText)
        self.preview.setWordWrap(True)
        self.body.addWidget(self.preview)
        options = QFormLayout()
        self.fontsize = QDoubleSpinBox()
        self.fontsize.setRange(4, 144)
        self.fontsize.setValue(10)
        self.fontsize.setSuffix(" pt")
        self.color = ColorButton((0, 0, 0))
        self.margin_top = self._margin(36)
        self.margin_bottom = self._margin(36)
        self.margin_side = self._margin(36)
        self.pages = _pages_edit(self.page_count)
        options.addRow(_("Tamaño de letra"), self.fontsize)
        options.addRow(_("Color"), self.color)
        options.addRow(_("Margen superior"), self.margin_top)
        options.addRow(_("Margen inferior"), self.margin_bottom)
        options.addRow(_("Margen lateral"), self.margin_side)
        options.addRow(_("Páginas"), self.pages)
        self.body.addLayout(options)
        for edit in self.header + self.footer + [self.pages]:
            edit.textChanged.connect(self.update_preview)
        self._finish_layout()
        self.update_preview()

    @staticmethod
    def _margin(value):
        spin = QDoubleSpinBox()
        spin.setRange(0, 400)
        spin.setValue(value)
        spin.setSuffix(" pt")
        return spin

    def _texts(self, edits):
        return tuple(e.text() for e in edits)

    def preview_text(self, page=0):
        """Plain-text rendering of the three header and footer cells for ``page`` (zero based)."""
        def line(edits):
            cells = [doctools.expand_tokens(e.text(), page, self.page_count, self.filename, self.date) for e in edits]
            return "  |  ".join(c if c else "·" for c in cells)
        return _("Encabezado:  {header}\nPie:  {footer}", header=line(self.header), footer=line(self.footer))

    def update_preview(self):
        self.preview.setText(self.preview_text(0))

    def validate(self):
        if not any(self._texts(self.header)) and not any(self._texts(self.footer)):
            return _("Escribe al menos un texto de encabezado o de pie.")
        try:
            _pages_value(self.pages, self.page_count)
        except ValueError as exc:
            return str(exc)
        return None

    def values(self):
        return {
            "header": self._texts(self.header), "footer": self._texts(self.footer),
            "fontsize": self.fontsize.value(), "color": self.color.rgb(),
            "margin_top": self.margin_top.value(), "margin_bottom": self.margin_bottom.value(),
            "margin_side": self.margin_side.value(), "pages": _pages_value(self.pages, self.page_count),
            "filename": self.filename,
        }


# ------------------------------------------------------------------ Bates

class BatesDialog(_ToolDialog):
    """values(): prefix, suffix, start, digits, position, fontsize, color, margin, pages
    -> doctools.add_bates(doc, **values)."""
    POSITIONS = [(N_("Abajo a la derecha"), "bottom-right"), (N_("Abajo en el centro"), "bottom-center"),
                 (N_("Abajo a la izquierda"), "bottom-left"), (N_("Arriba a la derecha"), "top-right"),
                 (N_("Arriba en el centro"), "top-center"), (N_("Arriba a la izquierda"), "top-left")]

    def __init__(self, page_count=1, parent=None):
        super().__init__(_("Numeración Bates"), "BatesDialog", parent)
        self.page_count = max(1, page_count)
        form = QFormLayout()
        self.prefix, self.suffix = QLineEdit(), QLineEdit()
        self.start = QSpinBox()
        self.start.setRange(0, 999999999)
        self.start.setValue(1)
        self.digits = QSpinBox()
        self.digits.setRange(1, 12)
        self.digits.setValue(6)
        self.position = QComboBox()
        for label, key in self.POSITIONS:
            self.position.addItem(_(label), key)
        self.fontsize = QDoubleSpinBox()
        self.fontsize.setRange(4, 144)
        self.fontsize.setValue(10)
        self.fontsize.setSuffix(" pt")
        self.color = ColorButton((0, 0, 0))
        self.margin = QDoubleSpinBox()
        self.margin.setRange(0, 400)
        self.margin.setValue(36)
        self.margin.setSuffix(" pt")
        self.pages = _pages_edit(self.page_count)
        for label, widget in ((_("Prefijo"), self.prefix), (_("Sufijo"), self.suffix), (_("Número inicial"), self.start),
                              (_("Dígitos"), self.digits), (_("Posición"), self.position), (_("Tamaño de letra"), self.fontsize),
                              (_("Color"), self.color), (_("Margen"), self.margin), (_("Páginas"), self.pages)):
            form.addRow(label, widget)
        self.body.addLayout(form)
        self.body.addWidget(_section(_("VISTA PREVIA")))
        self.preview = QLabel()
        self.preview.setObjectName("BatesPreview")
        self.preview.setTextFormat(Qt.PlainText)
        self.body.addWidget(self.preview)
        for w in (self.prefix, self.suffix, self.pages):
            w.textChanged.connect(self.update_preview)
        for w in (self.start, self.digits):
            w.valueChanged.connect(self.update_preview)
        self._finish_layout()
        self.update_preview()

    def update_preview(self, *_args):
        try:
            count = len(_pages_value(self.pages, self.page_count) or range(self.page_count))
        except ValueError:
            count = self.page_count
        first = doctools.bates_label(self.start.value(), self.prefix.text(), self.suffix.text(), self.digits.value())
        last = doctools.bates_label(self.start.value() + count - 1, self.prefix.text(), self.suffix.text(), self.digits.value())
        self.preview.setText(_("{first}  …  {last}  ({count} páginas)", first=first, last=last, count=count))

    def validate(self):
        try:
            _pages_value(self.pages, self.page_count)
        except ValueError as exc:
            return str(exc)
        return None

    def values(self):
        return {"prefix": self.prefix.text(), "suffix": self.suffix.text(), "start": self.start.value(),
                "digits": self.digits.value(), "position": self.position.currentData(),
                "fontsize": self.fontsize.value(), "color": self.color.rgb(), "margin": self.margin.value(),
                "pages": _pages_value(self.pages, self.page_count)}


# -------------------------------------------------------- search & redact

class RedactSearchDialog(_ToolDialog):
    """Search sensitive data and pick matches. Reads (never modifies) ``doc`` to search.

    values(): matches (checked ones, as returned by doctools.find_matches), fill (rgb),
    patterns, custom, custom_is_regex, case_sensitive, whole_word
    -> doctools.add_redactions(doc, values["matches"], fill=values["fill"]).
    """
    ACCEPT_TEXT = N_("Marcar para censurar")

    def __init__(self, doc=None, parent=None):
        super().__init__(_("Buscar y censurar información sensible"), "RedactSearchDialog", parent, 640)
        self.doc = doc
        self.matches = []
        self.body.addWidget(_section(_("PATRONES")))
        self.pattern_checks = {}
        row = QWidget()
        grid = QHBoxLayout(row)
        grid.setContentsMargins(0, 0, 0, 0)
        cols = [QVBoxLayout(), QVBoxLayout()]
        for i, (key, label) in enumerate(doctools.pattern_choices()):
            check = QCheckBox(_(label))
            check.setObjectName(f"pattern_{key}")
            self.pattern_checks[key] = check
            cols[i % 2].addWidget(check)
        for col in cols:
            grid.addLayout(col)
        self.body.addWidget(row)
        form = QFormLayout()
        self.custom = QLineEdit()
        self.custom.setPlaceholderText(_("Texto o expresión regular"))
        self.regex = QCheckBox(_("Expresión regular"))
        self.case = QCheckBox(_("Distinguir mayúsculas y minúsculas"))
        self.word = QCheckBox(_("Solo palabras completas"))
        form.addRow(_("Texto personalizado"), self.custom)
        form.addRow("", self.regex)
        form.addRow("", self.case)
        form.addRow("", self.word)
        self.body.addLayout(form)
        search_row = QHBoxLayout()
        self.search_button = QPushButton(_("Buscar"))
        self.search_button.clicked.connect(self.search)
        self.select_all = QPushButton(_("Marcar todo"))
        self.select_none = QPushButton(_("Desmarcar todo"))
        self.select_all.clicked.connect(lambda: self.set_all_checked(True))
        self.select_none.clicked.connect(lambda: self.set_all_checked(False))
        search_row.addWidget(self.search_button)
        search_row.addStretch()
        search_row.addWidget(self.select_all)
        search_row.addWidget(self.select_none)
        self.body.addLayout(search_row)
        self.results = QListWidget()
        self.results.setMinimumHeight(180)
        self.results.itemChanged.connect(lambda _i: self._update_state())
        self.body.addWidget(self.results)
        self.summary = _caption(_("Elige patrones y pulsa Buscar. Las coincidencias se marcan para censurar; el contenido se elimina al aplicar las censuras."))
        self.body.addWidget(self.summary)
        self.fill = ColorButton((0, 0, 0))
        fill_row = QFormLayout()
        fill_row.addRow(_("Color de relleno"), self.fill)
        self.body.addLayout(fill_row)
        self._finish_layout()
        self.ok_button.setEnabled(False)

    def search(self):
        self.set_error("")
        self.results.clear()
        self.matches = []
        if self.doc is None:
            self.set_error(_("No hay un documento abierto."))
            return
        try:
            self.matches = doctools.find_matches(
                self.doc, [k for k, c in self.pattern_checks.items() if c.isChecked()],
                custom=self.custom.text(), custom_is_regex=self.regex.isChecked(),
                case_sensitive=self.case.isChecked(), whole_word=self.word.isChecked())
        except ValueError as exc:
            self.set_error(str(exc))
            self._update_state()
            return
        self.results.blockSignals(True)
        for match in self.matches:
            item = QListWidgetItem(_("Pág. {page} · {label} · {found}", page=match['page'] + 1, label=_(match['label']), found=match["text"]))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.results.addItem(item)
        self.results.blockSignals(False)
        self._update_state()

    def set_matches(self, matches):
        """Load matches computed elsewhere (all checked)."""
        self.matches = list(matches)
        self.results.clear()
        for match in self.matches:
            item = QListWidgetItem(_("Pág. {page} · {label} · {found}", page=match['page'] + 1, label=_(match.get('label', '')), found=match["text"]))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.results.addItem(item)
        self._update_state()

    def set_all_checked(self, checked):
        for i in range(self.results.count()):
            self.results.item(i).setCheckState(Qt.Checked if checked else Qt.Unchecked)

    def selected_matches(self):
        return [m for i, m in enumerate(self.matches) if self.results.item(i).checkState() == Qt.Checked]

    def _update_state(self):
        chosen = len(self.selected_matches())
        self.summary.setText(_("{chosen} de {total} coincidencias seleccionadas.", chosen=chosen, total=len(self.matches)))
        self.ok_button.setEnabled(chosen > 0)

    def validate(self):
        return None if self.selected_matches() else _("Selecciona al menos una coincidencia.")

    def values(self):
        return {"matches": self.selected_matches(), "fill": self.fill.rgb(),
                "patterns": [k for k, c in self.pattern_checks.items() if c.isChecked()],
                "custom": self.custom.text(), "custom_is_regex": self.regex.isChecked(),
                "case_sensitive": self.case.isChecked(), "whole_word": self.word.isChecked()}


# --------------------------------------------------------------- optimize

def format_size(count):
    value = float(count)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}".replace(".", ",")
        value /= 1024


class OptimizeDialog(_ToolDialog):
    """values(): dpi (int|None), jpeg_quality, remove_metadata, remove_unused
    -> doctools.optimize(doc, **values). The "Calcular tamaño" button emits
    ``previewRequested(values)``; the caller runs the optimization and calls
    ``set_result(before, after)``."""
    previewRequested = Signal(dict)
    PRESETS = [(N_("Equilibrado (150 ppp)"), 150, 75), (N_("Alta calidad (220 ppp)"), 220, 85),
               (N_("Tamaño mínimo (96 ppp)"), 96, 55), (N_("Sin tocar imágenes"), None, 75), (N_("Personalizado"), -1, 75)]

    def __init__(self, current_size=None, parent=None):
        super().__init__(_("Optimizar PDF"), "OptimizeDialog", parent)
        form = QFormLayout()
        self.preset = QComboBox()
        for label, dpi, quality in self.PRESETS:
            self.preset.addItem(_(label), (dpi, quality))
        self.dpi = QSpinBox()
        self.dpi.setRange(36, 1200)
        self.dpi.setValue(150)
        self.dpi.setSuffix(" ppp")
        self.quality = QSpinBox()
        self.quality.setRange(1, 100)
        self.quality.setValue(75)
        self.downsample = QCheckBox(_("Reducir resolución de imágenes"))
        self.downsample.setChecked(True)
        self.remove_unused = QCheckBox(_("Eliminar objetos no usados y comprimir"))
        self.remove_unused.setChecked(True)
        self.remove_metadata = QCheckBox(_("Eliminar metadatos"))
        form.addRow(_("Ajuste"), self.preset)
        form.addRow("", self.downsample)
        form.addRow(_("Resolución máxima"), self.dpi)
        form.addRow(_("Calidad JPEG"), self.quality)
        form.addRow("", self.remove_unused)
        form.addRow("", self.remove_metadata)
        self.body.addLayout(form)
        self.current = _caption("")
        if current_size is not None:
            self.current.setText(_("Tamaño actual: {size}", size=format_size(current_size)))
        self.body.addWidget(self.current)
        calc = QHBoxLayout()
        self.calc_button = QPushButton(_("Calcular tamaño"))
        self.calc_button.clicked.connect(lambda: self.previewRequested.emit(self.values()))
        calc.addWidget(self.calc_button)
        calc.addStretch()
        self.body.addLayout(calc)
        self.result = QLabel("")
        self.result.setObjectName("OptimizeResult")
        self.result.setWordWrap(True)
        self.body.addWidget(self.result)
        self.preset.currentIndexChanged.connect(self._preset_changed)
        self.downsample.toggled.connect(self._sync_enabled)
        self._finish_layout()
        self._preset_changed()

    def _preset_changed(self, *_args):
        dpi, quality = self.preset.currentData()
        if dpi == -1:
            self._sync_enabled()
            return
        self.downsample.setChecked(dpi is not None)
        if dpi is not None:
            self.dpi.setValue(dpi)
        self.quality.setValue(quality)
        self._sync_enabled()

    def _sync_enabled(self, *_args):
        on = self.downsample.isChecked()
        self.dpi.setEnabled(on)
        self.quality.setEnabled(on)

    def set_result(self, before, after):
        saved = before - after
        if before > 0 and saved > 0:
            text = _("{before} → {after}  (se ahorra {saved}, {percent} %)", before=format_size(before), after=format_size(after), saved=format_size(saved), percent=f"{saved * 100 / before:.0f}")
        else:
            text = _("{before} → {after}  (no se puede reducir más)", before=format_size(before), after=format_size(after))
        self.result.setText(text)

    def values(self):
        return {"dpi": self.dpi.value() if self.downsample.isChecked() else None,
                "jpeg_quality": self.quality.value(), "remove_metadata": self.remove_metadata.isChecked(),
                "remove_unused": self.remove_unused.isChecked()}


# ------------------------------------------------------------ page labels

class PageLabelsDialog(_ToolDialog):
    """values(): rules -> doctools.set_page_labels(doc, values["rules"])."""

    def __init__(self, page_count=1, parent=None):
        super().__init__(_("Etiquetas de página"), "PageLabelsDialog", parent, 600)
        self.page_count = max(1, page_count)
        self.body.addWidget(_caption(_("Cada rango empieza en una página y numera hasta el siguiente rango.")))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([_("Desde la página"), _("Estilo"), _("Prefijo"), _("Empezar en")])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(160)
        self.body.addWidget(self.table)
        row = QHBoxLayout()
        add = QPushButton(_("Añadir rango"))
        remove = QPushButton(_("Quitar rango"))
        add.clicked.connect(lambda: self.add_rule())
        remove.clicked.connect(self.remove_selected)
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch()
        self.body.addLayout(row)
        self.body.addWidget(_section(_("VISTA PREVIA")))
        self.preview = QLabel()
        self.preview.setObjectName("PageLabelsPreview")
        self.preview.setWordWrap(True)
        self.preview.setTextFormat(Qt.PlainText)
        self.body.addWidget(self.preview)
        self._finish_layout()
        self.add_rule(1, "arabic")

    def add_rule(self, start=None, style="arabic", prefix="", first=1):
        r = self.table.rowCount()
        self.table.insertRow(r)
        if start is None:
            start = min(self.page_count, (self._max_start() + 1) if r else 1)
        spin = QSpinBox()
        spin.setRange(1, self.page_count)
        spin.setValue(start)
        combo = QComboBox()
        for key, name in doctools.LABEL_STYLE_NAMES.items():
            combo.addItem(_(name), key)
        combo.setCurrentIndex(combo.findData(style))
        pre = QLineEdit(prefix)
        num = QSpinBox()
        num.setRange(1, 99999)
        num.setValue(first)
        for col, widget in enumerate((spin, combo, pre, num)):
            self.table.setCellWidget(r, col, widget)
        spin.valueChanged.connect(self.update_preview)
        combo.currentIndexChanged.connect(self.update_preview)
        pre.textChanged.connect(self.update_preview)
        num.valueChanged.connect(self.update_preview)
        self.update_preview()

    def _max_start(self):
        return max((self.table.cellWidget(r, 0).value() for r in range(self.table.rowCount())), default=0)

    def remove_selected(self):
        row = self.table.currentRow()
        if row < 0:
            row = self.table.rowCount() - 1
        if row >= 0 and self.table.rowCount() > 1:
            self.table.removeRow(row)
            self.update_preview()

    def rules(self):
        out = []
        for r in range(self.table.rowCount()):
            out.append({"start": self.table.cellWidget(r, 0).value() - 1,
                        "style": self.table.cellWidget(r, 1).currentData(),
                        "prefix": self.table.cellWidget(r, 2).text(),
                        "first": self.table.cellWidget(r, 3).value()})
        return out

    def label_names(self, limit=12):
        """Labels of the first ``limit`` pages under the current rules (empty on invalid rules)."""
        import pymupdf as fitz
        scratch = fitz.open()
        try:
            for _i in range(self.page_count):
                scratch.new_page(width=20, height=20)
            doctools.set_page_labels(scratch, self.rules())
            return doctools.page_label_names(scratch)[:limit]
        except ValueError:
            return []
        finally:
            scratch.close()

    def update_preview(self, *_args):
        names = self.label_names()
        if names:
            more = " …" if self.page_count > len(names) else ""
            self.preview.setText("  ".join(f"{i + 1}→{n}" for i, n in enumerate(names)) + more)
        else:
            self.preview.setText(_("Los rangos no son válidos."))

    def validate(self):
        starts = [r["start"] for r in self.rules()]
        if len(set(starts)) != len(starts):
            return _("Dos rangos empiezan en la misma página.")
        return None

    def values(self):
        return {"rules": self.rules()}


# ------------------------------------------------------------ insert page

class InsertPageDialog(_ToolDialog):
    """values(): mode ('blank' | 'image' | 'duplicate'), after (zero based page to insert after,
    -1 = at the start), size, width, height, landscape, image (path), copies, page.

    mode blank     -> doctools.insert_blank_page(doc, after, size, width, height, landscape)
    mode image     -> doctools.insert_image_page(doc, after, image, size|None, width, height, landscape)
    mode duplicate -> doctools.duplicate_page(doc, page, copies)
    """

    def __init__(self, page_count=1, current=0, parent=None):
        super().__init__(_("Insertar páginas"), "InsertPageDialog", parent)
        self.page_count = max(1, page_count)
        self.blank_radio = QRadioButton(_("Página en blanco"))
        self.image_radio = QRadioButton(_("Imagen como página"))
        self.dup_radio = QRadioButton(_("Duplicar la página actual"))
        self.blank_radio.setChecked(True)
        for r in (self.blank_radio, self.image_radio, self.dup_radio):
            self.body.addWidget(r)
            r.toggled.connect(self._sync)
        form = QFormLayout()
        self.size = QComboBox()
        for name in list(doctools.PAGE_SIZES) + ["Personalizado"]:
            self.size.addItem(_(name), name)
        self.width = QDoubleSpinBox()
        self.height = QDoubleSpinBox()
        for w, v in ((self.width, 595.0), (self.height, 842.0)):
            w.setRange(20, 14400)
            w.setValue(v)
            w.setSuffix(" pt")
        self.landscape = QCheckBox(_("Horizontal"))
        self.image_path = QLineEdit()
        self.image_path.setPlaceholderText(_("Archivo de imagen"))
        self.browse = QPushButton(_("Examinar…"))
        self.browse.clicked.connect(self._browse)
        image_row = QHBoxLayout()
        image_row.addWidget(self.image_path)
        image_row.addWidget(self.browse)
        self.fit_page = QCheckBox(_("Ajustar a un tamaño de página (si no, la página toma el de la imagen)"))
        self.copies = QSpinBox()
        self.copies.setRange(1, 100)
        self.where = QComboBox()
        self.where.addItem(_("Al principio"), -1)
        for i in range(self.page_count):
            self.where.addItem(_("Después de la página {n}", n=i + 1), i)
        self.where.setCurrentIndex(min(max(current, 0), self.page_count - 1) + 1)
        self.current = max(0, min(current, self.page_count - 1))
        form.addRow(_("Tamaño"), self.size)
        form.addRow(_("Ancho"), self.width)
        form.addRow(_("Alto"), self.height)
        form.addRow("", self.landscape)
        form.addRow(_("Imagen"), image_row)
        form.addRow("", self.fit_page)
        form.addRow(_("Copias"), self.copies)
        form.addRow(_("Posición"), self.where)
        self.body.addLayout(form)
        self.size.currentIndexChanged.connect(self._sync)
        self.fit_page.toggled.connect(self._sync)
        self._finish_layout()
        self._sync()

    def mode(self):
        return "image" if self.image_radio.isChecked() else "duplicate" if self.dup_radio.isChecked() else "blank"

    def _sync(self, *_args):
        mode = self.mode()
        custom = self.size.currentData() == "Personalizado"
        uses_size = mode == "blank" or (mode == "image" and self.fit_page.isChecked())
        self.size.setEnabled(uses_size)
        self.width.setEnabled(uses_size and custom)
        self.height.setEnabled(uses_size and custom)
        self.landscape.setEnabled(uses_size)
        self.image_path.setEnabled(mode == "image")
        self.browse.setEnabled(mode == "image")
        self.fit_page.setEnabled(mode == "image")
        self.copies.setEnabled(mode == "duplicate")
        self.where.setEnabled(mode != "duplicate")

    def _browse(self):
        path, _filter = QFileDialog.getOpenFileName(self, _("Elegir imagen"), "", _(IMAGE_FILTER))
        if path:
            self.image_path.setText(path)

    def validate(self):
        if self.mode() == "image" and not self.image_path.text().strip():
            return _("Elige un archivo de imagen.")
        return None

    def values(self):
        mode = self.mode()
        size = self.size.currentData()
        if mode == "image" and not self.fit_page.isChecked():
            size = None
        return {"mode": mode, "after": self.where.currentData(), "size": size,
                "width": self.width.value(), "height": self.height.value(), "landscape": self.landscape.isChecked(),
                "image": self.image_path.text().strip(), "copies": self.copies.value(), "page": self.current}


# ----------------------------------------------------------------- stamps

class StampDialog(_ToolDialog):
    """values(): kind ('preset' | 'image'), name (preset name), color (rgb|None = preset colour),
    image (path), opacity, as_annotation
    -> doctools.add_preset_stamp(doc, page, rect, name, color=, as_annotation=, opacity=)
       doctools.add_image_stamp(doc, page, rect, image, as_annotation=, opacity=)"""

    def __init__(self, parent=None):
        super().__init__(_("Sellos"), "StampDialog", parent)
        self.body.addWidget(_section(_("SELLOS PREDEFINIDOS")))
        self.list = QListWidget()
        self.list.setObjectName("StampList")
        self.list.setMaximumHeight(170)
        for name, rgb in doctools.STAMPS.items():
            item = QListWidgetItem(_(name))
            item.setData(Qt.UserRole, name)
            item.setForeground(QColor.fromRgbF(*rgb))
            font = item.font()
            font.setBold(True)
            item.setFont(font)
            self.list.addItem(item)
        self.list.setCurrentRow(0)
        self.body.addWidget(self.list)
        self.custom_color = QCheckBox(_("Usar otro color"))
        self.color = ColorButton((0.78, 0.1, 0.1))
        self.color.setEnabled(False)
        self.custom_color.toggled.connect(self.color.setEnabled)
        color_row = QHBoxLayout()
        color_row.addWidget(self.custom_color)
        color_row.addWidget(self.color)
        color_row.addStretch()
        self.body.addLayout(color_row)
        self.body.addWidget(_section(_("SELLO DE IMAGEN (FIRMA, LOGOTIPO)")))
        self.use_image = QCheckBox(_("Usar una imagen en lugar de un sello predefinido"))
        self.image_path = QLineEdit()
        self.image_path.setPlaceholderText(_("PNG con transparencia recomendado"))
        self.browse = QPushButton(_("Examinar…"))
        self.browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.image_path)
        row.addWidget(self.browse)
        self.body.addWidget(self.use_image)
        self.body.addLayout(row)
        form = QFormLayout()
        self.opacity = QSlider(Qt.Horizontal)
        self.opacity.setRange(5, 100)
        self.opacity.setValue(100)
        self.as_annotation = QCheckBox(_("Insertar como anotación (se puede mover o eliminar)"))
        self.as_annotation.setChecked(True)
        form.addRow(_("Opacidad"), self.opacity)
        form.addRow("", self.as_annotation)
        self.body.addLayout(form)
        self.use_image.toggled.connect(self._sync)
        # Picking a preset or an image starts placing it on the page; no OK button needed.
        self.list.itemActivated.connect(lambda _item: self.accept())
        self.list.itemClicked.connect(lambda _item: self.accept())
        self._finish_layout()
        self.ok_button.hide()
        self._sync()

    def _sync(self, *_args):
        image = self.use_image.isChecked()
        self.list.setEnabled(not image)
        self.custom_color.setEnabled(not image)
        self.color.setEnabled(not image and self.custom_color.isChecked())
        self.image_path.setEnabled(image)
        self.browse.setEnabled(image)

    def _browse(self):
        path, _filter = QFileDialog.getOpenFileName(self, _("Elegir imagen"), "", _(IMAGE_FILTER))
        if path:
            self.image_path.setText(path)
            self.use_image.setChecked(True)
            self.accept()

    def validate(self):
        if self.use_image.isChecked() and not self.image_path.text().strip():
            return _("Elige un archivo de imagen.")
        return None

    def values(self):
        item = self.list.currentItem()
        image = self.use_image.isChecked()
        return {"kind": "image" if image else "preset",
                "name": item.data(Qt.UserRole) if item is not None else "",
                "color": self.color.rgb() if self.custom_color.isChecked() and not image else None,
                "image": self.image_path.text().strip() if image else "",
                "opacity": self.opacity.value() / 100.0, "as_annotation": self.as_annotation.isChecked()}


# --------------------------------------------------------------- flatten

class FlattenDialog(_ToolDialog):
    """values(): annotations (bool), forms (bool) -> doctools.flatten(doc, **values)."""
    ACCEPT_TEXT = N_("Aplanar")

    def __init__(self, parent=None):
        super().__init__(_("Aplanar documento"), "FlattenDialog", parent)
        self.body.addWidget(_caption(_(
            "Las anotaciones y los campos de formulario pasan a formar parte del contenido de la página: "
            "dejan de poder editarse, pero se ven igual en cualquier lector. Puedes deshacerlo en esta sesión.")))
        self.annotations = QCheckBox(_("Anotaciones (resaltados, notas, sellos, figuras)"))
        self.annotations.setChecked(True)
        self.forms = QCheckBox(_("Campos de formulario"))
        self.forms.setChecked(True)
        self.body.addWidget(self.annotations)
        self.body.addWidget(self.forms)
        self.annotations.toggled.connect(lambda _checked: self.set_error(None))
        self.forms.toggled.connect(lambda _checked: self.set_error(None))
        self._finish_layout()

    def validate(self):
        if not (self.annotations.isChecked() or self.forms.isChecked()):
            return _("Elige qué aplanar: anotaciones, formularios o ambos.")
        return None

    def values(self):
        return {"annotations": self.annotations.isChecked(), "forms": self.forms.isChecked()}


# ------------------------------------------------------------- protection

PASSWORD_MIN_LENGTH = 8


def password_strength(password):
    """(text, level) with level 0..2 for the strength meter; empty text for an empty password."""
    if not password:
        return "", 0
    score = sum([
        len(password) >= PASSWORD_MIN_LENGTH, len(password) >= 12,
        any(c.islower() for c in password) and any(c.isupper() for c in password),
        any(c.isdigit() for c in password), any(not c.isalnum() for c in password),
    ])
    if score <= 2:
        return _("Débil"), 0
    if score <= 3:
        return _("Aceptable"), 1
    return _("Fuerte"), 2


class ProtectDialog(_ToolDialog):
    """One dialog for the passwords of a protected copy.

    values(): password (opening, required), owner ("" generates a strong one),
    restrict (True: only accessibility stays allowed, so print, copy and edit are blocked)
    -> PDFEngine.protect(path, password, owner or None, permissions=permissions_for(restrict)).
    """
    ACCEPT_TEXT = N_("Continuar")

    def __init__(self, parent=None):
        super().__init__(_("Proteger PDF"), "ProtectDialog", parent, 520)
        self.body.addWidget(_caption(_(
            "La contraseña de apertura es necesaria para abrir el archivo. La de propietario controla "
            "los permisos; si la dejas vacía se genera una segura y se muestra una sola vez.")))
        form = QFormLayout()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText(_("Al menos {n} caracteres", n=PASSWORD_MIN_LENGTH))
        self.repeat = QLineEdit()
        self.repeat.setEchoMode(QLineEdit.EchoMode.Password)
        self.reveal = QPushButton(_("Mostrar"))
        self.reveal.setCheckable(True)
        self.reveal.setObjectName("RevealPassword")
        self.reveal.toggled.connect(self._reveal)
        row = QHBoxLayout()
        row.addWidget(self.password, 1)
        row.addWidget(self.reveal)
        form.addRow(_("Contraseña de apertura"), row)
        form.addRow(_("Repetir contraseña"), self.repeat)
        self.strength = _caption("")
        self.strength.setObjectName("PasswordStrength")
        form.addRow(_("Fuerza"), self.strength)
        self.owner = QLineEdit()
        self.owner.setEchoMode(QLineEdit.EchoMode.Password)
        self.owner.setPlaceholderText(_("Vacía: se genera una segura"))
        form.addRow(_("Propietario (opcional)"), self.owner)
        self.restrict = QCheckBox(_("Restringir imprimir, copiar y editar"))
        form.addRow("", self.restrict)
        self.body.addLayout(form)
        self.password.textChanged.connect(self._update)
        self.repeat.textChanged.connect(self._update)
        self._finish_layout()
        self._update()

    def _reveal(self, shown):
        mode = QLineEdit.EchoMode.Normal if shown else QLineEdit.EchoMode.Password
        self.password.setEchoMode(mode)
        self.repeat.setEchoMode(mode)
        self.owner.setEchoMode(mode)
        self.reveal.setText(_("Ocultar") if shown else _("Mostrar"))

    def _update(self, *_args):
        self.strength.setText(password_strength(self.password.text())[0])
        self.set_error(self._problem())

    def _problem(self):
        """Inline message for the current fields, None when they are valid to continue."""
        password = self.password.text()
        if password and len(password) < PASSWORD_MIN_LENGTH:
            return _("Usa al menos {n} caracteres.", n=PASSWORD_MIN_LENGTH)
        if self.repeat.text() and self.repeat.text() != password:
            return _("Las contraseñas no coinciden.")
        return None

    def validate(self):
        if not self.password.text():
            return _("Escribe la contraseña de apertura.")
        return self._problem()

    def values(self):
        return {"password": self.password.text(), "owner": self.owner.text(), "restrict": self.restrict.isChecked()}


def permissions_for(restrict):
    """Permission bits kept when restricting: only accessibility (screen readers) stays allowed."""
    return fitz.PDF_PERM_ACCESSIBILITY if restrict else None


class OcrLanguagesDialog(_ToolDialog):
    """Choose among the bundled Tesseract languages. values(): languages (codes, e.g. ["spa", "eng"]), deskew (bool)."""
    NAMES = {"spa": N_("Español"), "eng": N_("Inglés"), "fra": N_("Francés"), "deu": N_("Alemán"), "por": N_("Portugués")}

    def __init__(self, codes, parent=None):
        super().__init__(_("Idiomas del texto"), "OcrLanguagesDialog", parent, 360)
        self.body.addWidget(_caption(_("Elige los idiomas del documento. Varios idiomas tardan más.")))
        self.checks = {}
        for code in codes:
            check = QCheckBox(_(self.NAMES.get(code, code)))
            check.setObjectName(f"language_{code}")
            check.setChecked(True)
            check.toggled.connect(lambda _checked: self.set_error(None))
            self.checks[code] = check
            self.body.addWidget(check)
        self.deskew = QCheckBox(_("Enderezar páginas y detectar su orientación"))
        self.deskew.setObjectName("ocr_deskew")
        self.deskew.setToolTip(_("Útil en escaneos torcidos o girados. Tarda más."))
        self.body.addWidget(self.deskew)
        self._finish_layout()

    def validate(self):
        return None if self.values()["languages"] else _("Elige al menos un idioma.")

    def values(self):
        return {"languages": [code for code, check in self.checks.items() if check.isChecked()], "deskew": self.deskew.isChecked()}


# --------------------------------------------------------- document check

SEVERITY_TEXT = {"error": N_("Error"), "warning": N_("Aviso"), "info": N_("Información"), "ok": N_("Correcto")}
SEVERITY_COLOR = {"error": "#B42318", "warning": "#9A5B00", "info": "#4F5B5F", "ok": "#087F70"}


class DocumentCheckDialog(QDialog):
    """Read-only report view for doctools.check_document(). values() returns {}.
    ``findingActivated(dict)`` is emitted when a finding with a page is double-clicked."""
    findingActivated = Signal(dict)

    def __init__(self, report, parent=None):
        super().__init__(parent)
        self.setObjectName("DocumentCheckDialog")
        self.setWindowTitle(_("Comprobar documento"))
        self.setMinimumSize(560, 480)
        self.report = report
        layout = QVBoxLayout(self)
        s = report["summary"]
        self.headline = QLabel(
            _("{pages} páginas · {images} imágenes · {fonts} fuentes · {form_fields} campos de formulario", pages=s['pages'], images=s['images'], fonts=s['fonts'], form_fields=s['form_fields']))
        self.headline.setObjectName("DocumentCheckSummary")
        self.counts = _caption(_("{errors} errores · {warnings} avisos", errors=s.get('errors', 0), warnings=s.get('warnings', 0)))
        layout.addWidget(self.headline)
        layout.addWidget(self.counts)
        layout.addWidget(_section(_("RESULTADOS")))
        self.tree = QTreeWidget()
        self.tree.setObjectName("DocumentCheckFindings")
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels([_("Gravedad"), _("Detalle")])
        self.tree.setRootIsDecorated(False)
        self.tree.setWordWrap(True)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(1, QHeaderView.Stretch)
        for finding in report["findings"]:
            item = QTreeWidgetItem([_(SEVERITY_TEXT[finding["severity"]]), _(finding["message"])])
            item.setForeground(0, QColor(SEVERITY_COLOR[finding["severity"]]))
            item.setData(0, Qt.UserRole, finding)
            item.setToolTip(1, _(finding["message"]))
            self.tree.addTopLevelItem(item)
        self.tree.itemDoubleClicked.connect(self._activated)
        layout.addWidget(self.tree, 1)
        layout.addWidget(_section(_("FUENTES")))
        self.fonts = QListWidget()
        self.fonts.setMaximumHeight(110)
        for f in report["fonts"]:
            self.fonts.addItem(_("{name} — incrustada", name=f['name']) if f['embedded'] else _("{name} — no incrustada", name=f['name']))
        if not report["fonts"]:
            self.fonts.addItem(_("Sin fuentes"))
        layout.addWidget(self.fonts)
        row = QHBoxLayout()
        row.addStretch()
        close = QPushButton(_("Cerrar"))
        close.setProperty("primary", True)
        close.clicked.connect(self.accept)
        row.addWidget(close)
        layout.addLayout(row)

    def _activated(self, item, _column):
        finding = item.data(0, Qt.UserRole)
        if finding and "page" in finding:
            self.findingActivated.emit(finding)

    def values(self):
        return {}


# ------------------------------------------------------------ image export

class ExportImagesDialog(_ToolDialog):
    """values(): dpi, pages (None for all, else zero based indices), fmt ('png' or 'jpeg'), quality
    -> engine.export_images(folder, **values)."""
    DPI = (72, 150, 300, 600)
    ACCEPT_TEXT = N_("Exportar")

    def __init__(self, page_count=1, current=1, parent=None):
        super().__init__(_("Exportar páginas como imágenes"), "ExportImagesDialog", parent)
        self.page_count = max(1, page_count)
        self.current = min(max(current, 1), self.page_count) - 1
        self.dpi = QComboBox()
        for value in self.DPI:
            self.dpi.addItem(_("{value} ppp", value=value), value)
        self.dpi.setCurrentIndex(self.DPI.index(150))
        self.scope = QComboBox()
        self.scope.addItem(_("Todas las páginas"), "all")
        self.scope.addItem(_("Página actual ({n})", n=self.current + 1), "current")
        self.scope.addItem(_("Rango de páginas"), "range")
        self.range = QLineEdit()
        self.range.setPlaceholderText(_("Ejemplo: 1-3, 5 (1-{page_count})", page_count=self.page_count))
        self.fmt = QComboBox()
        self.fmt.addItem(_("PNG (sin pérdida)"), "png")
        self.fmt.addItem(_("JPEG (más ligero)"), "jpeg")
        self.quality = QSpinBox()
        self.quality.setRange(1, 100)
        self.quality.setValue(90)
        self.quality_label = QLabel(_("Calidad JPEG"))
        form = QFormLayout()
        form.addRow(_("Resolución"), self.dpi)
        form.addRow(_("Páginas"), self.scope)
        form.addRow(_("Rango"), self.range)
        form.addRow(_("Formato"), self.fmt)
        form.addRow(self.quality_label, self.quality)
        self.body.addLayout(form)
        self.scope.currentIndexChanged.connect(self._sync)
        self.fmt.currentIndexChanged.connect(self._sync)
        self._sync()
        self._finish_layout()

    def _sync(self, *_args):
        self.range.setEnabled(self.scope.currentData() == "range")
        jpeg = self.fmt.currentData() == "jpeg"
        self.quality.setEnabled(jpeg)
        self.quality_label.setEnabled(jpeg)

    def validate(self):
        if self.scope.currentData() != "range":
            return None
        if not self.range.text().strip():
            return _("Escribe el rango de páginas, por ejemplo 1-3, 5.")
        try:
            doctools.parse_page_range(self.range.text(), self.page_count)
        except ValueError as error:
            return str(error)
        return None

    def values(self):
        scope = self.scope.currentData()
        if scope == "all":
            pages = None
        elif scope == "current":
            pages = [self.current]
        else:
            pages = doctools.parse_page_range(self.range.text(), self.page_count)
        return {"dpi": self.dpi.currentData(), "pages": pages, "fmt": self.fmt.currentData(), "quality": self.quality.value()}
