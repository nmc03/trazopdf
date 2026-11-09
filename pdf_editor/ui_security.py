from __future__ import annotations

from PySide6.QtWidgets import QApplication, QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QLabel, QLineEdit, QMessageBox, QVBoxLayout
from pathlib import Path

from . import doctools_dialogs
from .engine import PendingRedactionsError, SecurityPreservationError, TimestampError
from .lang import _, ntext
from .signing import make_timestamper
from .signing_ui import SignatureAppearanceDialog, SigningOptionsDialog
from .ui_support import CANCELLED


MAX_PASSWORD_ATTEMPTS = 5


class PasswordDialog(QDialog):
    """Asks for a password; a wrong one is reported inline and the dialog stays open, up to a limit."""

    def __init__(self, parent, title, prompt, check=None, max_attempts=MAX_PASSWORD_ATTEMPTS):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(380)
        self.check, self.max_attempts, self.attempts, self.password = check, max_attempts, 0, None
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(prompt))
        self.edit = QLineEdit()
        self.edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit.setAccessibleName(prompt)
        self.edit.textChanged.connect(lambda: self.error.setText(""))
        layout.addWidget(self.edit)
        self.show_box = QCheckBox(_("Mostrar contraseña"))
        self.show_box.toggled.connect(lambda on: self.edit.setEchoMode(QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
        layout.addWidget(self.show_box)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setObjectName("passwordError")
        self.error.setStyleSheet("color: #c0392b;")
        layout.addWidget(self.error)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(_("Aceptar"))
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(_("Cancelar"))
        self.buttons.accepted.connect(self.submit)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    @property
    def exhausted(self):
        return self.attempts >= self.max_attempts

    def submit(self):
        if self.exhausted:
            return
        text = self.edit.text()
        if self.check is None or self.check(text):
            self.password = text
            self.accept()
            return
        self.attempts += 1
        if self.exhausted:
            self.error.setText(_("Demasiados intentos fallidos. Cierra este cuadro y vuelve a intentarlo más tarde."))
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        else:
            left = self.max_attempts - self.attempts
            self.error.setText(ntext(left, "Contraseña incorrecta. Te quedan 1 intento.", "Contraseña incorrecta. Te quedan {n} intentos."))
        self.edit.selectAll()
        self.edit.setFocus()


class UiSecurityMixin:
    """Protection, passwords, redaction gate, writing the document and signatures."""

    def ask_pending(self, error, anyway=None):
        """Pending redactions block the output. Returns "apply", "anyway" or None (cancel)."""
        count = len(error.pending)
        mark = ntext(count, "1 censura sin aplicar; el texto bajo ella sigue en el archivo.", "{n} censuras sin aplicar; el texto bajo ellas sigue en el archivo.")
        apply = _("Aplicar censuras ahora")
        anyway = _(anyway) if anyway else _("Guardar de todos modos")
        picked = self.choose(_("Censuras sin aplicar"), _("Hay {mark}", mark=mark), [apply, anyway, _("Cancelar")], QMessageBox.Icon.Warning,
                             _("Si continúas sin aplicarlas, quien reciba el archivo podrá recuperar ese texto."), cancel=_("Cancelar"))
        return "apply" if picked == apply else "anyway" if picked == anyway else None

    def with_redaction_gate(self, operation, anyway=None):
        """Run operation(allow_pending) and handle unapplied redactions. Returns its result, or CANCELLED."""
        allow = False
        while True:
            try:
                return operation(allow)
            except PendingRedactionsError as error:
                choice = self.ask_pending(error, anyway)
                if choice == "apply":
                    self.change(self.engine.apply_redactions)
                elif choice == "anyway":
                    allow = True
                else:
                    return CANCELLED

    def confirm_unprotected_output(self, what):
        """F4: outputs of a protected document carry no password; tell the user before writing them."""
        if not self.engine.is_protected:
            return True
        return QMessageBox.question(self, _("Documento protegido"), _("Este documento está protegido con contraseña. {what} no tendrá contraseña ni restricciones. ¿Quieres continuar?", what=what),
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    def ask_password(self, title, prompt, check=None):
        """Password prompt with inline errors. Returns the accepted password, or None if cancelled."""
        dialog = PasswordDialog(self, title, prompt, check)
        return dialog.password if dialog.exec() == QDialog.DialogCode.Accepted else None

    def open_with_password(self, engine, path):
        """engine.open, asking for the password when the file needs one. False if the user gives up."""
        try:
            engine.open(path, "")
            return True
        except ValueError as error:
            if not self._needs_password(error):
                raise

        def attempt(password):
            try:
                engine.open(path, password)
                return True
            except ValueError as error:
                if not self._needs_password(error):
                    raise
                return False

        return self.ask_password(_("Documento protegido"), _("Este documento está protegido. Introduce la contraseña:"), attempt) is not None

    @staticmethod
    def _needs_password(error):
        text = str(error)
        return "Contraseña incorrecta o requerida" in text or _("Contraseña incorrecta o requerida") in text

    def offer_owner_password(self):
        """Opened with restrictions but without owner rights: they can only be kept on save with that password."""
        if not (self.engine.has_restrictions and not self.engine.has_owner_rights):
            return
        unlock = _("Contraseña de propietario…")
        while self.choose(_("Documento con restricciones"),
                          _("Este documento tiene restricciones (impresión, edición o copia). Para poder guardarlo conservándolas, introduce la contraseña de propietario."),
                          [unlock, _("Ahora no")], QMessageBox.Icon.Information, cancel=_("Ahora no")) == unlock:
            if self.ask_password(_("Contraseña de propietario"), _("Contraseña de propietario:"), self.engine.unlock_owner) is None:
                return
            self.statusBar().showMessage(_("Contraseña de propietario aceptada; las restricciones se conservarán al guardar"))
            return

    def write_document(self, path):
        """engine.save with the recovery dialogs for pending redactions and lost protection."""
        allow = False
        while True:
            try:
                self.engine.save(path, allow_pending_redactions=allow)
                return True
            except PendingRedactionsError as error:
                choice = self.ask_pending(error)
                if choice == "apply":
                    self.change(self.engine.apply_redactions)
                elif choice == "anyway":
                    allow = True
                else:
                    return False
            except SecurityPreservationError as error:
                outcome = self.resolve_security(error, allow)
                if outcome != "retry":
                    return outcome

    def resolve_security(self, error, allow_pending):
        """Saving would drop the document's protection. Returns "retry", True (saved another way) or False."""
        owner = _("Introducir contraseña de propietario")
        fresh = _("Proteger con contraseñas nuevas")
        plain = _("Guardar copia sin protección")
        if error.reason == "owner_unknown":
            text = _("Este documento tiene restricciones y no se conoce su contraseña de propietario, así que no se pueden conservar al guardar.")
            options = [owner, fresh, plain, _("Cancelar")]
        else:
            text = _("El documento se abrió con la contraseña de propietario y no con la de apertura, que no se puede recuperar para conservarla al guardar.")
            options = [fresh, plain, _("Cancelar")]
        picked = self.choose(_("No se puede conservar la protección"), text, options, QMessageBox.Icon.Warning, cancel=_("Cancelar"))
        if picked == owner:
            return "retry" if self.ask_password(_("Contraseña de propietario"), _("Contraseña de propietario:"), self.engine.unlock_owner) is not None else False
        if picked == fresh:
            return bool(self.protect())
        if picked == plain:
            return self.save_plain_copy(allow_pending)
        return False

    def save_plain_copy(self, allow_pending=False):
        if QMessageBox.warning(self, _("Guardar copia sin protección"), _("La copia no tendrá contraseña ni restricciones. ¿Quieres continuar?"),
                               QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return False
        stem = Path(self.engine.path).stem if self.engine.path else "Documento"
        path, _filter = QFileDialog.getSaveFileName(self, _("Guardar copia sin protección"), _("{stem} sin contraseña.pdf", stem=stem), "PDF (*.pdf)")
        if not path:
            return False
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        if self.engine.path and Path(path).resolve() == Path(self.engine.path).resolve():
            raise ValueError(_("Elige otro nombre para conservar el archivo protegido."))
        outcome = self.with_redaction_gate(lambda allow: self.engine.save_unprotected_copy(path, allow_pending_redactions=allow or allow_pending))
        return outcome is not CANCELLED

    def protect(self):
        """Save a copy with new passwords. Returns True when the file was written."""
        dialog = doctools_dialogs.ProtectDialog(self)
        if not dialog.exec():
            return False
        values = dialog.values()
        path, _filter = QFileDialog.getSaveFileName(self, _("Guardar copia protegida"), _("Documento protegido.pdf"), "PDF (*.pdf)")
        if not path:
            return False
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        owner = values["owner"]
        permissions = doctools_dialogs.permissions_for(values["restrict"])
        used = self.with_redaction_gate(lambda allow: self.engine.protect(path, values["password"], owner or None, permissions=permissions, allow_pending_redactions=allow))
        if used is CANCELLED:
            return False
        self.remember_recent(self.engine.path)
        self.refresh()
        self.statusBar().showMessage(_("Guardado con contraseña: {path}", path=self.engine.path))
        if not owner and used:
            self.show_generated_password(used)
        return True

    def show_generated_password(self, password):
        copy = _("Copiar")
        picked = self.choose(_("Contraseña de propietario"), _("Contraseña de propietario generada: {password}\n\nGuárdala; no se volverá a mostrar.", password=password),
                             [copy, _("Cerrar")], QMessageBox.Icon.Information, cancel=_("Cerrar"))
        if picked == copy:
            QApplication.clipboard().setText(password)
            self.statusBar().showMessage(_("Contraseña de propietario copiada al portapapeles"))

    def unprotect(self):
        if self.engine.has_restrictions and QMessageBox.question(
                self, _("Quitar restricciones"), _("Este documento tiene restricciones (impresión, edición o copia). La copia no tendrá contraseña ni restricciones. ¿Quieres continuar?"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        path, _filter = QFileDialog.getSaveFileName(self, _("Guardar copia sin protección"), _("Documento sin contraseña.pdf"), "PDF (*.pdf)")
        if path:
            if not path.lower().endswith(".pdf"):
                path += ".pdf"
            if self.engine.path and Path(path).resolve() == Path(self.engine.path).resolve():
                raise ValueError(_("Elige otro nombre para conservar la copia protegida."))
            if self.with_redaction_gate(lambda allow: self.engine.save_unprotected_copy(path, allow_pending_redactions=allow)) is CANCELLED:
                return
            self.remember_recent(self.engine.path)
            self.refresh()
            self.statusBar().showMessage(_("Copia sin contraseña guardada: {path}", path=self.engine.path))

    def sign(self):
        pfx, _filter = QFileDialog.getOpenFileName(self, _("Certificado de firma"), "", _("Certificado PKCS#12 (*.pfx *.p12)"))
        if not pfx:
            return
        password = self.ask_password(_("Certificado"), _("Contraseña del certificado:"))
        if password is None:
            return
        from .signing import load_signer, signer_name
        try:
            who = signer_name(load_signer(pfx, password).signing_cert)
        except ValueError as error:
            QMessageBox.warning(self, _("Certificado de firma"), str(error))
            return
        look = SignatureAppearanceDialog(self, self.engine.doc, self.engine.signature_count(), who)
        if look.exec() != QDialog.DialogCode.Accepted:
            return
        options = SigningOptionsDialog(self, self.settings)
        if options.exec() != QDialog.DialogCode.Accepted:
            return
        stamp_url = options.timestamp_url()
        if not self.confirm_unprotected_output(_("La copia firmada")):
            return
        output, _filter = QFileDialog.getSaveFileName(self, _("Guardar copia firmada"), _("Documento firmado.pdf"), "PDF (*.pdf)")
        if output:
            self.sign_to(output, pfx, password, stamp_url, look.field_spec(), look.appearance())

    def sign_to(self, output, pfx, password, stamp_url, field_spec=None, appearance=None):
        stamper = make_timestamper(stamp_url) if stamp_url else None
        try:
            signed = self.with_redaction_gate(lambda allow: self.busy(_("Firmando documento…"), lambda: self.engine.sign_pkcs12(output, pfx, password, reason="Firma personal con TrazoPDF" if appearance is None else (appearance.reason or ""), allow_pending_redactions=allow, timestamper=stamper, field_spec=field_spec, appearance=appearance)), _("Continuar de todos modos"))
        except TimestampError as error:
            box = QMessageBox.question(self, _("Sello de tiempo"), _("{error}\n\n¿Quieres firmar sin sello de tiempo?", error=error),
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if box == QMessageBox.StandardButton.Yes:
                self.sign_to(output, pfx, password, None, field_spec, appearance)
            return
        if signed is CANCELLED:
            return
        QMessageBox.information(self, _("Documento firmado"), _("Copia firmada guardada en:\n{output}\n\nLas ediciones posteriores pueden invalidar la firma.", output=output))

    def signatures(self):
        self.text_report(_("Firmas del documento"), self.engine.inspect_signatures())
