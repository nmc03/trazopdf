"""Local PDF operations. Coordinates are unrotated PDF points; pages are zero based."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import csv
import difflib
import getpass
import io
import html
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from urllib.parse import urlsplit

import pymupdf as fitz
import secrets

from . import doctools
from .lang import _
from .signing import TimestampError  # noqa: F401  (re-exported)


class PendingRedactionsError(ValueError):
    """Unapplied redaction marks exist: the text underneath is still in the file."""

    def __init__(self, pending):
        self.pending = list(pending)
        super().__init__(
            _("Hay {count} marca(s) de censura sin aplicar. El contenido que cubren sigue "
              "presente en el archivo. Aplica las censuras antes de guardar o exportar.", count=len(self.pending)))


class SecurityPreservationError(ValueError):
    """Saving would lose or alter the document's passwords or restrictions.

    reason: "owner_unknown" (restricted file opened without the owner password)
    or "user_unknown" (opened with the owner password only; the open password
    cannot be recovered). restricted tells whether the file limits permissions.
    """

    def __init__(self, reason, restricted=True):
        self.reason = reason
        self.restricted = restricted
        super().__init__(
            _("Para guardar este documento protegido sin perder sus restricciones, ábrelo con la contraseña "
              "de propietario o guarda una copia sin protección de forma explícita."))


def default_author():
    """Name stored as the author of new annotations: the system user unless changed."""
    try:
        return getpass.getuser() or "Usuario"
    except Exception:
        return "Usuario"


_ALL_PERMISSIONS = (fitz.PDF_PERM_PRINT | fitz.PDF_PERM_MODIFY | fitz.PDF_PERM_COPY | fitz.PDF_PERM_ANNOTATE
                    | fitz.PDF_PERM_FORM | fitz.PDF_PERM_ACCESSIBILITY | fitz.PDF_PERM_ASSEMBLE | fitz.PDF_PERM_PRINT_HQ)


def encryption_info(doc):
    """Describe the /Encrypt dictionary of an opened document, or None if unencrypted.

    Read from the trailer: needs_pass and metadata are not reliable for files
    with an empty user password. Returns {"method", "perm", "restricted"}.
    """
    kind, value = doc.xref_get_key(-1, "Encrypt")
    if kind == "null" or not value:
        return None
    if kind == "xref":
        value = doc.xref_object(int(value.split()[0]))
    def number(key, default):
        found = re.search(r"/" + key + r"\s+(-?\d+)", value)
        return int(found.group(1)) if found else default
    version = number("V", 1)
    if version >= 5:
        method = fitz.PDF_ENCRYPT_AES_256
    elif version == 4:
        method = fitz.PDF_ENCRYPT_AES_128 if "AESV2" in value else fitz.PDF_ENCRYPT_RC4_128
    elif version == 2 or number("Length", 40) > 40:
        method = fitz.PDF_ENCRYPT_RC4_128
    else:
        method = fitz.PDF_ENCRYPT_RC4_40
    perm = number("P", -1)
    return {"method": method, "perm": perm, "restricted": (perm & _ALL_PERMISSIONS) != _ALL_PERMISSIONS}


_TOOLS = {
    "tesseract": ("PDFEDITOR_TESSERACT", "tesseract.exe", "tesseract",
                  [r"Tesseract-OCR\tesseract.exe"]),
    "soffice": ("PDFEDITOR_SOFFICE", "soffice.exe", "soffice",
                [r"LibreOffice\program\soffice.exe"]),
}


def bundled_tool_dirs():
    """Folders next to the application that may hold a bundled copy of a tool.

    Frozen: the folder of the executable and PyInstaller's data folder. Source
    checkout: the project root. A bundled tool lives in a subfolder named after it.
    """
    if getattr(sys, "frozen", False):
        folders = [Path(sys.executable).resolve().parent, Path(getattr(sys, "_MEIPASS", sys.executable)).resolve()]
    else:
        folders = [Path(__file__).resolve().parent.parent]
    return list(dict.fromkeys(folders))


def _tool_candidates(name):
    env_var, exe, posix_name, relatives = _TOOLS[name]
    if os.environ.get(env_var):
        yield "variable de entorno", os.environ[env_var]
    for folder in bundled_tool_dirs():
        yield "incluido", str(folder / name / (exe if os.name == "nt" else posix_name))
    if os.name == "nt":
        roots = [os.environ.get(v) for v in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432")]
        roots.append(str(Path(os.environ["LOCALAPPDATA"]) / "Programs") if os.environ.get("LOCALAPPDATA") else None)
        for root in dict.fromkeys(r for r in roots if r):
            for relative in relatives:
                yield "instalación", str(Path(root) / relative)
        try:
            import winreg
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths" + "\\" + exe) as key:
                        yield "registro", winreg.QueryValueEx(key, None)[0]
                except OSError:
                    pass
        except ImportError:
            pass
    else:
        for folder in ("/usr/bin", "/usr/local/bin", "/opt/homebrew/bin", "/snap/bin"):
            yield "instalación", str(Path(folder) / posix_name)
    # PATH last, parsed by hand: shutil.which also consults the current directory on Windows.
    for folder in os.environ.get("PATH", "").split(os.pathsep):
        folder = folder.strip().strip('"')
        if folder and os.path.isabs(folder):
            yield "PATH", str(Path(folder) / (exe if os.name == "nt" else posix_name))


def resolve_external_tool(name, reject_dirs=()):
    """Return (path, source) of a trusted external program, or (None, None).

    Order: PDFEDITOR_* variable, copy bundled next to the application, known install folders, registry App Paths, PATH.
    Relative results and programs sitting in the working directory or in any of
    reject_dirs (typically the opened document's folder) are refused.
    """
    banned = set()
    for folder in (os.getcwd(), *[d for d in reject_dirs if d]):
        try:
            banned.add(os.path.normcase(str(Path(folder).resolve())))
        except OSError:
            pass
    for source, candidate in _tool_candidates(name):
        candidate = os.path.expandvars(str(candidate).strip().strip('"'))
        if not candidate or not os.path.isabs(candidate):
            continue
        try:
            path = Path(candidate).resolve()
        except OSError:
            continue
        if not path.is_file() or os.path.normcase(str(path.parent)) in banned:
            continue
        if os.name != "nt" and not os.access(path, os.X_OK):
            continue
        return str(path), source
    return None, None


def external_tools(reject_dirs=()):
    """Resolved paths (or None) of OCR / Office converters, for diagnostics."""
    return {name: resolve_external_tool(name, reject_dirs)[0] for name in _TOOLS}


class PDFEngine:
    HISTORY_BYTES = 160 * 1024 * 1024
    HISTORY_COUNT = 24

    def __init__(self):
        self.author = default_author()
        self.doc = None
        self.path = None
        self.dirty = False
        self._undo = []
        self._redo = []
        self._coalesce_key = None
        self._coalesce_time = 0.0
        # Security state of the file on disk. None = unencrypted. Otherwise a dict
        # with method, perm (raw /P), restricted, user/owner (known passwords or None).
        self._security = None
        self._original_bytes = None
        self.generated_owner_password = None
        self.save_notes = []
        self.new()

    # Backwards compatible views of the security state.
    @property
    def _encrypted(self):
        return self._security is not None

    @property
    def is_protected(self):
        return self._security is not None

    @property
    def has_restrictions(self):
        return bool(self._security and self._security["restricted"])

    @property
    def has_owner_rights(self):
        """True when the owner password is known (restrictions can be preserved or changed)."""
        return bool(self._security) and self._security["owner"] is not None

    def external_tools(self):
        return external_tools(self._tool_reject_dirs())

    def _tool_reject_dirs(self, *extra):
        folders = [str(Path(e).resolve().parent) for e in extra]
        folders.extend(getattr(self, "reject_dirs", ()))
        if self.path:
            folders.append(str(Path(self.path).parent))
        return folders

    @property
    def page_count(self):
        return len(self.doc) if self.doc is not None else 0

    @property
    def can_undo(self):
        return bool(self._undo)

    @property
    def can_redo(self):
        return bool(self._redo)

    def _require(self):
        if self.doc is None:
            raise ValueError(_("No hay un documento abierto."))
        return self.doc

    def apply_processed(self, data):
        candidate = fitz.open(stream=data, filetype="pdf")
        if len(candidate) != self.page_count:
            candidate.close()
            raise ValueError(_("El procesamiento cambió inesperadamente el número de páginas."))
        with self._mutation():
            old, self.doc = self.doc, candidate
            old.close()

    def from_pdf_bytes(self, data):
        candidate = fitz.open(stream=data, filetype="pdf")
        if not len(candidate):
            candidate.close()
            raise ValueError(_("El documento convertido no contiene páginas."))
        self.close()
        self.doc, self.dirty = candidate, True

    def _page(self, index):
        if not isinstance(index, int) or not 0 <= index < self.page_count:
            raise ValueError(_("Número de página fuera del documento."))
        return self._require()[index]

    def _pages(self, pages):
        values = sorted(set(pages))
        if not values:
            raise ValueError(_("Selecciona al menos una página."))
        for index in values:
            self._page(index)
        return values

    def _rect(self, page, rect):
        rect = fitz.Rect(rect)
        bounds = page.rect * page.derotation_matrix
        if rect.is_empty or rect.is_infinite or not all(math.isfinite(v) for v in rect):
            raise ValueError(_("El área seleccionada no es válida."))
        rect &= bounds
        if rect.is_empty:
            raise ValueError(_("El área está fuera de la página."))
        return rect

    def _bytes(self):
        # Garbage collection can renumber live xrefs, invalidating the widget
        # selected by the UI before an operation begins. Compact only on save.
        return self._require().tobytes(garbage=0, deflate=True, encryption=fitz.PDF_ENCRYPT_NONE)

    def _snapshot(self):
        return self._bytes(), self.dirty

    def _restore(self, snapshot):
        candidate = fitz.open(stream=snapshot[0], filetype="pdf")
        old = self.doc
        self.doc = candidate
        self.dirty = snapshot[1]
        if old is not None:
            old.close()

    def _trim(self):
        while len(self._undo) + len(self._redo) > self.HISTORY_COUNT or sum(len(s[0]) for s in self._undo + self._redo) > self.HISTORY_BYTES:
            if self._undo:
                self._undo.pop(0)
            elif self._redo:
                self._redo.pop(0)
            else:
                break

    def checkpoint(self):
        self._undo.append(self._snapshot())
        self._redo.clear()
        self._trim()

    @contextmanager
    def _mutation(self, coalesce=None):
        # Consecutive changes with the same coalesce key within 0.8 s share one undo step.
        before = self._snapshot()
        merge = coalesce is not None and coalesce == self._coalesce_key and time.monotonic() - self._coalesce_time < 0.8
        try:
            yield
        except BaseException:
            self._restore(before)
            self._coalesce_key = None
            raise
        else:
            if not merge:
                self._undo.append(before)
            self._coalesce_key = coalesce
            self._coalesce_time = time.monotonic()
            self._redo.clear()
            self.dirty = True
            self._trim()

    def undo(self):
        self._coalesce_key = None
        if self._undo:
            now = self._snapshot()
            before = self._undo.pop()
            self._restore(before)
            self._redo.append(now)
            self._trim()

    def redo(self):
        self._coalesce_key = None
        if self._redo:
            now = self._snapshot()
            after = self._redo.pop()
            self._restore(after)
            self._undo.append(now)
            self._trim()

    def close(self):
        if self.doc is not None:
            self.doc.close()
        self.doc = None
        self.path = None
        self._original_bytes = None
        self._undo.clear()
        self._redo.clear()
        self.dirty = False
        self._security = None
        self.generated_owner_password = None
        self.save_notes = []

    def new(self):
        candidate = fitz.open()
        candidate.new_page()
        self.close()
        self.doc = candidate

    def open(self, path, password=""):
        raw = Path(path).read_bytes()
        security, needs_pass = self._probe_security(raw, password or "")
        candidate = fitz.open(stream=raw, filetype="pdf")
        try:
            # Probing happened on a separate document; authenticate the real one once.
            if needs_pass and not candidate.authenticate(password):
                raise ValueError(_("Contraseña incorrecta o requerida."))
            if not len(candidate):
                raise ValueError(_("El PDF no contiene páginas."))
        except BaseException:
            candidate.close()
            raise
        self.close()
        self.doc = candidate
        self.path = str(Path(path).resolve())
        self._original_bytes = raw
        self._security = security

    @staticmethod
    def _probe_security(raw, password):
        """Work out encryption and which credentials `password` represents.

        Runs on throwaway documents: calling needs_pass/authenticate repeatedly
        on the live document can break later reads in PyMuPDF.
        Returns (security descriptor or None, needs_pass).
        """
        with fitz.open(stream=raw, filetype="pdf") as probe:
            info = encryption_info(probe)
            needs_pass = bool(probe.needs_pass)
            if info is None and not needs_pass:
                return None, False
            if info is None:  # needs a password but the trailer is unreadable until unlocked
                info = {"method": fitz.PDF_ENCRYPT_AES_256, "perm": -1, "restricted": False}
            rc = probe.authenticate(password)
            if needs_pass and not rc:
                raise ValueError(_("Contraseña incorrecta o requerida."))
            user = password if (needs_pass and rc & 2) else ("" if not needs_pass else None)
            owner = password if rc & 4 else None
        return {**info, "user": user, "owner": owner}, needs_pass

    def unlock_owner(self, password):
        """Prove the owner password for the open document so restrictions can be kept on save.

        Returns True on success. Nothing changes when the password is wrong.
        """
        if self._security is None or self._original_bytes is None:
            return False
        with fitz.open(stream=self._original_bytes, filetype="pdf") as probe:
            rc = probe.authenticate(password or "")
        if not rc & 4:
            return False
        self._security["owner"] = password or ""
        if rc & 2 and self._security["user"] is None:
            self._security["user"] = password or ""
        return True

    @staticmethod
    def _atomic_write(path, data):
        target = Path(path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        # A single exclusive create fails promptly on denied destinations. On
        # Windows tempfile.mkstemp can retry denied paths thousands of times.
        tmp = str(target.parent / (".pdf-editor-" + uuid.uuid4().hex + ".tmp"))
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, target)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    @staticmethod
    def _new_owner_password():
        return secrets.token_urlsafe(24)  # 32 ASCII characters, within the 40 byte limit

    def _plan_security(self, password, owner_password, permissions):
        """Decide how to encrypt the output.

        Returns (plan or None, notes). plan = dict(method, user, owner, perm).
        None means write unencrypted (only on an explicit request or for a file
        that was never protected).

        Rules:
        * Implicit save (no password arguments) keeps the original method,
          permissions and credentials. Credentials we do not hold are never
          invented from the ones we do: a user password is never copied into the
          owner slot and vice versa.
        * If the owner password is unknown and the file restricts anything, or if
          the open password is unknown, SecurityPreservationError is raised.
          A file that grants every permission and whose open password is known
          is saved with the same open password and a fresh random owner password
          (the original one cannot be recovered); a note records this.
        * password="" without owner_password is an explicit request to remove
          protection. Any other password/owner_password is a new protection: the
          owner password is never inherited from the old document, and is generated
          when omitted.
        """
        sec = self._security
        explicit = password is not None or owner_password is not None
        if permissions is not None and not explicit and sec is None:
            raise ValueError(_("Las restricciones necesitan una contraseña."))
        if explicit:
            if password == "" and not owner_password:
                return None, [_("Se ha retirado la protección del documento.")]
            user = password or ""
            owner = owner_password
            notes = []
            if not owner:
                owner = self._new_owner_password()
                self.generated_owner_password = owner
                notes.append(_("Se ha generado una contraseña de propietario nueva."))
            if owner == user:
                raise ValueError(_("La contraseña de propietario debe ser distinta de la de apertura."))
            perm = permissions if permissions is not None else (sec["perm"] if sec else -1)
            return {"method": fitz.PDF_ENCRYPT_AES_256, "user": user, "owner": owner, "perm": int(perm)}, notes
        if sec is None:
            return None, []
        notes = []
        if sec["user"] is None:
            raise SecurityPreservationError("user_unknown", sec["restricted"])
        owner = sec["owner"]
        if owner is None:
            if sec["restricted"] or permissions is not None:
                raise SecurityPreservationError("owner_unknown", True)
            owner = self._new_owner_password()
            notes.append(_("La contraseña de propietario original no se puede conservar; se ha creado una nueva."))
        perm = permissions if permissions is not None else sec["perm"]
        return {"method": sec["method"], "user": sec["user"], "owner": owner, "perm": int(perm)}, notes

    @staticmethod
    def _verify_output(data, plan, pages):
        """Re-open the bytes about to be written and check them against the plan."""
        with fitz.open(stream=data, filetype="pdf") as check:
            info = encryption_info(check)
            if plan is None:
                if info is not None or check.needs_pass:
                    raise ValueError(_("Falló la comprobación del documento guardado."))
            else:
                # Reserved /P bits are normalised by MuPDF; compare the permission bits only.
                if info is None or info["method"] != plan["method"] or \
                        (info["perm"] & _ALL_PERMISSIONS) != (plan["perm"] & _ALL_PERMISSIONS):
                    raise ValueError(_("No se pudo comprobar el cifrado del documento guardado."))
        if plan is not None:
            # One authenticate per fresh handle: repeated attempts on one handle are unreliable.
            with fitz.open(stream=data, filetype="pdf") as check:
                if not check.authenticate(plan["user"]) & 2:
                    raise ValueError(_("No se pudo comprobar la contraseña de apertura del documento guardado."))
                if len(check) != pages:
                    raise ValueError(_("Falló la comprobación del documento guardado."))
            with fitz.open(stream=data, filetype="pdf") as check:
                if not check.authenticate(plan["owner"]) & 4:
                    raise ValueError(_("No se pudo comprobar la contraseña de propietario del documento guardado."))
            if plan["user"] != plan["owner"]:
                with fitz.open(stream=data, filetype="pdf") as check:
                    if check.authenticate(plan["user"]) & 4:
                        raise ValueError(_("La contraseña de apertura no debe conceder derechos de propietario."))
        else:
            with fitz.open(stream=data, filetype="pdf") as check:
                if len(check) != pages:
                    raise ValueError(_("Falló la comprobación del documento guardado."))

    def save(self, path=None, password=None, owner_password=None, permissions=None, *, allow_pending_redactions=False):
        """Write the document atomically.

        Returns the generated owner password when a new protection had to invent
        one (show it to the user once), otherwise None. See _plan_security.
        """
        target = path or self.path
        if not target:
            raise ValueError(_("Selecciona dónde guardar el documento."))
        self._gate_redactions(allow_pending_redactions)
        self.generated_owner_password = None
        plan, notes = self._plan_security(password, owner_password, permissions)
        generated = self.generated_owner_password
        data = self._encoded(plan)
        self._atomic_write(target, data)
        self.path = str(Path(target).resolve())
        self.save_notes = notes
        if plan:
            self._security = {"method": plan["method"], "perm": plan["perm"],
                              "restricted": (plan["perm"] & _ALL_PERMISSIONS) != _ALL_PERMISSIONS,
                              "user": plan["user"], "owner": plan["owner"]}
        else:
            self._security = None
        self._original_bytes = data
        self.dirty = False
        # Old history entries refer to content before the current saved revision.
        self._undo = [(b, True) for b, _ in self._undo]
        self._redo = [(b, True) for b, _ in self._redo]
        return generated

    def _encoded(self, plan, *, garbage=4, clean=True):
        """Bytes of the document under plan (None = unencrypted), verified before anyone writes them."""
        opts = dict(garbage=garbage, deflate=True, clean=clean)
        if plan:
            for secret in (plan["user"], plan["owner"]):
                if len(secret.encode("utf-8")) > 40:
                    raise ValueError(_("La contraseña admite un máximo de 40 bytes UTF-8."))
            opts.update(encryption=plan["method"], user_pw=plan["user"], owner_pw=plan["owner"], permissions=plan["perm"])
        else:
            opts["encryption"] = fitz.PDF_ENCRYPT_NONE
        self._require()
        self._write_layer_state()
        data = self.doc.tobytes(**opts)
        self._verify_output(data, plan, self.page_count)
        return data

    def copy_bytes(self, *, allow_pending_redactions=False):
        """Bytes of a copy that keeps the document's protection. Neither the document nor its path changes."""
        self._gate_redactions(allow_pending_redactions)
        plan, __ = self._plan_security(None, None, None)
        return self._encoded(plan, garbage=0, clean=False)

    def protect(self, path, user_password="", owner_password=None, permissions=None, *, allow_pending_redactions=False):
        """Save a protected copy with new credentials; returns the owner password in force.

        The previous document's passwords are never reused. When owner_password
        is omitted a strong random one is generated and returned.
        """
        if not (user_password or owner_password):
            raise ValueError(_("Indica una contraseña de apertura o de propietario."))
        generated = self.save(path, password=user_password or "", owner_password=owner_password,
                              permissions=permissions, allow_pending_redactions=allow_pending_redactions)
        return generated or owner_password

    def save_unprotected_copy(self, path, *, allow_pending_redactions=False):
        """Explicitly write a copy with no passwords or restrictions."""
        self.save(path, password="", allow_pending_redactions=allow_pending_redactions)

    def pending_redactions(self):
        """Unapplied redaction marks: [{"page", "xref", "rect"}]."""
        found = []
        for page in self._require():
            for annot in page.annots(types=[fitz.PDF_ANNOT_REDACT]) or ():
                found.append({"page": page.number, "xref": annot.xref, "rect": tuple(annot.rect)})
        return found

    def _gate_redactions(self, allowed):
        if not allowed:
            pending = self.pending_redactions()
            if pending:
                raise PendingRedactionsError(pending)

    def require_no_pending_redactions(self):
        """For callers that export bytes themselves (OCR, compare jobs)."""
        self._gate_redactions(False)

    def delete_annotation(self, page, xref):
        """Remove one annotation (comments dialog) with rollback on failure."""
        p = self._page(page)
        with self._mutation():
            annot = p.load_annot(int(xref))
            if annot is None:
                raise ValueError(_("La anotación ya no existe."))
            p.delete_annot(annot)

    def render(self, page, scale=1):
        if not math.isfinite(scale) or not 0 < scale <= 16:
            raise ValueError(_("Escala de visualización fuera de rango."))
        if getattr(self, "_layer_choice", None) and self.doc is not None:
            self._layer_session()
            self._reapply_layers()
        return self._page(page).get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)

    def text(self, page):
        return self._page(page).get_text(sort=True)

    def search(self, query):
        if not query.strip():
            return []
        return [(page.number, rect) for page in self._require() for rect in page.search_for(query)]

    def _put_text(self, page, rect, text, size, color, fontname="helv", align=0, underline=False, line_spacing=1.0):
        if not 1 <= size <= 500:
            raise ValueError(_("Tamaño de texto fuera de rango."))
        if not 1.0 <= line_spacing <= 3.0:
            raise ValueError(_("Interlineado fuera de rango."))
        if any(ord(character) > 255 for character in text):
            family = "monospace" if fontname.startswith("co") else "serif" if fontname.startswith("ti") else "sans-serif"
            rgb = ",".join(str(round(component * 255)) for component in color)
            alignment = ["left", "center", "right", "justify"][align]
            css = f"body {{ margin:0; font-family:{family}; font-size:{size}pt; color:rgb({rgb}); text-align:{alignment}; }}"
            css += f" p {{ line-height:{line_spacing}; }}" if line_spacing != 1.0 else ""
            result, __ = page.insert_htmlbox(rect, html.escape(text).replace("\n", "<br>"), css=css, scale_low=1)
        else:
            # lineheight is a multiple of the font size; the font's own ascent-descent is the 1.0 spacing.
            lineheight = None
            if line_spacing != 1.0:
                font = fitz.Font(fontname)
                lineheight = line_spacing * (font.ascender - font.descender)
                # Every line takes the full step, plus a little for the last descent; grow the box to hold them.
                needed = text.count("\n") + 1
                bounds = page.rect * page.derotation_matrix
                rect = fitz.Rect(rect.x0, rect.y0, rect.x1, max(rect.y1, rect.y0 + needed * lineheight * size + 4)) & bounds
            result = page.insert_textbox(rect, text, fontsize=size, fontname=fontname, color=color, align=align, lineheight=lineheight)
        if result < 0:
            raise ValueError(_("El texto no cabe en el área. Amplía el área o reduce el tamaño."))
        if underline:
            self._underline_lines(page, rect, size, color)

    @staticmethod
    def _underline_lines(page, rect, size, color):
        """Draw a rule under every text line that starts inside rect."""
        shape = page.new_shape()
        for block in page.get_text("dict", clip=rect)["blocks"]:
            for line in block.get("lines", []):
                x0, y0, x1, y1 = line["bbox"]
                if not rect.contains(fitz.Point(x0 + 0.5, y0 + 0.5)):
                    continue
                y = y1 + size * 0.06
                shape.draw_line((x0, y), (min(x1, rect.x1), y))
        shape.finish(color=color, width=max(0.6, size * 0.06), closePath=False)
        shape.commit()

    def add_mark(self, page, rect, kind, color=(0, 0, 0)):
        """Vector check (✓) or cross (✗) in a square at the top-left of rect, stroked two lines each."""
        if kind not in ("check", "cross"):
            raise ValueError(_("Marca desconocida."))
        p = self._page(page)
        r = self._rect(p, rect)
        side = min(r.width, r.height)
        if side < 4:
            raise ValueError(_("La marca es demasiado pequeña."))
        x, y = r.x0, r.y0

        def at(u, v):
            return fitz.Point(x + u * side, y + v * side)

        if kind == "check":
            strokes = [(at(0.05, 0.55), at(0.38, 0.9)), (at(0.38, 0.9), at(0.95, 0.1))]
        else:
            strokes = [(at(0.1, 0.1), at(0.9, 0.9)), (at(0.9, 0.1), at(0.1, 0.9))]
        with self._mutation():
            shape = p.new_shape()
            for start, end in strokes:
                shape.draw_line(start, end)
            shape.finish(color=color, width=max(0.8, side * 0.12), lineCap=1, lineJoin=1, closePath=False)
            shape.commit()

    def add_text(self, page, rect, text, size=12, color=(0, 0, 0), fontname="helv", align=0, *, underline=False, line_spacing=1.0):
        p = self._page(page)
        r = self._rect(p, rect)
        with self._mutation():
            self._put_text(p, r, text, size, color, fontname, align, underline, line_spacing)

    def _erase_text(self, page, rect):
        # Temporarily detach existing redaction marks. Applying a text edit must
        # never apply a separate, still-pending redaction elsewhere on the page.
        pending = [a.xref for a in page.annots() or () if a.type[0] == fitz.PDF_ANNOT_REDACT]
        def references():
            kind, value = self.doc.xref_get_key(page.xref, "Annots")
            if kind == "xref":
                value = self.doc.xref_object(int(value.split()[0]))
            return [int(x) for x in re.findall(r"(\d+)\s+\d+\s+R", value)]
        if pending:
            self.doc.xref_set_key(page.xref, "Annots", "[" + " ".join(f"{x} 0 R" for x in references() if x not in pending) + "]")
            page = self.doc.reload_page(page)
        page.add_redact_annot(rect, fill=False, cross_out=False)
        page.apply_redactions(images=0, graphics=0, text=0)
        if pending:
            self.doc.xref_set_key(page.xref, "Annots", "[" + " ".join(f"{x} 0 R" for x in references() + pending) + "]")
            page = self.doc.reload_page(page)
        return page

    def replace_text(self, page, rect, text, size=12, color=(0, 0, 0), target_rect=None, fontname="helv", align=0, *, underline=False, line_spacing=1.0):
        p = self._page(page)
        r = self._rect(p, rect)
        with self._mutation():
            p = self._erase_text(p, r)
            # insert_textbox reserves an additional descent after the last line.
            # A span bbox already contains that descent, so supplying it as the
            # exact box otherwise rejects even the original text. This changes
            # only the insertion bookkeeping; the redacted region stays exact.
            insertion = self._rect(p, target_rect) if target_rect is not None else fitz.Rect(r)
            if text:
                font = fitz.Font(fontname)
                insertion.y1 = max(insertion.y1 + abs(font.descender) * size + 0.02,
                                   insertion.y0 + size * (font.ascender - 2 * font.descender) + 0.02)
                # Span bboxes are float32 and exactly as wide as the text, and a
                # translated rect can lose a ULP of width at fractional zoom.
                # insert_textbox would then wrap the last word and overflow.
                # Allow a sub-glyph slack opposite the alignment anchor so the
                # same text keeps its line breaks; real overflow still fails.
                slack = 0.01 * size + 0.01
                if align == 1:
                    insertion.x0 -= slack / 2
                    insertion.x1 += slack / 2
                elif align == 2:
                    insertion.x0 -= slack
                else:
                    insertion.x1 += slack
                self._put_text(p, insertion, text, size, color, fontname, align, underline, line_spacing)

    def remove_text(self, page, rect):
        p = self._page(page)
        r = self._rect(p, rect)
        with self._mutation():
            self._erase_text(p, r)

    def add_image(self, page, rect, path):
        p = self._page(page)
        r = self._rect(p, rect)
        with self._mutation():
            p.insert_image(r, filename=str(path), keep_proportion=True)

    def images(self, page):
        from .image_objects import list_images
        return list_images(self._page(page))

    def transform_image(self, page, index, rect):
        from .image_objects import transform_image
        p = self._page(page)
        target = fitz.Rect(rect)
        bounds = p.rect * p.derotation_matrix
        if not all(math.isfinite(v) for v in target) or target.is_empty or not bounds.contains(target):
            raise ValueError(_("La imagen debe quedar dentro de la página."))
        with self._mutation():
            transform_image(p, index, target)

    def rotate_image(self, page, index):
        """Turn an image 90 degrees clockwise around its centre, using the same content-stream edit as transform_image."""
        from pypdf.generic import FloatObject
        from .image_objects import _selected, _write
        p = self._page(page)
        with self._mutation():
            image, stream, number, ctm, matrix = _selected(p, index)
            original = image["rect"]
            cx, cy = (original.x0 + original.x1) / 2, (original.y0 + original.y1) / 2
            turned = fitz.Rect(cx - original.height / 2, cy - original.width / 2, cx + original.height / 2, cy + original.width / 2)
            if not (p.rect * p.derotation_matrix).contains(turned):
                raise ValueError(_("La imagen girada no cabe en la página."))
            rotation = fitz.Matrix(0, 1, -1, 0, cx + cy, cy - cx)
            local = ctm * matrix * rotation * ~matrix * ~ctm
            operations = list(stream.operations)
            operations[number:number + 1] = [([], b"q"), ([FloatObject(value) for value in local], b"cm"), stream.operations[number], ([], b"Q")]
            _write(p, stream, operations)

    def image_opacity(self, page, index):
        """Opacity (0.05 to 1) set on an inserted image through set_image_opacity; 1.0 when untouched."""
        images = self.images(page)
        if not 0 <= index < len(images):
            return 1.0
        kind, value = self.doc.xref_get_key(images[index]["xref"], "EditorOpacity")
        try:
            return min(1.0, max(0.05, float(value))) if kind != "null" else 1.0
        except ValueError:
            return 1.0

    def set_image_opacity(self, page, index, opacity):
        """Show one image occurrence at the given opacity. The transparency is stored in the image itself, so the
        result is the same in every viewer and the image stays editable; the original pixels are kept to restore it."""
        import io
        from PIL import Image
        from pypdf.generic import NameObject
        from .image_objects import _selected, _unrotated, _write
        if not 0.05 <= opacity <= 1:
            raise ValueError(_("La opacidad debe estar entre 0,05 y 1."))
        p = self._page(page)
        with self._mutation():
            image, stream, number, ctm, matrix = _selected(p, index)
            source = image["xref"]
            kind, value = self.doc.xref_get_key(source, "EditorSource")
            if kind == "xref":
                source = int(value.split()[0])
            names = {row[7] for row in p.get_images(full=True) if row[9] == 0}
            png = None
            if opacity < 1:
                try:
                    info = self.doc.extract_image(source)
                    base = Image.open(io.BytesIO(info["image"])).convert("RGBA")
                    if info.get("smask"):
                        mask = Image.open(io.BytesIO(self.doc.extract_image(info["smask"])["image"])).convert("L")
                        base.putalpha(mask.resize(base.size))
                    alpha = base.getchannel("A").point(lambda v: round(v * opacity))
                    base.putalpha(alpha)
                    out = io.BytesIO()
                    base.save(out, format="PNG")
                    png = out.getvalue()
                except Exception:
                    raise ValueError(_("No se pudo cambiar la opacidad de esta imagen.")) from None
            with _unrotated(p):
                created = p.insert_image((0, 0, 10, 10), stream=png) if png else p.insert_image((0, 0, 10, 10), xref=source)
            added = [row[7] for row in p.get_images(full=True) if row[9] == 0 and row[0] == created and row[7] not in names]
            if len(added) != 1:
                raise ValueError(_("No se pudo aislar el recurso de la imagen."))
            if png:
                self.doc.xref_set_key(created, "EditorOpacity", repr(round(float(opacity), 4)))
                self.doc.xref_set_key(created, "EditorSource", f"{source} 0 R")
            operations = list(stream.operations)
            operations[number] = ([NameObject("/" + added[0])], b"Do")
            _write(p, stream, operations)

    def delete_image(self, page, index):
        from .image_objects import delete_image
        with self._mutation():
            delete_image(self._page(page), index)

    def replace_image(self, page, index, path):
        from .image_objects import replace_image
        with self._mutation():
            replace_image(self._page(page), index, path)

    @staticmethod
    def validate_uri(uri):
        uri = str(uri).strip()
        if any(ord(c) < 32 or c.isspace() for c in uri):
            raise ValueError(_("El enlace contiene espacios o caracteres no válidos."))
        parsed = urlsplit(uri)
        if parsed.scheme.lower() in ("http", "https") and parsed.hostname and not parsed.username and not parsed.password:
            return uri
        if parsed.scheme.lower() == "mailto" and parsed.path and "@" in parsed.path:
            return uri
        raise ValueError(_("Introduce una dirección http://, https:// o mailto: válida."))

    def links(self, page):
        p = self._page(page)
        # MuPDF reports link rectangles in rotated page coordinates.
        return [{**link, "from": fitz.Rect(link["from"]) * p.derotation_matrix}
                for link in p.get_links()]

    def set_link(self, page, rect, *, uri=None, target_page=None, xref=None):
        p = self._page(page)
        rect = self._rect(p, rect)
        if (uri is None) == (target_page is None):
            raise ValueError(_("Elige una dirección web o una página de destino."))
        link = {"from": rect}
        if uri is not None:
            link.update(kind=fitz.LINK_URI, uri=self.validate_uri(uri))
        else:
            self._page(target_page)
            link.update(kind=fitz.LINK_GOTO, page=target_page, to=fitz.Point(0, 0), zoom=0)
        if xref is not None:
            previous = next((item for item in p.get_links() if item["xref"] == xref), None)
            if previous is None:
                raise ValueError(_("El enlace ya no existe. Actualiza la lista."))
            link.update(xref=xref, id=previous.get("id", ""))
        with self._mutation():
            # On cropped, rotated pages MuPDF's insertion matrix omits the
            # crop offset. Use the unrotated matrix for source and destination.
            involved = {page: p}
            if target_page is not None:
                involved[target_page] = self._page(target_page)
            rotations = {index: item.rotation for index, item in involved.items()}
            try:
                for item in involved.values():
                    item.set_rotation(0)
                if xref is None:
                    p.insert_link(link)
                else:
                    p.update_link(link)
            finally:
                for index, item in involved.items():
                    item.set_rotation(rotations[index])
            # Reopen to rebuild link caches even when a caller holds another
            # Page handle; reload_page can assert with multiple live handles.
            self._restore(self._snapshot())

    def delete_link(self, page, xref):
        p = self._page(page)
        link = next((item for item in p.get_links() if item["xref"] == xref), None)
        if link is None:
            raise ValueError(_("El enlace ya no existe. Actualiza la lista."))
        with self._mutation():
            p.delete_link(link)
            self._restore(self._snapshot())

    def annotate(self, page, rect, kind, content="", color=None, width=None, opacity=None, fill=None):
        p = self._page(page)
        r = self._rect(p, rect)
        with self._mutation():
            methods = {"highlight": p.add_highlight_annot, "underline": p.add_underline_annot, "strikeout": p.add_strikeout_annot, "rectangle": p.add_rect_annot, "ellipse": p.add_circle_annot, "redact": p.add_redact_annot}
            if kind == "note":
                annot = p.add_text_annot(r.tl, content or "Nota")
            elif kind in methods:
                annot = methods[kind](r)
            else:
                raise ValueError(_("Tipo de anotación desconocido."))
            annot.set_info(content=content, title=self.author)
            if kind == "redact":
                annot.set_colors(stroke=(0, 0, 0), fill=(0, 0, 0))
            elif color is not None or fill is not None:
                annot.set_colors(stroke=color, fill=fill)
            if width is not None and kind in ("rectangle", "ellipse"):
                annot.set_border(width=width)
            if opacity is not None and kind != "redact":
                annot.set_opacity(opacity)
            annot.update()
            return annot.xref

    def apply_redactions(self):
        """Burn in every redaction mark and remove what hides under it.

        Besides page content this deletes form fields, links and other
        annotations that intersect a marked area, and scrubs the document
        metadata, XMP and bookmark titles that quote the removed text.
        """
        secrets_found = set()
        with self._mutation():
            for page in self.doc:
                marks = [fitz.Rect(a.rect) for a in page.annots(types=[fitz.PDF_ANNOT_REDACT]) or ()]
                if not marks:
                    continue
                for rect in marks:
                    for line in page.get_text("text", clip=rect).splitlines():
                        if len(line.strip()) >= 2:
                            secrets_found.add(line.strip())
                    for word in page.get_text("words", clip=rect):
                        if len(word[4]) >= 4:
                            secrets_found.add(word[4])
                for widget in list(page.widgets() or ()):
                    if any(widget.rect.intersects(rect) for rect in marks):
                        for kind in ("V", "DV"):
                            secrets_found.update(self._plain_strings(self.doc.xref_get_key(widget.xref, kind)[1]))
                        page.delete_widget(widget)
                for link in page.get_links():
                    if any(fitz.Rect(link["from"]).intersects(rect) for rect in marks):
                        page.delete_link(link)
                for annot in list(page.annots() or ()):
                    if annot.type[0] != fitz.PDF_ANNOT_REDACT and any(annot.rect.intersects(rect) for rect in marks):
                        info = annot.info
                        secrets_found.update(s.strip() for s in (info.get("content", ""), info.get("subject", "")) if len(s.strip()) >= 3)
                        page.delete_annot(annot)
                page.apply_redactions(images=2, graphics=2, text=0)
            self._scrub_quoted(secrets_found)

    @staticmethod
    def _plain_strings(pdf_value):
        value = pdf_value or ""
        if value.startswith("(") and value.endswith(")"):
            value = value[1:-1]
        return [value.strip()] if len(value.strip()) >= 2 and not value.startswith("/") else []

    def _scrub_quoted(self, secrets_found):
        secrets_found = {s for s in secrets_found if s}
        if not secrets_found:
            return
        def mentions(text):
            lowered = (text or "").lower()
            return any(s.lower() in lowered for s in secrets_found)
        def clean(text):
            for s in sorted(secrets_found, key=len, reverse=True):
                text = re.sub(re.escape(s), "[censurado]", text, flags=re.IGNORECASE)
            return text
        metadata = {k: v for k, v in (self.doc.metadata or {}).items() if k != "format" and k != "encryption"}
        changed = {k: clean(v) for k, v in metadata.items() if v and mentions(v)}
        if changed:
            self.doc.set_metadata({**metadata, **changed})
        xml = self.doc.get_xml_metadata()
        if xml and mentions(xml):
            self.doc.del_xml_metadata()
        toc = self.doc.get_toc()
        if any(mentions(item[1]) for item in toc):
            self.doc.set_toc([[item[0], clean(item[1]), item[2]] for item in toc])

    def annotate_text(self, page, rects, kind, color=None, opacity=None):
        p = self._page(page)
        boxes = [self._rect(p, r) for r in rects]
        quads = [fitz.Quad(r.tl, r.tr, r.bl, r.br) for r in boxes]
        methods = {"highlight": p.add_highlight_annot, "underline": p.add_underline_annot, "strikeout": p.add_strikeout_annot}
        if kind not in methods or not quads:
            raise ValueError(_("Selecciona texto para anotarlo."))
        with self._mutation():
            annot = methods[kind](quads)
            annot.set_info(title=self.author)
            if color is not None:
                annot.set_colors(stroke=color)
            if opacity is not None:
                annot.set_opacity(opacity)
            annot.update()

    def add_ink(self, page, points, color=(0, 0, 0), width=2, opacity=None):
        p = self._page(page)
        if len(points) < 2:
            raise ValueError(_("Traza al menos dos puntos."))
        with self._mutation():
            annot = p.add_ink_annot([[(float(point[0]), float(point[1])) for point in points]])
            annot.set_info(title=self.author)
            annot.set_colors(stroke=color)
            annot.set_border(width=width)
            if opacity is not None:
                annot.set_opacity(opacity)
            annot.update()

    def add_line(self, page, start, end, arrow=False, color=(0, 0, 0), width=2, opacity=None):
        """Straight line, or a line with an open arrowhead at its end point."""
        p = self._page(page)
        a, b = fitz.Point(start), fitz.Point(end)
        if not all(math.isfinite(v) for v in (*a, *b)) or a.distance_to(b) < 2:
            raise ValueError(_("Arrastra para dibujar una línea más larga."))
        with self._mutation():
            annot = p.add_line_annot(a, b)
            annot.set_info(title=self.author)
            annot.set_colors(stroke=color)
            annot.set_border(width=width)
            if arrow:
                annot.set_line_ends(fitz.PDF_ANNOT_LE_NONE, fitz.PDF_ANNOT_LE_OPEN_ARROW)
            if opacity is not None:
                annot.set_opacity(opacity)
            annot.update()
            return annot.xref

    # Measurements: a line (distance) or a polygon (area) whose text holds the value in the chosen unit.
    MEASURE_UNITS = ("mm", "cm", "pulg", "pt")
    MEASURE_POINTS = {"pt": 1.0, "mm": 72 / 25.4, "cm": 72 / 2.54, "pulg": 72.0}
    MEASURE_SUBJECT = "Medición"

    @classmethod
    def measure_true_scale(cls, unit):
        """Units per page point at real size."""
        return 1 / cls.MEASURE_POINTS[unit]

    @staticmethod
    def measure_length(points):
        """Length in points of the path through the given points."""
        pts = [fitz.Point(p) for p in points]
        return sum(a.distance_to(b) for a, b in zip(pts, pts[1:]))

    @staticmethod
    def measure_area(points):
        """Area in square points of the polygon (shoelace formula)."""
        pts = [fitz.Point(p) for p in points]
        total = sum(a.x * b.y - b.x * a.y for a, b in zip(pts, pts[1:] + pts[:1]))
        return abs(total) / 2

    @staticmethod
    def format_measure(value, unit, area=False):
        text = f"{value:,.2f}".replace(",", " ").replace(".", ",")
        return f"{text} {unit}" + ("²" if area else "")

    def measure_value(self, points, scale, unit, area=False):
        """Text for a measurement; scale is units per page point."""
        if not (math.isfinite(scale) and scale > 0) or unit not in self.MEASURE_UNITS:
            raise ValueError(_("La escala debe ser un número mayor que cero."))
        value = self.measure_area(points) * scale * scale if area else self.measure_length(points) * scale
        return self.format_measure(value, unit, area)

    def add_measurement(self, page, points, scale, unit, area=False, color=(0.85, 0.19, 0.15), width=1.5):
        """Saves a distance (two points) or an area (three or more) as an annotation carrying its value as text."""
        p = self._page(page)
        pts = [fitz.Point(q) for q in points]
        if not all(math.isfinite(v) for q in pts for v in q):
            raise ValueError(_("Puntos de medición no válidos."))
        if area and len(pts) < 3 or not area and len(pts) != 2:
            raise ValueError(_("Marca al menos tres puntos para medir un área.") if area else _("Arrastra para medir una distancia."))
        if self.measure_area(pts) < 1 if area else self.measure_length(pts) < 2:
            raise ValueError(_("La medición es demasiado pequeña."))
        label = self.measure_value(pts, scale, unit, area)
        with self._mutation():
            annot = p.add_polygon_annot(pts) if area else p.add_line_annot(*pts)
            annot.set_info(content=label, subject=self.MEASURE_SUBJECT, title=self.author)
            annot.set_colors(stroke=color)
            annot.set_border(width=width)
            annot.update()
            return annot.xref

    def measurements(self, page):
        """Measurement annotations of a page: xref, kind, vertices, text and rectangle."""
        found = []
        for annot in self._page(page).annots() or ():
            kind = annot.type[1]
            if kind not in ("Line", "Polygon") or annot.info.get("subject") != self.MEASURE_SUBJECT:
                continue
            found.append({"xref": annot.xref, "kind": "area" if kind == "Polygon" else "distance",
                          "points": [fitz.Point(v) for v in annot.vertices or ()],
                          "label": annot.info.get("content", ""), "rect": fitz.Rect(annot.rect)})
        return found

    def add_freetext(self, page, rect, text="", color=(0, 0, 0), size=12, opacity=None):
        """Text box shown directly on the page (FreeText annotation)."""
        p = self._page(page)
        r = self._rect(p, rect)
        with self._mutation():
            annot = p.add_freetext_annot(r, text or " ", fontsize=size, text_color=color, fontname="helv")
            annot.set_info(title=self.author)
            if opacity is not None:
                annot.set_opacity(opacity)
            annot.update()
            return annot.xref

    REVIEW_STATES = ("Accepted", "Rejected", "Cancelled", "Completed", "None")

    def add_reply(self, page, parent_xref, content):
        """Reply to a comment: a note linked to its parent through /IRT."""
        p = self._page(page)
        with self._mutation():
            parent = self._annotation(p, parent_xref)
            reply = p.add_text_annot(parent.rect.tl + (14, 14), content or "")
            reply.set_info(content=content, title=self.author)
            reply.set_irt_xref(parent.xref)
            reply.update()
            return reply.xref

    def set_annotation_state(self, page, xref, state):
        """Review state of a comment, stored as a state-change reply like other readers do."""
        if state not in self.REVIEW_STATES:
            raise ValueError(_("Estado de revisión desconocido."))
        p = self._page(page)
        with self._mutation():
            parent = self._annotation(p, xref)
            for item in p.annots() or ():
                if item.irt_xref == parent.xref and self._state_of(item):
                    p.delete_annot(item)
                    break
            if state == "None":
                return None
            change = p.add_text_annot(parent.rect.tl + (14, 14), state)
            change.set_info(title=self.author)
            change.set_irt_xref(parent.xref)
            change.update()
            self.doc.xref_set_key(change.xref, "StateModel", "(Review)")
            self.doc.xref_set_key(change.xref, "State", f"({state})")
            return change.xref

    def _state_of(self, annot):
        value = self.doc.xref_get_key(annot.xref, "State")
        return value[1].strip("()") if value[0] != "null" else ""

    def annotation_replies(self, page, xref):
        """Replies to one comment (oldest first) and its current review state."""
        replies, state = [], "None"
        for item in self._page(page).annots() or ():
            if item.irt_xref != int(xref):
                continue
            marked = self._state_of(item)
            if marked:
                state = marked
            else:
                info = item.info
                replies.append({"xref": item.xref, "author": info.get("title", ""), "content": info.get("content", "")})
        return {"replies": replies, "state": state}

    # Styling and moving of existing markup annotations (Editar PDF / objetos).
    EDITABLE_ANNOTATIONS = {"Highlight", "Underline", "StrikeOut", "Square", "Circle", "Ink", "Text", "Stamp", "Line", "FreeText"}

    def annotations(self, page):
        found = []
        for annot in self._page(page).annots() or ():
            kind = annot.type[1]
            if kind not in self.EDITABLE_ANNOTATIONS or annot.irt_xref:
                continue
            colors = annot.colors or {}
            opacity = annot.opacity
            text_color = self._freetext_color(annot) if kind == "FreeText" else None
            found.append({
                "xref": annot.xref,
                "type": kind,
                "rect": fitz.Rect(annot.rect),
                "stroke": text_color or colors.get("stroke"),
                "fill": colors.get("fill"),
                "opacity": opacity if opacity is not None and opacity >= 0 else 1.0,
                "width": (annot.border or {}).get("width") or 1,
                "author": annot.info.get("title", ""),
                "arrow": kind == "Line" and annot.line_ends[1] != fitz.PDF_ANNOT_LE_NONE,
            })
        return found

    def _freetext_color(self, annot):
        """Text colour of a FreeText annotation, read from its default appearance string."""
        kind, value = self.doc.xref_get_key(annot.xref, "DA")
        found = re.search(r"((?:[\d.]+\s+){1,3})(g|rg)\b", value) if kind == "string" else None
        if not found:
            return None
        parts = [float(x) for x in found.group(1).split()]
        return tuple(parts * 3) if len(parts) == 1 else tuple(parts) if len(parts) == 3 else None

    def _annotation(self, p, xref):
        # The caller keeps the page object alive: an annotation is unusable once its page is gone.
        annot = p.load_annot(int(xref))
        if annot is None or annot.type[1] not in self.EDITABLE_ANNOTATIONS:
            raise ValueError(_("La anotación ya no existe."))
        return annot

    def set_annotation_style(self, page, xref, *, color=None, fill=None, opacity=None, width=None, coalesce=None):
        p = self._page(page)
        with self._mutation(coalesce=coalesce):
            annot = self._annotation(p, xref)
            if annot.type[1] == "FreeText":
                # A text box has no stroke colour: the colour shown is the text colour.
                if color is not None:
                    annot.update(text_color=color)
            elif color is not None or fill is not None:
                annot.set_colors(stroke=color, fill=fill)
            if opacity is not None:
                annot.set_opacity(opacity)
            if width is not None:
                annot.set_border(width=width)
            annot.update()

    def set_annotation_rect(self, page, xref, rect, coalesce=None):
        p = self._page(page)
        with self._mutation(coalesce=coalesce):
            annot = self._annotation(p, xref)
            annot.set_rect(self._rect(p, rect))
            annot.update()

    def set_annotation_content(self, page, xref, content):
        p = self._page(page)
        with self._mutation():
            annot = self._annotation(p, xref)
            annot.set_info(content=content)
            annot.update()

    def rotate(self, pages, angle=90):
        selected = self._pages(pages)
        if angle % 90:
            raise ValueError(_("La rotación debe ser múltiplo de 90 grados."))
        with self._mutation():
            for index in selected:
                p = self.doc[index]
                p.set_rotation((p.rotation + angle) % 360)

    def delete_pages(self, pages):
        selected = self._pages(pages)
        if len(selected) == self.page_count:
            raise ValueError(_("El documento debe conservar al menos una página."))
        with self._mutation():
            for index in reversed(selected):
                self.doc.delete_page(index)

    def duplicate_page(self, page):
        self._page(page)
        with self._mutation():
            with fitz.open(stream=self._bytes(), filetype="pdf") as source:
                self.doc.insert_pdf(source, from_page=page, to_page=page, start_at=page + 1, widgets=True)

    def insert_blank(self, after, width=595, height=842):
        if not -1 <= after < self.page_count or not 20 <= width <= 14400 or not 20 <= height <= 14400:
            raise ValueError(_("Posición o dimensiones de página inválidas."))
        with self._mutation():
            self.doc.new_page(pno=after + 1, width=width, height=height)

    def reorder(self, order):
        order = list(order)
        if sorted(order) != list(range(self.page_count)):
            raise ValueError(_("El orden debe contener cada página exactamente una vez."))
        with self._mutation():
            self.doc.select(order)

    def merge(self, paths, at=None):
        at = self.page_count if at is None else at
        if not 0 <= at <= self.page_count:
            raise ValueError(_("Posición de inserción inválida."))
        with self._mutation():
            for path in paths:
                with fitz.open(path) as source:
                    if source.needs_pass:
                        raise ValueError(_("El archivo está protegido: {name}", name=Path(path).name))
                    self.doc.insert_pdf(source, start_at=at, widgets=True)
                    at += len(source)

    def extract(self, pages, output, *, allow_pending_redactions=False):
        self._gate_redactions(allow_pending_redactions)
        selected = list(dict.fromkeys(pages))
        self._pages(selected)
        with fitz.open() as result:
            for index in selected:
                result.insert_pdf(self.doc, from_page=index, to_page=index, widgets=True)
            self._atomic_write(output, result.tobytes(garbage=4, deflate=True))

    def split(self, output_dir, *, allow_pending_redactions=False):
        self._gate_redactions(allow_pending_redactions)
        folder = Path(output_dir)
        folder.mkdir(parents=True, exist_ok=True)
        outputs = [folder / f"pagina-{index + 1:04d}.pdf" for index in range(self.page_count)]
        if any(path.exists() for path in outputs):
            raise ValueError(_("La carpeta ya contiene páginas con estos nombres; selecciona otra carpeta."))
        for index, output in enumerate(outputs):
            self.extract([index], output, allow_pending_redactions=True)
        return [str(path) for path in outputs]

    def split_by(self, output_dir, mode, *, pages_per_file=1, ranges="", prefix="pagina", allow_pending_redactions=False):
        """Split into several PDFs. mode: 'each', 'every' (pages_per_file), 'ranges' ('1-3, 4-8') or 'bookmarks' (level 1)."""
        self._gate_redactions(allow_pending_redactions)
        groups = self._split_groups(mode, pages_per_file, ranges)
        prefix = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", str(prefix)).strip() or "pagina"
        folder = Path(output_dir)
        folder.mkdir(parents=True, exist_ok=True)
        outputs = [folder / f"{prefix}-{name}.pdf" for name, _ in groups]
        if any(path.exists() for path in outputs):
            raise ValueError(_("La carpeta ya contiene archivos con estos nombres; selecciona otra carpeta o cambia el prefijo."))
        for (_name, pages), output in zip(groups, outputs):
            self.extract(pages, output, allow_pending_redactions=True)
        return [str(path) for path in outputs]

    def _split_groups(self, mode, pages_per_file, ranges):
        """List of (name, zero based pages) for split_by."""
        count = self.page_count
        if mode == "each":
            return [(f"{index + 1:04d}", [index]) for index in range(count)]
        if mode == "every":
            size = int(pages_per_file)
            if size < 1:
                raise ValueError(_("Indica al menos 1 página por archivo."))
            return [(f"{start + 1:04d}-{min(start + size, count):04d}", list(range(start, min(start + size, count)))) for start in range(0, count, size)]
        if mode == "ranges":
            groups = []
            for part in (ranges or "").split(","):
                if part.strip():
                    pages = doctools.parse_page_range(part, count)
                    groups.append((f"{pages[0] + 1:04d}-{pages[-1] + 1:04d}", pages))
            if not groups:
                raise ValueError(_("Indica al menos un rango de páginas, por ejemplo 1-3, 4-8."))
            return groups
        if mode == "bookmarks":
            starts = {}
            for level, title, page, *__ in self.bookmarks():
                if level == 1 and 1 <= page <= count:
                    starts.setdefault(page - 1, title)
            if not starts:
                raise ValueError(_("El documento no tiene marcadores de nivel 1. Elige otra forma de dividir."))
            if min(starts) > 0:
                starts.setdefault(0, "inicio")
            order = sorted(starts)
            groups = []
            for number, start in enumerate(order, 1):
                end = order[number] if number < len(order) else count
                slug = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", starts[start]).strip()[:40].strip() or "seccion"
                groups.append((f"{number:02d}-{slug}", list(range(start, end))))
            return groups
        raise ValueError(_("Forma de dividir no válida."))

    def crop(self, page, rect):
        p = self._page(page)
        r = self._rect(p, rect)
        with self._mutation():
            # CropBox uses the original page's top-left origin, including any existing crop.
            p.set_cropbox(r + (p.cropbox_position.x, p.cropbox_position.y, p.cropbox_position.x, p.cropbox_position.y))

    def watermark(self, text, size=36):
        with self._mutation():
            for p in self.doc:
                bounds = p.rect * p.derotation_matrix
                r = fitz.Rect(20, bounds.height / 2 - size, bounds.width - 20, bounds.height / 2 + size * 2)
                if p.insert_textbox(r, text, fontsize=size, color=(0.65, 0.65, 0.65), align=1, fill_opacity=0.3) < 0:
                    raise ValueError(_("La marca de agua no cabe. Reduce el tamaño."))

    def number_pages(self, start=1):
        with self._mutation():
            for index, p in enumerate(self.doc):
                bounds = p.rect * p.derotation_matrix
                p.insert_textbox(fitz.Rect(20, bounds.height - 30, bounds.width - 20, bounds.height - 8), str(start + index), fontsize=10, align=1)

    # Document tools: pure functions in doctools, wrapped so each one is a single undo step.
    def header_footer(self, **options):
        with self._mutation():
            return doctools.add_header_footer(self._require(), **options)

    def bates(self, **options):
        with self._mutation():
            return doctools.add_bates(self._require(), **options)

    def find_sensitive(self, **options):
        return doctools.find_matches(self._require(), **options)

    def mark_redactions(self, matches, fill=(0, 0, 0)):
        """Add (not apply) redaction marks for matches found by find_sensitive."""
        with self._mutation():
            return doctools.add_redactions(self._require(), matches, fill=fill)

    def flatten(self, *, allow_pending_redactions=False, **options):
        if options.get("annotations", True):
            self._gate_redactions(allow_pending_redactions)
        with self._mutation():
            return doctools.flatten(self._require(), **options)

    def set_page_labels(self, rules):
        with self._mutation():
            doctools.set_page_labels(self._require(), rules)

    def page_labels(self):
        return doctools.page_label_names(self._require())

    def insert_blank_page(self, after, **options):
        with self._mutation():
            return doctools.insert_blank_page(self._require(), after, **options)

    def insert_image_page(self, after, image, **options):
        with self._mutation():
            return doctools.insert_image_page(self._require(), after, image, **options)

    def duplicate_pages(self, page, copies=1):
        with self._mutation():
            return doctools.duplicate_page(self._require(), page, copies)

    def duplicate_selected(self, pages):
        selected = self._pages(pages)
        with self._mutation():
            with fitz.open(stream=self._bytes(), filetype="pdf") as source:
                for index in reversed(selected):
                    self.doc.insert_pdf(source, from_page=index, to_page=index, start_at=index + 1, widgets=True)

    def add_stamp(self, page, rect, *, kind="preset", name="", image="", color=None, opacity=1.0, as_annotation=True, turn=0):
        """turn: 0, 90, 180 or 270 degrees counter-clockwise, as the viewer shows it; the turned stamp fits inside rect."""
        if turn not in (0, 90, 180, 270):
            raise ValueError(_("El giro debe ser 0, 90, 180 o 270 grados."))
        with self._mutation():
            if not turn:
                if kind == "image":
                    return doctools.add_image_stamp(self._require(), page, rect, image, as_annotation=as_annotation, opacity=opacity)
                return doctools.add_preset_stamp(self._require(), page, rect, name, color=color, as_annotation=as_annotation, opacity=opacity)
            doc = self._require()
            if kind == "image":
                try:
                    data = bytes(image) if isinstance(image, (bytes, bytearray)) else Path(image).read_bytes()
                except Exception:
                    raise ValueError(_("No se pudo leer la imagen del sello.")) from None
                label = "Imagen"
            else:
                label = str(name or "").upper()
                if label not in doctools.STAMPS:
                    raise ValueError(_("Sello desconocido."))
                data = doctools._stamp_pixmap(label, doctools._color(color) if color is not None else doctools.STAMPS[label]).tobytes("png")
            turned = doctools._turn_png(data, turn)
            if as_annotation:
                xref = doctools.add_image_stamp(doc, page, rect, turned, as_annotation=True, opacity=opacity)
                target = doc[page]
                annot = target.load_annot(xref)
                annot.set_info(title="Sello", content=label)
                annot.update()
                return xref
            if opacity < 1:
                import io
                from PIL import Image
                with Image.open(io.BytesIO(turned)) as picture:
                    picture = picture.convert("RGBA")
                    picture.putalpha(picture.getchannel("A").point(lambda v: round(v * opacity)))
                    out = io.BytesIO()
                    picture.save(out, format="PNG")
                turned = out.getvalue()
            return doctools.add_image_stamp(doc, page, rect, turned, as_annotation=False)

    def optimize_preview(self, **options):
        """Result dict of doctools.optimize; the open document is not modified."""
        return doctools.optimize(self._require(), **options)

    def check_document(self):
        return doctools.check_document(self._require())

    def compare_text(self, other_doc, *, allow_pending_redactions=False):
        self._gate_redactions(allow_pending_redactions)
        return doctools.compare_text(self._require(), other_doc)

    def metadata(self):
        return dict(self._require().metadata)

    def set_metadata(self, values):
        allowed = {"title", "author", "subject", "keywords", "creator", "producer", "creationDate", "modDate", "trapped"}
        with self._mutation():
            self.doc.set_metadata({k: str(v or "") for k, v in values.items() if k in allowed})

    def bookmarks(self):
        return self._require().get_toc()

    def set_bookmarks(self, toc):
        with self._mutation():
            self.doc.set_toc(toc)

    def forms(self):
        return [{"page": p.number, "xref": w.xref, "name": w.field_name, "type": w.field_type_string, "value": w.field_value, "rect": tuple(w.rect), "choices": w.choice_values or []} for p in self._require() for w in p.widgets() or ()]

    def fill_form(self, page, xref, value):
        p = self._page(page)
        with self._mutation():
            self._set_form_value(p, xref, value)

    def _set_form_value(self, page, xref, value):
        w = page.load_widget(int(xref))
        if w is None:
            raise ValueError(_("El campo ya no existe."))
        if w.field_flags & 1:
            raise ValueError(_("El campo {name} es de solo lectura.", name=w.field_name))
        if w.field_type == fitz.PDF_WIDGET_TYPE_SIGNATURE:
            raise ValueError(_("Usa la firma con certificado para los campos de firma."))
        if w.field_type == fitz.PDF_WIDGET_TYPE_CHECKBOX:
            value = w.on_state() if value is True or str(value).lower() in ("true", "1", "yes", "sí", "on") else "Off"
        elif w.field_type == fitz.PDF_WIDGET_TYPE_TEXT:
            value = str(value or "")
            if w.text_maxlen and len(value) > w.text_maxlen:
                raise ValueError(_("El campo {name} admite como máximo {count} caracteres.", name=w.field_name, count=w.text_maxlen))
        w.field_value = value
        w.update()

    def fill_forms(self, edits):
        with self._mutation():
            for page, xref, value in edits:
                self._set_form_value(self._page(page), xref, value)

    def select_radio(self, page, xref):
        """Select one option of a radio group, or clear it when it is already selected."""
        p = self._page(page)
        with self._mutation():
            target = p.load_widget(int(xref))
            if target is None:
                raise ValueError(_("El campo ya no existe."))
            if target.field_flags & 1:
                raise ValueError(_("El campo {name} es de solo lectura.", name=target.field_name))
            if target.field_type != fitz.PDF_WIDGET_TYPE_RADIOBUTTON:
                raise ValueError(_("Este campo no es una opción de grupo."))
            selected = target.field_value not in (None, "", "Off")
            # PyMuPDF clears a radio only with False; the string "Off" leaves it selected.
            for widget in p.widgets() or ():
                if widget.field_name != target.field_name or widget.field_type != fitz.PDF_WIDGET_TYPE_RADIOBUTTON:
                    continue
                if widget.xref == target.xref and not selected:
                    widget.field_value = widget.on_state()
                else:
                    widget.field_value = False
                widget.update()

    def add_field(self, page, rect, name, kind="text"):
        p = self._page(page)
        r = self._rect(p, rect)
        if not name.strip() or name in {f["name"] for f in self.forms()}:
            raise ValueError(_("El campo necesita un nombre único."))
        types = {"text": fitz.PDF_WIDGET_TYPE_TEXT, "checkbox": fitz.PDF_WIDGET_TYPE_CHECKBOX, "signature": fitz.PDF_WIDGET_TYPE_SIGNATURE, "choice": fitz.PDF_WIDGET_TYPE_COMBOBOX}
        if kind not in types:
            raise ValueError(_("Tipo de campo no admitido."))
        with self._mutation():
            widget = fitz.Widget()
            widget.field_name = name
            widget.field_type = types[kind]
            widget.rect = r
            widget.field_value = "Off" if kind == "checkbox" else ""
            if kind == "choice":
                widget.choice_values = ["Opción 1", "Opción 2"]
            widget.text_fontsize = 12
            widget.border_width = 1
            widget.border_color = (0.45, 0.45, 0.45)
            p.add_widget(widget)

    def add_fields(self, specs):
        """Creates several fields in one undo step. specs: (page, rect, name, kind) tuples."""
        types = {"text": fitz.PDF_WIDGET_TYPE_TEXT, "checkbox": fitz.PDF_WIDGET_TYPE_CHECKBOX}
        taken = {f["name"] for f in self.forms()}
        prepared = []
        for page, rect, name, kind in specs:
            p = self._page(page)
            r = self._rect(p, rect)
            if not name.strip() or name in taken:
                raise ValueError(_("El campo necesita un nombre único."))
            if kind not in types:
                raise ValueError(_("Tipo de campo no admitido."))
            taken.add(name)
            prepared.append((p, r, name, kind))
        if not prepared:
            raise ValueError(_("No hay campos que crear."))
        with self._mutation():
            for p, r, name, kind in prepared:
                widget = fitz.Widget()
                widget.field_name = name
                widget.field_type = types[kind]
                widget.rect = r
                widget.field_value = "Off" if kind == "checkbox" else ""
                widget.text_fontsize = 12
                widget.border_width = 1
                widget.border_color = (0.45, 0.45, 0.45)
                p.add_widget(widget)
        return len(prepared)

    def attachments(self):
        return [{"name": name, **self.doc.embfile_info(name)} for name in self._require().embfile_names()]

    def attach(self, path):
        name = Path(path).name
        data = Path(path).read_bytes()
        if name in self._require().embfile_names():
            raise ValueError(_("Ya existe un adjunto con ese nombre."))
        with self._mutation():
            self.doc.embfile_add(name, data, filename=name, ufilename=name)

    def extract_attachment(self, name, path):
        self._atomic_write(path, self._require().embfile_get(name))

    def remove_attachment(self, name):
        with self._mutation():
            self.doc.embfile_del(name)

    def sanitize(self):
        with self._mutation():
            self.doc.scrub(attached_files=True, clean_pages=True, embedded_files=True, hidden_text=True, javascript=True, metadata=True, redactions=True, redact_images=2, remove_links=True, reset_fields=True, reset_responses=True, thumbnails=True, xml_metadata=True)

    def export_text(self, path, *, allow_pending_redactions=False):
        self._gate_redactions(allow_pending_redactions)
        self._atomic_write(path, "\n\f\n".join(self.text(p) for p in range(self.page_count)).encode("utf-8"))

    def export_images(self, directory, dpi=150, *, pages=None, fmt="png", quality=90, allow_pending_redactions=False):
        """Write one image per page (all pages when pages is None). fmt: 'png' or 'jpeg'. Returns the written paths."""
        self._gate_redactions(allow_pending_redactions)
        if fmt not in ("png", "jpeg"):
            raise ValueError(_("Formato de imagen no válido."))
        selected = list(range(self.page_count)) if pages is None else list(dict.fromkeys(pages))
        self._pages(selected)
        folder = Path(directory)
        folder.mkdir(parents=True, exist_ok=True)
        extension = "png" if fmt == "png" else "jpg"
        outputs = [folder / f"pagina-{index + 1:04d}.{extension}" for index in selected]
        if any(path.exists() for path in outputs):
            raise ValueError(_("La carpeta ya contiene imágenes con estos nombres."))
        for index, output in zip(selected, outputs):
            pix = self.render(index, dpi / 72)
            data = pix.tobytes("png") if fmt == "png" else pix.tobytes("jpeg", jpg_quality=min(max(int(quality), 1), 100))
            self._atomic_write(output, data)
        return [str(path) for path in outputs]

    def export_docx(self, path, *, allow_pending_redactions=False):
        self._gate_redactions(allow_pending_redactions)
        from docx import Document
        result = Document()
        for index in range(self.page_count):
            if index:
                result.add_page_break()
            for line in self.text(index).splitlines():
                result.add_paragraph(line)
        data = io.BytesIO()
        result.save(data)
        self._atomic_write(path, data.getvalue())

    def export_xlsx(self, path, *, allow_pending_redactions=False):
        self._gate_redactions(allow_pending_redactions)
        from openpyxl import Workbook
        result = Workbook()
        result.remove(result.active)
        for index, page in enumerate(self._require()):
            sheet = result.create_sheet(_("Página {n}", n=index + 1))
            tables = page.find_tables()
            if tables.tables:
                for table in tables.tables:
                    for row in table.extract():
                        sheet.append([self._xlsx_literal(cell) for cell in row])
                    sheet.append([])
            else:
                for line in page.get_text(sort=True).splitlines():
                    sheet.append([self._xlsx_literal(line)])
            sheet.column_dimensions["A"].width = 60
        data = io.BytesIO()
        result.save(data)
        self._atomic_write(path, data.getvalue())

    @staticmethod
    def _xlsx_literal(value):
        if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
            return "'" + value
        return value

    def export_pptx(self, path, *, allow_pending_redactions=False):
        self._gate_redactions(allow_pending_redactions)
        from pptx import Presentation
        from pptx.util import Inches
        result = Presentation()
        p0 = self._page(0)
        result.slide_width = Inches(p0.rect.width / 72)
        result.slide_height = Inches(p0.rect.height / 72)
        for index in range(self.page_count):
            p = self._page(index)
            slide = result.slides.add_slide(result.slide_layouts[6])
            scale = min(result.slide_width / p.rect.width, result.slide_height / p.rect.height)
            width, height = int(p.rect.width * scale), int(p.rect.height * scale)
            slide.shapes.add_picture(io.BytesIO(self.render(index, 1.5).tobytes("png")), (result.slide_width - width) // 2, (result.slide_height - height) // 2, width, height)
        data = io.BytesIO()
        result.save(data)
        self._atomic_write(path, data.getvalue())

    def compare(self, path):
        with fitz.open(path) as other:
            if other.needs_pass:
                raise ValueError(_("Abre una copia sin protección para comparar."))
            left = [_("--- Página {n} ---", n=i + 1) + "\n" + p.get_text(sort=True) for i, p in enumerate(self._require())]
            right = [_("--- Página {n} ---", n=i + 1) + "\n" + p.get_text(sort=True) for i, p in enumerate(other)]
        differences = "\n".join(difflib.unified_diff("\n".join(left).splitlines(), "\n".join(right).splitlines(), fromfile=_("Documento actual"), tofile=Path(path).name, lineterm=""))
        return differences or _("No se encontraron diferencias en el texto extraído. No compara imágenes ni formato.")

    @staticmethod
    def _external_command(args, *, cancelled=None, text=False):
        if cancelled and cancelled():
            raise InterruptedError(_("Operación cancelada."))
        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=text, encoding="utf-8" if text else None,
                                   errors="replace" if text else None,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        started = time.monotonic()
        try:
            while True:
                try:
                    stdout, stderr = process.communicate(timeout=.15 if cancelled else 180)
                    return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
                except subprocess.TimeoutExpired:
                    if time.monotonic() - started >= 180:
                        raise TimeoutError(_("El programa externo superó el tiempo de espera de 180 segundos."))
                    if cancelled and cancelled():
                        raise InterruptedError(_("Operación cancelada."))
        except BaseException:
            if os.name == "nt":
                subprocess.run([str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"), "/PID", str(process.pid), "/T", "/F"], capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            else:
                process.kill()
            process.communicate()
            raise

    def ocr(self, language=None, progress=None, cancelled=None, deskew=False):
        executable, __ = resolve_external_tool("tesseract", self._tool_reject_dirs())
        if not executable:
            raise ValueError(_("Tesseract OCR no está instalado."))
        from . import ocr_batch
        root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
        bundled = root / "assets" / "tessdata"
        if language is None:
            language = "spa+eng" if all((bundled / f"{code}.traineddata").is_file() for code in ("spa", "eng")) else "eng"
        models = language.split("+")
        tessdata_args = ["--tessdata-dir", str(bundled)] if models and all((bundled / f"{code}.traineddata").is_file() for code in models) else []
        self.ocr_stats = {"pages": 0, "words": 0, "skew": {}, "rotation": {}}
        with tempfile.TemporaryDirectory(prefix="pdf-editor-ocr-") as folder, self._mutation():
            for index in range(self.page_count):
                if cancelled and cancelled():
                    raise InterruptedError(_("Operación cancelada."))
                p = self.doc[index]
                # Mixed pages retain their searchable text and gain OCR only
                # for words not already represented by the existing text layer.
                existing_words = [fitz.Rect(word[:4]) for word in p.get_text("words")]
                if existing_words and not p.get_images():
                    if progress:
                        progress(index + 1, self.page_count)
                    continue
                rotation = p.rotation
                p.set_rotation(0)
                scale = 200 / 72
                image = Path(folder) / "page.png"
                matrix = fitz.Matrix(scale, scale)
                turn = 0
                skew = 0.0
                if deskew:
                    matrix, turn, skew = ocr_batch.straighten_matrix(
                        p, matrix, lambda path: self._external_command([executable, str(path), "stdout", *tessdata_args, "--psm", "0"], text=True, cancelled=cancelled), folder)
                    if turn or skew:
                        self.ocr_stats["rotation"][index] = turn
                        self.ocr_stats["skew"][index] = skew
                pixmap = p.get_pixmap(matrix=matrix, alpha=False)
                pixmap.save(image)
                origin = (pixmap.x, pixmap.y)
                inverse = ~matrix
                # Enable TSV directly: a bundled model directory does not carry
                # the installation's configs/tsv convenience file.
                process = self._external_command([executable, str(image), "stdout", *tessdata_args, "-l", language, "--dpi", "200", "-c", "tessedit_create_tsv=1"], text=True, cancelled=cancelled)
                if process.returncode:
                    raise ValueError(_("OCR: {error}", error=process.stderr.strip()))
                for word in csv.DictReader(io.StringIO(process.stdout), delimiter="\t"):
                    text = (word.get("text") or "").strip()
                    if not text or int(word.get("level", 0)) != 5:
                        continue
                    left, top, width, height = [float(word[key]) for key in ("left", "top", "width", "height")]
                    if turn or skew:
                        corners = [fitz.Point(left + dx * width + origin[0], top + dy * height + origin[1]) * inverse for dx in (0, 1) for dy in (0, 1)]
                        word_rect = fitz.Rect(min(c.x for c in corners), min(c.y for c in corners), max(c.x for c in corners), max(c.y for c in corners))
                        x, y, w, h = word_rect.x0, word_rect.y0, word_rect.width, word_rect.height
                    else:
                        x, y, w, h = left / scale, top / scale, width / scale, height / scale
                        word_rect = fitz.Rect(x, y, x + w, y + h)
                    if any((word_rect & known).get_area() > word_rect.get_area() * .3 for known in existing_words):
                        continue
                    if turn in (90, 270):
                        # The page shows this text turned: write it along the page's vertical axis.
                        size = max(1, w / 1.1)
                        length = fitz.get_text_length(text, fontsize=size)
                        if length > h and length:
                            size *= h / length
                        point = (x + w * .85, y + h) if turn == 90 else (x + w * .15, y)
                        p.insert_text(point, text, fontsize=size, render_mode=3, rotate=90 if turn == 90 else 270)
                    else:
                        size = max(1, h / 1.1)
                        text_width = fitz.get_text_length(text, fontsize=size)
                        if text_width > w and text_width:
                            size *= w / text_width
                        if turn == 180:
                            p.insert_text((x + w, y + h * .15), text, fontsize=size, render_mode=3, rotate=180)
                        else:
                            p.insert_text((x, y + h * .85), text, fontsize=size, render_mode=3)
                    self.ocr_stats["words"] += 1
                p.set_rotation(rotation)
                self.ocr_stats["pages"] += 1
                if progress:
                    progress(index + 1, self.page_count)

    def from_images(self, paths):
        if not paths:
            raise ValueError(_("Selecciona al menos una imagen."))
        candidate = fitz.open()
        try:
            for path in paths:
                with fitz.open(path) as image:
                    pdf_data = image.convert_to_pdf()
                with fitz.open(stream=pdf_data, filetype="pdf") as source:
                    candidate.insert_pdf(source)
        except BaseException:
            candidate.close()
            raise
        # Creation starts an untitled document, including from the welcome screen.
        # Never retain the previous PDF path: Save must request a new destination.
        self.close()
        self.doc = candidate
        self.dirty = True

    def convert_office(self, path, cancelled=None):
        executable, __ = resolve_external_tool("soffice", self._tool_reject_dirs(path))
        if not executable:
            raise ValueError(_("LibreOffice no está instalado."))
        with tempfile.TemporaryDirectory(prefix="pdf-editor-office-") as folder:
            profile = (Path(folder) / "profile").as_uri()
            process = self._external_command([executable, f"-env:UserInstallation={profile}", "--headless", "--convert-to", "pdf", "--outdir", folder, str(Path(path).resolve())], cancelled=cancelled)
            output = Path(folder) / (Path(path).stem + ".pdf")
            if process.returncode or not output.exists():
                raise ValueError(_("LibreOffice no pudo convertir el archivo."))
            data = output.read_bytes()
        candidate = fitz.open(stream=data, filetype="pdf")
        self.close()
        self.doc = candidate
        self.dirty = True

    def sign_pkcs12(self, output, pfx, password, reason="", *, allow_pending_redactions=False, timestamper=None, field_spec=None, appearance=None):
        """Sign a copy (invisible unless field_spec has a rectangle). The open document stays editable and unchanged."""
        from . import signing
        self._gate_redactions(allow_pending_redactions)
        if self._encrypted:
            raise ValueError(_("Para firmar, guarda primero una copia sin contraseña y abre esa copia. Así decides explícitamente retirar la protección del documento firmado."))
        signer = signing.load_signer(pfx, password)
        source = self._bytes() if self.dirty or self._original_bytes is None or self._encrypted else self._original_bytes
        if appearance is None and reason:
            appearance = signing.Appearance(reason=reason)
        signed, report = signing.sign_bytes(source, signer, field_spec, appearance, reason=reason, timestamper=timestamper)
        self._atomic_write(output, signed)
        report.output = str(output)
        return report

    def signature_count(self):
        from . import signing
        source = self._bytes() if self.dirty or self._original_bytes is None or self._encrypted else self._original_bytes
        return signing.count_signatures(source)

    def inspect_signatures(self):
        from . import signing
        source = self._bytes() if self.dirty or self._original_bytes is None or self._encrypted else self._original_bytes
        return signing.report_text(signing.validate_bytes(source))

    # ---- optional content (layers): visibility is a view choice, written to the file only on request

    def _layer_session(self):
        key = tuple((row["number"], row["text"]) for row in self.doc.layer_ui_configs()) if self.doc is not None and not self.doc.is_closed else None
        if getattr(self, "_layer_key", None) != key:
            self._layer_key = key
            self._layer_choice = {}
            self._layer_remember = False
            self._layer_written = False
            self._layer_origin = None
        return self._layer_choice

    def layers(self):
        """Rows of the layer panel: number, text, depth, on, locked and whether it is a checkbox."""
        if self.doc is None or self.doc.is_closed:
            return []
        self._layer_session()
        self._reapply_layers()
        return [dict(row) for row in self.doc.layer_ui_configs()]

    def _reapply_layers(self):
        """A reopened document (undo, save) starts from the file defaults; put the user's choices back."""
        if self._layer_origin is None:
            self._layer_origin = {i["name"]: bool(i["on"]) for i in self.doc.get_ocgs().values()}
        for row in self.doc.layer_ui_configs():
            wanted = self._layer_choice.get(row["number"])
            if wanted is not None and row["type"] != "label" and bool(row["on"]) != wanted and not row["locked"]:
                self.doc.set_layer_ui_config(row["number"], 0 if wanted else 1)

    def set_layer_visible(self, number, visible):
        """Show or hide one layer. Not a document edit: no undo step and the file is not marked as changed."""
        rows = {row["number"]: row for row in self.layers()}
        row = rows.get(number)
        if row is None or row["locked"]:
            raise ValueError(_("Esta capa no se puede cambiar."))
        self.doc.set_layer_ui_config(number, 0 if visible else 1)
        self._layer_choice[number] = bool(visible)

    @property
    def layers_remembered(self):
        self._layer_session()
        return self._layer_remember

    def remember_layers(self, remember):
        self._layer_session()
        self._layer_remember = bool(remember)

    def _write_layer_state(self):
        """Called before saving: stores the visible layers as the file default only when the user asked for it."""
        if self.doc is None or self.doc.is_closed or not self.doc.get_ocgs():
            return
        self._layer_session()
        states = self.doc.get_ocgs()
        if self._layer_remember and self._layer_choice:
            self._layer_written = True
            self.doc.set_layer(-1, on=[x for x, i in states.items() if i["on"]], off=[x for x, i in states.items() if not i["on"]])
        elif self._layer_written:
            self._layer_written = False
            current = self.doc.get_ocgs()
            self.doc.set_layer(-1, on=[x for x, i in current.items() if self._layer_origin.get(i["name"], i["on"])],
                               off=[x for x, i in current.items() if not self._layer_origin.get(i["name"], i["on"])])
        else:
            return
