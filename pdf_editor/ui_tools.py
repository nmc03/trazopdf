from __future__ import annotations

import json
import tempfile

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout, QWidget
from pathlib import Path
import pymupdf as fitz

from . import doctools, doctools_dialogs
from .doctools_dialogs import format_size
from .engine import PDFEngine
from .floating_bar import rgb_of
from .lang import _, N_
from .toast import notify
from .ui_rail import MODE_ICONS
from .ui_support import CANCELLED, JOB_PREFIXES, ROOT, claim_job_folder, format_text_comparison

TESSDATA_LANGUAGES = ("spa", "eng", "fra", "deu", "por")
MODE_ICONS.update({"freetext": "freetext", "line": "line", "arrow": "arrow", "measure": "measure"})
REVIEW_LABELS = [("None", N_("Sin estado")), ("Accepted", N_("Aceptado")), ("Rejected", N_("Rechazado")), ("Completed", N_("Completado"))]
STAMP_TURNS = [(N_("Sin giro"), 0), (N_("90° a la izquierda"), 90), (N_("90° a la derecha"), 270)]


def pdf_date(value):
    """'D:20261028093000+02' as '28/10/2026 09:30'; empty when it cannot be read."""
    digits = "".join(ch for ch in str(value or "").removeprefix("D:")[:14] if ch.isdigit())
    if len(digits) < 8:
        return ""
    text = f"{digits[6:8]}/{digits[4:6]}/{digits[:4]}"
    return text + f" {digits[8:10]}:{digits[10:12]}" if len(digits) >= 12 else text


def bundled_languages():
    """Tesseract language codes whose data ships with the app (assets/tessdata)."""
    folder = ROOT / "assets" / "tessdata"
    return [code for code in TESSDATA_LANGUAGES if (folder / f"{code}.traineddata").is_file()]


