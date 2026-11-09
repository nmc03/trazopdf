from __future__ import annotations

import ctypes
import json
import os
import sys
import tempfile
import threading

from PySide6.QtCore import QEventLoop, QProcess, QTimer, Qt
from PySide6.QtWidgets import QApplication, QProgressDialog
from pathlib import Path

from .engine import PDFEngine
from .i18n import friendly_error
from .lang import _
from .toast import notify
from .ui_support import CANCELLED, JOB_PREFIXES, claim_job_folder


class OperationCancelled(Exception):
    """Raised inside a busy worker when the user presses Cancelar."""


class UiJobsMixin:
    """Busy dialogs, background jobs and guarded runs."""

    def run(self, function):
        try:
            return function()
        except Exception as error:
            message, technical = friendly_error(error)
            notify(self, message, kind="error", details=technical)
            if hasattr(self, "view"):
                self.refresh()
            return None

    def run_action(self, key, handler):
        if self.view.editor and key in ("undo", "redo"):
            getattr(self.view.editor.document(), key)()
            return
        if not self.view.commit_editor():
            return
        handler()

    def busy(self, title, function):
        """Run function on a worker thread with a progress dialog that can cancel it.

        Cancel interrupts the worker at its next Python instruction and removes the files
        this call created. Returns CANCELLED when the user cancelled or the work failed midway.
        """
        progress = QProgressDialog(title, _("Cancelar"), 0, 0, self)
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        outcome = {}
        created = []
        cancelled = {"requested": False, "running": True}

        def track(frame, event, _arg):
            # Every engine write goes through PDFEngine._atomic_write; remember targets that did not exist yet.
            if event == "call" and frame.f_code.co_name == "_atomic_write":
                target = frame.f_locals.get("path")
                if target and not os.path.exists(target):
                    created.append(str(target))

        def work():
            sys.setprofile(track)
            try:
                outcome["value"] = function()
            except BaseException as error:
                outcome["error"] = error
            finally:
                sys.setprofile(None)

        def cancel():
            # Closing the dialog also emits canceled(); only a press while the work runs counts.
            if cancelled["requested"] or not cancelled["running"]:
                return
            cancelled["requested"] = True
            progress.setLabelText(_("Cancelando…"))
            progress.setCancelButton(None)
            if worker.is_alive():
                ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(worker.ident), ctypes.py_object(OperationCancelled))

        progress.canceled.connect(cancel)
        worker = threading.Thread(target=work, name="busy-operation", daemon=True)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        progress.show()
        worker.start()
        try:
            while worker.is_alive():
                QApplication.processEvents()
                worker.join(0.02)
        finally:
            cancelled["running"] = False
            QApplication.restoreOverrideCursor()
            progress.close()
            progress.deleteLater()
        error = outcome.get("error")
        if cancelled["requested"] or error is not None:
            for target in created:
                try:
                    os.remove(target)
                except OSError:
                    pass
            if cancelled["requested"] or isinstance(error, OperationCancelled):
                notify(self, _("Operación cancelada"), kind="info")
                return CANCELLED
            raise error
        return outcome.get("value")

    def external_job(self, operation, title, *, allow_pending=False, **parameters):
        """Run OCR/Office/optimize/check in another process while Qt remains responsive."""
        if operation in ("ocr", "compare") and not allow_pending:
            self.engine.require_no_pending_redactions()
        with tempfile.TemporaryDirectory(prefix=JOB_PREFIXES[0]) as temporary:
            folder = Path(temporary)
            claim_job_folder(folder)
            if operation in ("ocr", "compare", "optimize", "check"):
                PDFEngine._atomic_write(folder / "source.pdf", self.engine._bytes())
            request = {"operation": operation, "allow_pending": bool(allow_pending), **parameters}
            if self.engine.path:
                # The worker only sees the temporary copy, so tell it where the real document lives.
                request["reject_dirs"] = [str(Path(self.engine.path).resolve().parent)]
            (folder / "request.json").write_text(json.dumps(request), encoding="utf-8")
            process = QProcess(self)
            loop = QEventLoop(self)
            progress = QProgressDialog(title, _("Cancelar"), 0, 0, self)
            progress.setWindowModality(Qt.WindowModality.ApplicationModal)
            progress.setAutoClose(False)
            progress.setAutoReset(False)
            progress.setMinimumDuration(0)
            self.job_progress = progress
            def cancel():
                (folder / "cancel").touch()
                progress.setLabelText(_("Cancelando…"))
                progress.setCancelButton(None)
                progress.show()
            progress.canceled.connect(cancel)
            def update_progress():
                if progress.wasCanceled() and not (folder / "cancel").exists():
                    cancel()
                try:
                    state = json.loads((folder / "progress.json").read_text())
                    progress.setRange(0, state["total"])
                    progress.setValue(state["done"])
                    progress.setLabelText(_("{title} · página {done} de {total}", title=title, done=state['done'], total=state['total']))
                except (OSError, ValueError):
                    pass
            timer = QTimer(self)
            timer.timeout.connect(update_progress)
            timer.start(80)
            process.finished.connect(loop.quit)
            process.errorOccurred.connect(loop.quit)
            arguments = ["--worker", str(folder / "request.json")]
            if not getattr(sys, "frozen", False):
                arguments = ["-m", "pdf_editor", *arguments]
            progress.show()
            process.start(sys.executable, arguments)
            try:
                loop.exec()
                if not (folder / "result.json").exists():
                    error = bytes(process.readAllStandardError()).decode("utf-8", errors="replace")
                    raise ValueError(_("No se pudo completar el procesamiento: {detail}", detail=error or process.errorString()))
                result = json.loads((folder / "result.json").read_text())
                if result.get("cancelled") or (folder / "cancel").exists() or progress.wasCanceled():
                    notify(self, _("Operación cancelada; se conserva el documento anterior"), kind="info")
                    return None
                if not result.get("ok"):
                    raise ValueError(result.get("error") or _("Falló el procesamiento."))
                if operation in ("compare", "check"):
                    return result["report"]
                if operation == "optimize":
                    return result["report"], (folder / "output.pdf").read_bytes()
                return (folder / "output.pdf").read_bytes()
            finally:
                timer.stop()
                timer.deleteLater()
                progress.close()
                progress.deleteLater()
                process.deleteLater()
                self.job_progress = None
