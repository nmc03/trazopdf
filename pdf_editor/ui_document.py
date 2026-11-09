from __future__ import annotations

import json
import time
from datetime import datetime
from uuid import uuid4

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFileDialog, QLabel, QMessageBox
from pathlib import Path

from . import recovery
from .engine import PDFEngine, SecurityPreservationError
from .lang import _
from .theme import current_tokens
from .toast import notify, notify_file
from .ui_support import CANCELLED

AUTOSAVE_MS = 60_000
STATE_POLL_MS = 500
VIEW_MEMORY_LIMIT = 50
VIEW_FIT_LOCK = 0.5
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp"}


class UiDocumentMixin:
    """Open, save, close and new document, drag and drop, close event, recovery copies."""

    recovery_queue = ()
    save_state_label = None
    backed_up = frozenset()

    def confirm_discard(self):
        if not self.view.commit_editor():
            return False
        if not self.engine.dirty:
            self.forget_recovery_copy()
            return True
        name = Path(self.engine.path).name if self.engine.path else _("Documento sin título")
        save, discard = _("Guardar"), _("No guardar")
        picked = self.choose(_("Cambios sin guardar"), _("¿Guardar los cambios de «{name}»?", name=name), [save, discard, _("Cancelar")], QMessageBox.Icon.Question,
                             _("Si no guardas, se perderán los cambios hechos desde el último guardado."), cancel=_("Cancelar"))
        if picked == save:
            return bool(self.save())
        if picked == discard:
            self.forget_recovery_copy()
            return True
        return False

    def confirm_all_tabs(self):
        """Quitting: asks about each modified document in turn; one Cancelar keeps the application open."""
        if not self.view.commit_editor():
            return False
        current = self.active_tab
        for tab in [t for t in self.documents if t.engine.dirty]:
            if not self.activate_tab(self.documents.index(tab)) or not self.confirm_discard():
                return False
        for tab in self.documents:
            if not tab.engine.dirty:
                recovery.discard(tab.recovery_id)
        if current in self.documents:
            self.activate_tab(self.documents.index(current))
        return True

    def open_file(self):
        path, _filter = QFileDialog.getOpenFileName(self, _("Abrir documento"), "", _("Documentos PDF (*.pdf);;Todos los archivos (*)"))
        if path:
            self.open_path(path)

    def open_path(self, path):
        if not Path(path).is_file():
            self.missing_recent(path)
            return
        existing = self.tab_for_path(path)
        if existing is not None:
            self.activate_tab(self.documents.index(existing))
            return
        engine = PDFEngine()
        if not self.open_with_password(engine, path):
            return
        self.remember_view()
        self.add_tab(engine)
        remembered = self.saved_view(self.engine.path)
        self.page = remembered["page"] if remembered else 0
        self.search_results = []
        self.remember_recent(path)
        self.refresh()
        if remembered:
            self.apply_view_memory(remembered)
        else:
            QTimer.singleShot(0, self.fit_width)
        self.offer_owner_password()

    # Per-file view memory: page, zoom and scroll.

    def view_memory(self):
        try:
            data = json.loads(self.settings.value("viewMemory", "{}", type=str) or "{}")
        except (TypeError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def saved_view(self, path):
        """The remembered view of a file as a dict with page, zoom, mode and scroll, or None."""
        if not path:
            return None
        entry = self.view_memory().get(str(Path(path).resolve()))
        if not isinstance(entry, dict):
            return None
        try:
            page, zoom = int(entry["page"]), int(entry["zoom"])
            scroll = [int(entry["scroll"][0]), int(entry["scroll"][1])]
        except (KeyError, TypeError, ValueError, IndexError):
            return None
        mode = entry.get("mode") if entry.get("mode") in ("width", "page", "actual", "manual") else "manual"
        if not self.has_doc() or not 0 <= page < self.engine.page_count:
            return None
        return {"page": page, "zoom": zoom, "mode": mode, "scroll": scroll}

    def remember_view(self):
        """Stores page, zoom and scroll of the open file (at most VIEW_MEMORY_LIMIT files)."""
        if not self.has_doc() or not self.engine.path:
            return
        view = self.view
        if self.is_continuous():
            self.continuous_view_moved()
        data = self.view_memory()
        key = str(Path(self.engine.path).resolve())
        data.pop(key, None)
        data[key] = {"page": self.page, "zoom": self.zoom.value(), "mode": self.zoom_mode,
                     "scroll": [view.horizontalScrollBar().value(), view.verticalScrollBar().value()]}
        while len(data) > VIEW_MEMORY_LIMIT:
            data.pop(next(iter(data)))
        self.settings.setValue("viewMemory", json.dumps(data))

    def apply_view_memory(self, entry):
        """Puts the remembered zoom and scroll back once the document is shown."""
        self.fit_locked_until = time.monotonic() + VIEW_FIT_LOCK
        self.zoom_mode = entry["mode"]
        self.set_zoom_value(entry["zoom"])
        self.render_page()
        self.after_zoom_change()
        self.restore_scroll(entry["scroll"])
        QTimer.singleShot(0, lambda: self.restore_scroll(entry["scroll"]))

    def restore_scroll(self, scroll):
        if not self.has_doc():
            return
        self.view.horizontalScrollBar().setValue(scroll[0])
        self.view.verticalScrollBar().setValue(scroll[1])
        if self.is_continuous():
            self.continuous_view_moved()

    def missing_recent(self, path):
        """The file is gone: say so, and offer to drop it from the recent list."""
        name = Path(path).name
        notify(self, _("No se encuentra {name}", name=name), kind="error", actions=[(_("Quitar de recientes"), lambda: self.forget_recent(path))],
               details=str(path), timeout=0)

    def forget_recent(self, path):
        recent = self.settings.value("recent", [], type=list)
        self.settings.setValue("recent", [x for x in recent if x != path])
        self.refresh_recent()

    def remember_recent(self, path):
        path = str(Path(path).resolve())
        recent = self.settings.value("recent", [], type=list)
        kept = ([path] + [x for x in recent if x != path])[:8]
        self.settings.setValue("recent", kept)
        used = {k: v for k, v in self.recent_used().items() if k in kept}
        used[path] = time.time()
        self.settings.setValue("recentUsed", json.dumps(used))

    def refresh_recent(self):
        self.fill_recents()

    def new_file(self):
        self.remember_view()
        with self.new_tab():
            self.engine.new()
        self.refresh()
        QTimer.singleShot(0, self.fit_width)

    def close_document(self):
        if self.active_tab is not None:
            self.close_tab(self.active_tab)

    def save(self, save_as=False):
        if not self.view.commit_editor():
            return False
        if self.engine.doc.get_sigflags() > 0 and self.engine.doc.get_sigflags() & 2:
            if QMessageBox.warning(self, _("Documento con firma digital"), _("Volver a guardar este PDF puede invalidar sus firmas. ¿Quieres continuar?"), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return False
        path = self.engine.path
        from_dialog = False
        if save_as or not path:
            path, _filter = QFileDialog.getSaveFileName(self, _("Guardar PDF"), path or "Documento.pdf", "PDF (*.pdf)")
            from_dialog = True
        if not path:
            return False
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
            if from_dialog and Path(path).exists():
                if QMessageBox.question(self, _("Reemplazar archivo"), _("Ya existe un archivo en:\n{path}\n\n¿Quieres reemplazarlo?", path=path), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                    return False
        self.backup_before_write(path)
        if not self.write_document(path):
            return False
        self.forget_recovery_copy()
        self.remember_recent(self.engine.path)
        self.refresh()
        notes = " ".join(self.engine.save_notes)
        self.statusBar().showMessage(_("Guardado: {path}", path=self.engine.path) + (f"  ·  {notes}" if notes else ""))
        notify_file(self, _("Guardado en {name}", name=Path(self.engine.path).name), self.engine.path, details=" ".join(notes))
        return True

    def backup_before_write(self, path):
        """Keep a .bak of the file about to be replaced: once per session and file, unless backups are off."""
        if not self.settings.value("backupOnSave", True, type=bool):
            return
        key = str(Path(path).resolve())
        if key in self.backed_up or not Path(path).is_file():
            return
        try:
            recovery.make_backup(path)
        except OSError as error:
            raise ValueError(_("No se pudo crear la copia de seguridad antes de guardar: {error}", error=error)) from error
        self.backed_up = self.backed_up | {key}

    def save_copy(self):
        """Guardar una copia…: writes another file with the same protection. The open document stays as it is."""
        if not self.view.commit_editor():
            return False
        stem = Path(self.engine.path).stem if self.engine.path else "Documento"
        path, _filter = QFileDialog.getSaveFileName(self, _("Guardar una copia"), _("{stem} copia.pdf", stem=stem), "PDF (*.pdf)")
        if not path:
            return False
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        if self.engine.path and Path(path).resolve() == Path(self.engine.path).resolve():
            raise ValueError(_("Para guardar sobre el archivo abierto usa Guardar; esta opción necesita otro nombre."))
        try:
            data = self.with_redaction_gate(lambda allow: self.engine.copy_bytes(allow_pending_redactions=allow))
        except SecurityPreservationError:
            QMessageBox.warning(self, _("No se puede guardar la copia"), _("No se puede conservar la protección del documento en la copia. El documento abierto no ha cambiado."))
            return False
        if data is CANCELLED:
            return False
        PDFEngine._atomic_write(path, data)
        self.statusBar().showMessage(_("Copia guardada: {path}", path=path))
        notify_file(self, _("Copia guardada en {name}", name=Path(path).name), path)
        return True

    def revert_document(self):
        """Revertir a la versión guardada: reloads the file on disk after confirmation."""
        if not self.view.commit_editor():
            return False
        path = self.engine.path
        if not path or not Path(path).is_file():
            notify(self, _("Este documento todavía no se ha guardado; no hay versión a la que volver."), kind="info")
            return False
        revert = _("Revertir")
        picked = self.choose(_("Revertir documento"), _("¿Volver a la versión guardada de «{name}»?", name=Path(path).name), [revert, _("Cancelar")], QMessageBox.Icon.Warning,
                             _("Se perderán los cambios hechos desde el último guardado."), cancel=_("Cancelar"))
        if picked != revert:
            return False
        if not self.open_with_password(self.engine, path):
            return False
        self.engine.path = str(Path(path).resolve())
        self.page = 0
        self.search_results = []
        self.forget_recovery_copy()
        self.refresh()
        QTimer.singleShot(0, self.fit_width)
        self.statusBar().showMessage(_("Documento revertido a la versión guardada: {path}", path=path))
        return True

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.show_drop_overlay()

    def dragLeaveEvent(self, event):
        self.hide_drop_overlay()
        event.accept()

    def show_drop_overlay(self):
        overlay = getattr(self, "drop_overlay", None)
        if overlay is None:
            overlay = QLabel(_("Suelta para abrir"), self)
            overlay.setObjectName("DropOverlay")
            overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
            overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            self.drop_overlay = overlay
        tokens = current_tokens()
        overlay.setStyleSheet(f"QLabel#DropOverlay {{ background: {tokens['accentsoft']}; color: {tokens['accent']}; border: 3px dashed {tokens['accent']}; border-radius: 14px; font-size: 22px; font-weight: 600; }}")
        overlay.setGeometry(self.rect().adjusted(12, 12, -12, -12))
        overlay.show()
        overlay.raise_()

    def hide_drop_overlay(self):
        overlay = getattr(self, "drop_overlay", None)
        if overlay is not None:
            overlay.hide()

    def dropEvent(self, event):
        self.hide_drop_overlay()
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            event.acceptProposedAction()
            self.run(lambda: self.handle_dropped(paths))

    def handle_dropped(self, paths):
        """One file opens; several PDFs offer to open the first or merge them; images become pages."""
        images = [p for p in paths if Path(p).suffix.lower() in IMAGE_SUFFIXES]
        documents = [p for p in paths if p not in images]
        if not documents:
            return self.drop_images(images)
        if len(documents) > 1:
            combine, first = _("Combinar"), _("Abrir el primero")
            picked = self.choose(_("Varios archivos"), _("Has soltado {n} archivos PDF.", n=len(documents)), [combine, first, _("Cancelar")], QMessageBox.Icon.Question,
                                 _("Combinar crea un documento nuevo con todas las páginas, en el orden soltado."), cancel=_("Cancelar"))
            if picked == combine:
                self.merge_as_new_document(documents)
            elif picked == first:
                self.open_path(documents[0])
        else:
            self.open_path(documents[0])
        if images:
            notify(self, _("Las imágenes no se han insertado. Suéltalas aparte para añadirlas como páginas."), kind="info")

    def drop_images(self, images):
        """Images dropped on an open document become pages after the current one; without a document they make a new one."""
        if not self.has_doc():
            with self.new_tab():
                self.engine.from_images(images)
            self.refresh()
            QTimer.singleShot(0, self.fit_width)
            return
        start = self.page

        def insert():
            index = start
            for image in images:
                index = self.engine.insert_image_page(index, image)
            return index

        last = self.change(insert)
        notify(self, _("{n} imagen(es) insertadas como página(s)", n=len(images)), actions=[(_("Deshacer"), self.undo)])
        self.goto(start + 1 if last > start else start)

    def closeEvent(self, event):
        try:
            allowed = self.confirm_all_tabs()
        except Exception as error:
            event.ignore()
            try:
                QMessageBox.warning(self, _("No se pudo cerrar"), _("No se pudo completar el cierre, así que la ventana sigue abierta. El documento permanece abierto y no se ha descartado ningún cambio. Si el guardado ya se había escrito en disco, el archivo puede estar guardado.\n\nDetalle: ") + (str(error) or type(error).__name__))
            except Exception:
                pass
            return
        if not allowed:
            event.ignore()
            return
        try:
            self.remember_view()
            self.settings.setValue("geometry", self.saveGeometry())
            self.settings.setValue("pagesCollapsed", self.pages_collapsed)
        except Exception:
            pass
        for tab in self.documents:
            try:
                tab.engine.close()
            except Exception:
                pass
        event.accept()

    # Recovery copies, save-state indicator and startup banners.

    def start_recovery(self):
        """Startup: status indicator, autosave timer, and banners for copies left by earlier sessions."""
        if self.save_state_label is not None:
            return
        self.save_state_label = QLabel()
        self.save_state_label.setObjectName("SaveState")
        self.statusBar().addPermanentWidget(self.save_state_label)
        self.autosave_timer = QTimer(self)
        self.autosave_timer.timeout.connect(self.autosave_now)
        self.autosave_timer.start(AUTOSAVE_MS)
        self.state_timer = QTimer(self)
        self.state_timer.timeout.connect(self.update_save_state)
        self.state_timer.start(STATE_POLL_MS)
        self.update_save_state()
        try:
            self.recovery_queue = recovery.orphans()
        except OSError:
            self.recovery_queue = []
        self.show_next_recovery()

    def save_state_text(self):
        if not self.has_doc():
            return ""
        if self.engine.dirty:
            if self.autosave_at:
                return _("Autoguardado a las {time}", time=f"{self.autosave_at:%H:%M}")
            return _("Sin guardar")
        return _("Guardado") if self.engine.path else ""

    def update_save_state(self):
        self.refresh_tab_bar()
        if self.save_state_label is None:
            return
        text = self.save_state_text()
        if self.save_state_label.text() != text:
            self.save_state_label.setText(text)

    def autosave_now(self):
        """Write the recovery copy of every document with unsaved changes. The original files are never touched."""
        saved = False
        for tab in list(self.documents):
            saved = self.autosave_tab(tab) or saved
        return saved

    def autosave_tab(self, tab):
        engine = tab.engine
        if engine.doc is None or engine.doc.is_closed or not engine.dirty:
            return False
        try:
            data = recovery.recovery_bytes(engine)
            if data is None:
                if not tab.autosave_warned:
                    tab.autosave_warned = True
                    notify(self, _("«{title}» está protegido: no se hace autoguardado.", title=tab.title()), kind="info", timeout=0)
                return False
            tab.recovery_id = tab.recovery_id or uuid4().hex
            name = Path(engine.path).name if engine.path else _("Documento sin título")
            recovery.write_copy(tab.recovery_id, data, original=engine.path, name=name, protected=engine.is_protected)
        except Exception as error:
            self.statusBar().showMessage(_("No se pudo autoguardar: {error}", error=error))
            return False
        tab.autosave_at = datetime.now()
        self.update_save_state()
        return True

    def forget_recovery_copy(self):
        """The copy is no longer needed: the file was saved, or its changes were discarded."""
        recovery.discard(self.recovery_id)
        self.recovery_id = None
        self.autosave_at = None
        self.autosave_warned = False
        self.update_save_state()

    def show_next_recovery(self):
        if not self.recovery_queue:
            return
        entry = self.recovery_queue[0]
        name = entry.get("name") or _("Documento sin título")
        try:
            when = _(", guardado a las {time}", time=f"{datetime.fromisoformat(entry['saved_at']):%H:%M}")
        except (KeyError, TypeError, ValueError):
            when = ""
        text = _("Hay un documento sin guardar de una sesión anterior: «{name}»{when}.", name=name, when=when)
        notify(self, text, kind="info", timeout=0,
               actions=[(_("Recuperar"), lambda: self.resolve_recovery(entry, True)), (_("Descartar"), lambda: self.resolve_recovery(entry, False))])

    def resolve_recovery(self, entry, recover):
        self.recovery_queue = [item for item in self.recovery_queue if item["id"] != entry["id"]]
        if recover:
            self.run(lambda: self.recover_entry(entry))
        else:
            recovery.discard(entry["id"])
        self.show_next_recovery()

    def recover_entry(self, entry):
        """Open the copy as the modified document. Its original path is kept, so Guardar writes there only on request."""
        self.remember_view()
        with self.new_tab():
            if not self.open_with_password(self.engine, entry["pdf"]):
                return False
            original = entry.get("original")
            self.engine.path = str(Path(original).resolve()) if original else None
            self.engine.dirty = True
            self.recovery_id = entry["id"]
            self.autosave_at = None
        self.refresh()
        QTimer.singleShot(0, self.fit_width)
        target = original or _("una ruta nueva")
        notify(self, _("Documento recuperado. Los cambios no están guardados; Guardar escribirá en {target}.", target=target), kind="info")
        self.update_save_state()
        return True