class UiToolsMixin:
    """Wrappers around the document tools (doctools / doctools_dialogs)."""

    def _done(self, text):
        """Result of a reversible change: a banner with Deshacer instead of a confirmation."""
        notify(self, text, actions=[(_("Deshacer"), self.undo)])

    def place_annotation_tool(self, mode, rect, point, clicked):
        """Line, Flecha and Cuadro de texto: created straight on the page, no dialog."""
        view = self.view

        def operation():
            style = view.tool_style(mode)
            color = rgb_of(style["color"])
            if mode == "freetext":
                box = fitz.Rect(point.x, point.y, point.x + 180, point.y + 40) if clicked or rect.width < 20 or rect.height < 14 else rect
                xref = self.change(lambda: self.engine.add_freetext(self.page, box, " ", color=color, size=12))
                view.open_note_popover(xref, box)
                return
            start, end = view.last_drag
            if clicked:
                self.statusBar().showMessage(_("Arrastra para dibujar la línea"))
                return
            self.change(lambda: self.engine.add_line(self.page, start, end, mode == "arrow", color, style["width"], style["opacity"]))

        self.run(operation)

    def set_annotation_author(self, name):
        """Author written into new annotations; remembered between sessions."""
        name = name.strip()
        if name:
            self.settings.setValue("annotationAuthor", name)
            self.engine.author = name

    def reply_to_comment(self, xref, text, page=None):
        page = self.page if page is None else page
        self.change(lambda: self.engine.add_reply(page, xref, text))

    def set_comment_state(self, xref, state, page=None):
        page = self.page if page is None else page
        self.change(lambda: self.engine.set_annotation_state(page, xref, state))

    # ---- left panel: Comentarios (thread, reply, state, author), Campos and Propiedades

    def toggle_layer(self, number, visible):
        def operation():
            self.engine.set_layer_visible(number, visible)
            self.render_page()
        self.run(operation)

    def engine_remember_layers(self, remember):
        self.engine.remember_layers(remember)

    def build_comments_panel(self):
        panel = QWidget()
        column = QVBoxLayout(panel)
        column.setContentsMargins(6, 6, 6, 6)
        column.setSpacing(6)
        self.author_edit = QLineEdit(self.engine.author)
        self.author_edit.setPlaceholderText(_("Autor de tus comentarios"))
        self.author_edit.setAccessibleName(_("Autor de los comentarios"))
        self.author_edit.setToolTip(_("Nombre con el que se firman tus anotaciones y respuestas"))
        self.author_edit.editingFinished.connect(lambda: self.set_annotation_author(self.author_edit.text()))
        self.comment_list = QListWidget()
        self.comment_list.setWordWrap(True)
        self.comment_list.itemClicked.connect(lambda _: self.side_comment_go())
        self.comment_list.currentRowChanged.connect(self.comment_selected)
        self.comment_state = QComboBox()
        self.comment_state.setAccessibleName(_("Estado del comentario"))
        for key, label in REVIEW_LABELS:
            self.comment_state.addItem(_(label), key)
        self.comment_state.activated.connect(lambda _: self.run(self.side_comment_state))
        self.reply_edit = QLineEdit()
        self.reply_edit.setPlaceholderText(_("Escribe una respuesta"))
        self.reply_edit.setAccessibleName(_("Respuesta"))
        self.reply_edit.returnPressed.connect(lambda: self.run(self.side_comment_reply))
        reply = QPushButton(_("Responder"))
        reply.clicked.connect(lambda _=False: self.run(self.side_comment_reply))
        remove = QPushButton(_("Eliminar"))
        remove.clicked.connect(lambda _=False: self.run(self.side_comment_remove))
        row = QHBoxLayout()
        row.setSpacing(4)
        row.addWidget(self.reply_edit, 1)
        row.addWidget(reply)
        state_row = QHBoxLayout()
        state_row.setSpacing(4)
        state_row.addWidget(QLabel(_("Estado")))
        state_row.addWidget(self.comment_state, 1)
        state_row.addWidget(remove)
        column.addWidget(self.author_edit)
        column.addWidget(self.comment_list, 1)
        column.addLayout(state_row)
        column.addLayout(row)
        self.comment_controls = (self.comment_state, self.reply_edit, reply, remove)
        return panel

    def fill_comments(self, listing, entries):
        engine = self.engine
        for number, page in enumerate(engine.doc):
            for annot in page.annots() or []:
                if annot.type[0] in (fitz.PDF_ANNOT_LINK, fitz.PDF_ANNOT_WIDGET) or annot.irt_xref:
                    continue
                info = annot.info
                head = " · ".join(part for part in (_("Página {n}", n=number + 1), annot.type[1], info.get("title", ""), pdf_date(info.get("modDate") or info.get("creationDate"))) if part)
                lines = [head]
                if info.get("content", "").strip():
                    lines.append(info["content"].strip())
                thread = engine.annotation_replies(number, annot.xref)
                lines += [f"   ↳ {reply['author']}: {reply['content']}" if reply["author"] else f"   ↳ {reply['content']}" for reply in thread["replies"]]
                if thread["state"] != "None":
                    lines.append(_("Estado: ") + _(dict(REVIEW_LABELS).get(thread["state"], thread["state"])))
                entries.append((number, annot.xref))
                listing.addItem("\n".join(lines))

    def fill_fields(self, listing, entries):
        for field in self.engine.forms():
            entries.append((field["page"], field["xref"]))
            listing.addItem(_("{name}\nPágina {page} · {type}", name=field['name'] or _("Sin nombre"), page=field['page'] + 1, type=field['type']))

    def fill_properties(self, listing, entries):
        engine = self.engine
        data = engine.metadata()
        rows = [(_("Título"), data.get("title")), (_("Autor"), data.get("author")), (_("Asunto"), data.get("subject")), (_("Palabras clave"), data.get("keywords")),
                (_("Creado con"), data.get("creator")), (_("Productor"), data.get("producer")), (_("Creación"), pdf_date(data.get("creationDate"))), (_("Modificación"), pdf_date(data.get("modDate"))),
                (_("Páginas"), str(engine.page_count)), (_("Tamaño"), format_size(len(engine._bytes()))), (_("Versión PDF"), data.get("format")),
                (_("Cifrado"), _("Sí: protegido con contraseña") if engine.is_protected else _("No"))]
        for label, value in rows:
            item = QListWidgetItem(f"{label}\n{value or '—'}")
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            listing.addItem(item)

    def comment_selected(self, row):
        entries = self.side_entries["comments"]
        entry = entries[row] if 0 <= row < len(entries) else None
        for control in self.comment_controls:
            control.setEnabled(entry is not None and self.has_doc())
        self.comment_state.blockSignals(True)
        state = self.engine.annotation_replies(*entry)["state"] if entry else "None"
        self.comment_state.setCurrentIndex(max(0, self.comment_state.findData(state)))
        self.comment_state.blockSignals(False)

    def side_comment_go(self):
        entry = self.side_current("comments")
        if entry:
            self.goto(entry[0])
            info = next((item for item in self.engine.annotations(entry[0]) if item["xref"] == entry[1]), None)
            if info:
                self.view.select_annotation(info)

    def side_comment_reply(self):
        entry, text = self.side_current("comments"), self.reply_edit.text().strip()
        if entry and text:
            self.reply_to_comment(entry[1], text, entry[0])
            self.reply_edit.clear()
            self.refresh_side_panel(True)

    def side_comment_state(self):
        entry = self.side_current("comments")
        if entry:
            self.set_comment_state(entry[1], self.comment_state.currentData(), entry[0])
            self.refresh_side_panel(True)

    def side_field_go(self):
        entry = self.side_current("fields")
        if entry:
            self.goto(entry[0])

    def watermark(self):
        text, ok = QInputDialog.getText(self, _("Marca de agua"), _("Texto para todas las páginas:"))
        if ok and text:
            self.change(lambda: self.engine.watermark(text))
            self._done(_("Marca de agua añadida a {n} página(s)", n=self.engine.page_count))

    def number_pages(self):
        start, ok = QInputDialog.getInt(self, _("Numerar páginas"), _("Primer número:"), 1, 1, 999999)
        if ok:
            self.change(lambda: self.engine.number_pages(start))
            self._done(_("Páginas numeradas desde {start}", start=start))

    def apply_redactions(self):
        if QMessageBox.question(self, _("Aplicar censuras"), _("Se eliminará el contenido bajo todas las marcas de censura. También se quitarán los enlaces, campos de formulario y anotaciones que estén bajo ellas, y los metadatos que citen el texto censurado. Guarda una copia para conservar el original.")) == QMessageBox.StandardButton.Yes:
            self.change(self.engine.apply_redactions)

    def anonymize(self):
        from .anonymize_dialog import AnonymizeDialog
        try:
            data = self.engine.copy_bytes()
        except ValueError as exc:
            QMessageBox.warning(self, _("Anonimizar documento"), str(exc))
            return
        with tempfile.TemporaryDirectory(prefix="trazopdf-anon-") as folder:
            source = Path(folder) / (Path(self.engine.path).name if self.engine.path else "documento.pdf")
            source.write_bytes(data)
            dialog = AnonymizeDialog(source, self)
            if self.engine.path:
                dialog.output.setText(str(Path(self.engine.path).with_name(Path(self.engine.path).stem + "-anonimizado.pdf")))
            dialog.exec()
        if dialog.report is not None and dialog.report.ok:
            self.statusBar().showMessage(_("Copia anonimizada y verificada guardada"))

    def sanitize(self):
        self.change(self.engine.sanitize)
        self._done(_("Datos ocultos eliminados: metadatos, adjuntos, enlaces y scripts. Revisa el resultado antes de guardarlo"))

    def ocr(self):
        languages = bundled_languages() or ["eng"]
        dialog = doctools_dialogs.OcrLanguagesDialog(languages, self)
        if not dialog.exec():
            return
        values = dialog.values()
        language = "+".join(values["languages"])
        deskew = bool(values.get("deskew", False))
        data = self.with_redaction_gate(lambda allow: self.external_job("ocr", _("Reconociendo texto"), allow_pending=allow, language=language, deskew=deskew), _("Continuar de todos modos"))
        if data is not None and data is not CANCELLED:
            self.change(lambda: self.engine.apply_processed(data))
            self._done(_("Texto reconocido; las páginas ahora se pueden buscar y seleccionar"))

    def compare(self):
        path, _filter = QFileDialog.getOpenFileName(self, _("Comparar con otro PDF"), "", "PDF (*.pdf)")
        if path:
            from .comparison_dialog import ComparisonDialog
            with tempfile.TemporaryDirectory(prefix=JOB_PREFIXES[1]) as folder:
                # The claimed folder holds owner.pid, so the report goes into an empty subfolder.
                claim_job_folder(folder)
                report_folder = Path(folder) / "report"
                report = self.with_redaction_gate(lambda allow: self.external_job("compare", _("Comparando apariencia"), allow_pending=allow, path=path, output_folder=str(report_folder)), _("Continuar de todos modos"))
                if report is not None and report is not CANCELLED:
                    ComparisonDialog(report, report_folder, self).exec()

    # ---- document tools (dialogs in doctools_dialogs, logic in doctools through the engine)
    def header_footer(self):
        name = Path(self.engine.path).name if self.engine.path else ""
        dialog = doctools_dialogs.HeaderFooterDialog(self.engine.page_count, name, self)
        if dialog.exec():
            values = dialog.values()
            count = self.change(lambda: self.engine.header_footer(**values))
            self.statusBar().showMessage(_("Encabezado y pie de página añadidos en {n} página(s)", n=count))

    def bates(self):
        dialog = doctools_dialogs.BatesDialog(self.engine.page_count, self)
        if dialog.exec():
            values = dialog.values()
            last = self.change(lambda: self.engine.bates(**values))
            self.statusBar().showMessage(_("Numeración Bates añadida; último número: {label}", label=doctools.bates_label(last, values['prefix'], values['suffix'], values['digits'])))

    def redact_search(self):
        dialog = doctools_dialogs.RedactSearchDialog(self.engine.doc, self)
        if not dialog.exec():
            return
        values = dialog.values()
        count = self.change(lambda: self.engine.mark_redactions(values["matches"], fill=values["fill"]))
        if QMessageBox.question(self, _("Aplicar censuras"), _("Se han marcado {count} zona(s) para censurar. ¿Quieres aplicarlas ahora? Se eliminará el contenido bajo todas las marcas de censura del documento (también enlaces, campos de formulario y anotaciones bajo ellas). Puedes deshacerlo en esta sesión.", count=count)) == QMessageBox.StandardButton.Yes:
            self.change(self.engine.apply_redactions)
            self.statusBar().showMessage(_("Censuras aplicadas"))
        else:
            self.statusBar().showMessage(_("{count} marca(s) de censura añadidas; el texto sigue en el archivo hasta que uses Aplicar censuras", count=count))

    def optimize(self):
        dialog = doctools_dialogs.OptimizeDialog(len(self.engine._bytes()), self)
        cache = {}

        def compute(values):
            key = json.dumps(values, sort_keys=True)
            if key not in cache:
                outcome = self.external_job("optimize", _("Optimizando documento"), options=values)
                if outcome is None:
                    return None
                cache[key] = outcome
            return cache[key]

        def preview(values):
            outcome = self.run(lambda: compute(values))
            if outcome:
                dialog.set_result(outcome[0]["before"], outcome[0]["after"])

        dialog.previewRequested.connect(preview)
        if not dialog.exec():
            return
        values = dialog.values()
        outcome = compute(values)
        if outcome is None:
            return
        stats, data = outcome
        if stats["saved"] <= 0 and not values["remove_metadata"]:
            QMessageBox.information(self, _("Optimizar tamaño"), _("El documento ya está optimizado: no se puede reducir más con estos ajustes."))
            return
        self.change(lambda: self.engine.apply_processed(data))
        before, after = doctools_dialogs.format_size(stats["before"]), doctools_dialogs.format_size(stats["after"])
        self._done(_("Documento optimizado: {before} → {after} (tamaño estimado; al guardar puede variar)", before=before, after=after))

    def flatten(self):
        dialog = doctools_dialogs.FlattenDialog(self)
        if dialog.exec():
            values = dialog.values()
            count = self.with_redaction_gate(lambda allow: self.change(lambda: self.engine.flatten(allow_pending_redactions=allow, **values)), _("Continuar de todos modos"))
            if count is CANCELLED:
                return
            if count:
                self._done(_("{count} elemento(s) aplanados", count=count))
            else:
                self.statusBar().showMessage(_("No había anotaciones ni campos que aplanar"))

    def page_labels(self):
        dialog = doctools_dialogs.PageLabelsDialog(self.engine.page_count, self)
        if dialog.exec():
            rules = dialog.values()["rules"]
            self.change(lambda: self.engine.set_page_labels(rules))
            self.statusBar().showMessage(_("Etiquetas de página actualizadas: ") + ", ".join(self.engine.page_labels()[:6]) + ("…" if self.engine.page_count > 6 else ""))

    def insert_page(self):
        dialog = doctools_dialogs.InsertPageDialog(self.engine.page_count, self.page, self)
        if not dialog.exec():
            return
        values = dialog.values()
        layout = {"size": values["size"], "width": values["width"], "height": values["height"], "landscape": values["landscape"]}

        def insert():
            if values["mode"] == "blank":
                return self.engine.insert_blank_page(values["after"], **layout)
            if values["mode"] == "image":
                return self.engine.insert_image_page(values["after"], values["image"], **layout)
            return self.engine.duplicate_pages(values["page"], values["copies"])[0]

        index = self.change(insert)
        self.goto(index)

    def stamp(self):
        dialog = doctools_dialogs.StampDialog(self)
        turn_box = QComboBox()
        turn_box.setAccessibleName(_("Giro del sello"))
        for label, degrees in STAMP_TURNS:
            turn_box.addItem(_(label), degrees)
        row = QFormLayout()
        row.addRow(_("Giro"), turn_box)
        dialog.body.addLayout(row)
        if dialog.exec():
            self.begin_stamp({**dialog.values(), "turn": turn_box.currentData()})

    def begin_stamp(self, values):
        """Choose where the stamp goes: a click centres it there, a drag sets its size."""
        self.set_mode("stamp")
        self.pending_stamp = values

    def place_stamp(self, point, rect):
        values = self.pending_stamp
        if not values:
            return
        page = self.engine.doc[self.page]
        if rect is None:
            width, height = 180.0, 54.0
            if values["kind"] == "image":
                try:
                    picture = fitz.Pixmap(values["image"])
                except Exception:
                    raise ValueError(_("No se pudo leer la imagen del sello.")) from None
                width = 160.0
                height = width * picture.height / max(1, picture.width)
                if height > 160:
                    width, height = width * 160 / height, 160.0
            if values.get("turn") in (90, 270):
                width, height = height, width
            # The stamp's size is what the user sees, so build it on the rotated page and map it back.
            visual_bounds = page.rect
            visual_point = fitz.Point(point) * page.rotation_matrix
            width, height = min(width, visual_bounds.width), min(height, visual_bounds.height)
            left = min(max(visual_point.x - width / 2, visual_bounds.x0), visual_bounds.x1 - width)
            top = min(max(visual_point.y - height / 2, visual_bounds.y0), visual_bounds.y1 - height)
            rect = fitz.Rect(left, top, left + width, top + height) * page.derotation_matrix
        self.change(lambda: self.engine.add_stamp(self.page, rect, **values))
        self.set_mode("select")
        self.statusBar().showMessage(_("Sello colocado; puedes deshacerlo con Ctrl+Z"))

    def check_document(self):
        report = self.external_job("check", _("Comprobando documento"))
        if report is None:
            return
        dialog = doctools_dialogs.DocumentCheckDialog(report, self)

        def go(finding):
            self.goto(finding["page"])
            dialog.accept()

        dialog.findingActivated.connect(go)
        dialog.exec()

    def compare_text(self):
        path, _filter = QFileDialog.getOpenFileName(self, _("Comparar texto con otro PDF"), "", "PDF (*.pdf)")
        if not path:
            return
        other = PDFEngine()
        try:
            if not self.open_with_password(other, path):
                return
            report = self.with_redaction_gate(lambda allow: self.busy(_("Comparando texto…"), lambda: self.engine.compare_text(other.doc, allow_pending_redactions=allow)), _("Continuar de todos modos"))
            if report is CANCELLED:
                return
        finally:
            other.close()
        name = Path(self.engine.path).name if self.engine.path else _("Sin título")
        self.text_report(_("Comparación de texto"), format_text_comparison(report, name, Path(path).name))
