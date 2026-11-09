"""Digital signatures without any window: visible or invisible signing and validation of existing signatures.

Nothing here needs Qt or the network. Time stamps (optional) and revocation are the only things that would
need a connection; revocation is never checked. The dialogs live in signing_ui.py and are re-exported lazily.
"""
from __future__ import annotations

import functools
import io
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .lang import _, N_

SETTINGS_ENABLED = "signing/timestampEnabled"
SETTINGS_URL = "signing/timestampUrl"

HELP = N_("El sello de tiempo prueba cuándo se firmó el documento. Requiere conexión a internet y una "
        "autoridad de sellado en la que confíes. No se envía nada a la red si no lo activas.")
LIMITS = N_("Esta herramienta valida firmas de forma local. No consulta servicios de terceros, no comprueba la revocación de "
            "los certificados y no equivale a una firma electrónica cualificada eIDAS.")

_SYSTEM_BUNDLES = ("/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt", "/etc/ssl/cert.pem")


class TimestampError(ValueError):
    """The time stamp authority could not be reached or rejected the request."""


@dataclass
class FieldSpec:
    """Where the visible signature goes: page index (0-based) and rectangle in the page as displayed
    (points, origin at the top left, as in PyMuPDF). rect=None means an invisible signature."""
    page: int = 0
    rect: tuple | None = None
    name: str | None = None


@dataclass
class Appearance:
    show_name: bool = True
    show_date: bool = True
    reason: str = ""
    location: str = ""
    image_path: str | None = None


@dataclass
class Report:
    output: str
    field_name: str
    visible: bool
    page: int | None
    rect: tuple | None
    signer: str
    previous_signatures: int
    timestamped: bool


@dataclass
class SignatureInfo:
    field_name: str
    signer: str
    signing_time: str
    intact: bool            # the signed bytes are exactly what was signed
    valid: bool             # the cryptographic signature checks out
    modified: bool          # content changed after signing in a way the signature does not allow
    later_revisions: bool   # permitted additions after signing (more signatures, form filling...)
    covers_whole_file: bool
    chain_verified: bool
    chain_message: str
    timestamp: str | None
    revocation_checked: bool = False
    problems: list = field(default_factory=list)

    @property
    def summary(self):
        if self.modified or not self.intact:
            return _("El documento se ha modificado después de firmar")
        if not self.valid:
            return _("Firma no válida criptográficamente")
        return _("Firma válida")

    def text(self):
        yes, no = _("Sí"), _("No")
        lines = [_("Campo: {field}", field=self.field_name), _("Firmante: {signer}", signer=self.signer),
                 _("Fecha declarada: {date}", date=self.signing_time or _("No especificada")),
                 _("Resultado: {summary}", summary=self.summary),
                 _("Integridad (documento sin modificar tras firmar): {answer}", answer=no if self.modified or not self.intact else (yes if self.covers_whole_file else _("Sí, con revisiones posteriores permitidas"))),
                 _("Validez criptográfica: {answer}", answer=yes if self.valid else no),
                 _("Cadena de confianza: {message}", message=self.chain_message),
                 _("Sello de tiempo: {answer}", answer=self.timestamp or _("Sin sello de tiempo")),
                 _("Revocación: no comprobada (sin conexión a servicios externos)")]
        return "\n".join(lines)


def __getattr__(name):
    """Dialogs are defined with Qt in signing_ui; load them only when someone asks."""
    if name in ("SigningOptionsDialog", "SignatureAppearanceDialog", "PlacementView"):
        from . import signing_ui
        return getattr(signing_ui, name)
    raise AttributeError(name)


def make_timestamper(url):
    from pyhanko.sign import timestamps
    return timestamps.HTTPTimeStamper(url.strip())


def load_signer(p12, password):
    from pyhanko.sign import signers
    try:
        signer = signers.SimpleSigner.load_pkcs12(str(p12), passphrase=(password or "").encode("utf-8"))
    except Exception as error:
        raise ValueError(_("No se pudo abrir el certificado. Comprueba el archivo y la contraseña.")) from error
    if signer is None:
        raise ValueError(_("No se pudo abrir el certificado. Comprueba el archivo y la contraseña."))
    return signer


def signer_name(cert):
    subject = cert.subject.native
    return str(subject.get("common_name") or subject.get("organization_name") or cert.subject.human_friendly)


def count_signatures(data):
    """Number of signatures already in the document (0 for unsigned or unreadable files)."""
    from pyhanko.pdf_utils.reader import PdfFileReader
    try:
        return len(PdfFileReader(io.BytesIO(data)).embedded_signatures)
    except Exception:
        return 0


def _pdf_box(data, page_index, rect):
    """Rectangle as displayed (top-left origin) -> PDF user space of the page (bottom-left origin)."""
    import pymupdf as fitz
    with fitz.open(stream=data, filetype="pdf") as doc:
        if not 0 <= page_index < doc.page_count:
            raise ValueError(_("La página elegida no existe."))
        page = doc[page_index]
        box = fitz.Rect(rect)
        if box.is_empty or box.width < 20 or box.height < 12:
            raise ValueError(_("El rectángulo de firma es demasiado pequeño."))
        box = (box & page.rect) if not page.rect.contains(box) else box
        if box.is_empty:
            raise ValueError(_("El rectángulo de firma queda fuera de la página."))
        box = fitz.Rect(box) * page.derotation_matrix * ~page.transformation_matrix
        box.normalize()
        return tuple(round(v, 2) for v in (box.x0, box.y0, box.x1, box.y1))


def _escape(text):
    return text.replace("%", "%%")


def _stamp_style(appearance, name):
    from pyhanko.pdf_utils.images import PdfImage
    from pyhanko.stamp import TextStampStyle
    lines = []
    if appearance.show_name:
        lines.append(_escape(_("Firmado por: {name}", name=name)))
    if appearance.show_date:
        lines.append(_escape(_("Fecha: ")) + "%(ts)s")
    if appearance.reason:
        lines.append(_escape(_("Motivo: {reason}", reason=appearance.reason)))
    if appearance.location:
        lines.append(_escape(_("Lugar: {place}", place=appearance.location)))
    image = None
    if appearance.image_path:
        image = PdfImage(str(appearance.image_path))
    text = "\n".join(lines)
    from pyhanko.pdf_utils.text import TextBoxStyle
    from pyhanko.pdf_utils.font.basic import SimpleFontEngineFactory
    font = SimpleFontEngineFactory.default_factory()
    return TextStampStyle(stamp_text=text, border_width=1, background=image, background_opacity=1.0 if image and not text else 0.5,
                          text_box_style=TextBoxStyle(font=font, font_size=9), timestamp_format="%d/%m/%Y %H:%M:%S %Z")


def sign_bytes(data, signer, field_spec=None, appearance=None, *, reason="", timestamper=None):
    """Sign PDF bytes with an already loaded signer. Returns (signed bytes, Report without output path)."""
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign import fields, signers
    appearance = appearance or Appearance()
    reason = reason or appearance.reason
    previous = count_signatures(data)
    visible = field_spec is not None and field_spec.rect is not None
    name = (field_spec.name if field_spec and field_spec.name else None) or "PDFEditor_" + uuid.uuid4().hex[:12]
    cert = signer.signing_cert
    who = signer_name(cert)
    metadata = signers.PdfSignatureMetadata(field_name=name, reason=reason or None, location=appearance.location or None)
    kwargs = {}
    box = None
    if visible:
        box = _pdf_box(data, field_spec.page, field_spec.rect)
        kwargs = {"new_field_spec": fields.SigFieldSpec(sig_field_name=name, on_page=field_spec.page, box=box),
                  "stamp_style": _stamp_style(appearance, who)}
    try:
        writer = IncrementalPdfFileWriter(io.BytesIO(data))
        result = signers.PdfSigner(metadata, signer=signer, timestamper=timestamper, **kwargs).sign_pdf(writer)
    except Exception as error:
        if timestamper is None:
            raise
        raise TimestampError(_("No se pudo obtener el sello de tiempo. Comprueba la conexión y la dirección de la autoridad.")) from error
    report = Report(output="", field_name=name, visible=visible, page=field_spec.page if visible else None, rect=tuple(field_spec.rect) if visible else None,
                    signer=who, previous_signatures=previous, timestamped=timestamper is not None)
    return result.getvalue(), report


def sign_file(path_in, path_out, p12, password, field_spec=None, appearance=None, *, timestamper=None):
    """Sign path_in with a PKCS#12 certificate and write path_out. Invisible unless field_spec has a rectangle.
    Signing an already signed file adds a revision; earlier signatures stay valid."""
    signer = load_signer(p12, password)
    data = Path(path_in).read_bytes()
    signed, report = sign_bytes(data, signer, field_spec, appearance, timestamper=timestamper)
    out = Path(path_out)
    fd, temporary = tempfile.mkstemp(prefix=out.name + ".", suffix=".tmp", dir=out.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(signed)
        os.replace(temporary, out)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    report.output = str(out)
    return report


@functools.lru_cache(maxsize=1)
def trust_roots():
    """Root certificates of the system (or certifi as a fallback). Read from disk only."""
    from asn1crypto import pem, x509
    paths = [p for p in _SYSTEM_BUNDLES if os.path.isfile(p)]
    try:
        import certifi
        paths.append(certifi.where())
    except Exception:
        pass
    for path in paths:
        try:
            roots = []
            for kind, _name, der in pem.unarmor(Path(path).read_bytes(), multiple=True):
                if kind == "CERTIFICATE":
                    try:
                        roots.append(x509.Certificate.load(der))
                    except Exception:
                        continue
            if roots:
                return tuple(roots)
        except OSError:
            continue
    return ()


def validate_bytes(data):
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.diff_analysis import ModificationLevel
    from pyhanko.sign.validation.status import SignatureCoverageLevel
    from pyhanko.sign.validation import validate_pdf_signature
    from pyhanko_certvalidator import ValidationContext
    reader = PdfFileReader(io.BytesIO(data))
    roots = trust_roots()
    infos = []
    for embedded in reader.embedded_signatures:
        cert = embedded.signer_cert
        problems = []
        try:
            context = ValidationContext(trust_roots=list(roots), allow_fetching=False, revocation_mode="soft-fail") if roots else ValidationContext(allow_fetching=False, revocation_mode="soft-fail")
            status = validate_pdf_signature(embedded, signer_validation_context=context)
        except Exception as error:
            problems.append(str(error))
            infos.append(SignatureInfo(field_name=embedded.field_name, signer=signer_name(cert), signing_time=str(embedded.self_reported_timestamp or ""),
                                       intact=False, valid=False, modified=True, later_revisions=False, covers_whole_file=False, chain_verified=False,
                                       chain_message=_("No verificada: certificado autofirmado o raíz desconocida"), timestamp=None, problems=problems))
            continue
        level = status.modification_level
        modified = level is not None and level > ModificationLevel.FORM_FILLING
        later = embedded.coverage != SignatureCoverageLevel.ENTIRE_FILE
        stamp = None
        token = getattr(status, "timestamp_validity", None)
        if token is not None:
            stamp = str(token.timestamp) + ("" if token.valid and token.intact else " (" + _("no válido") + ")")
        verified = bool(status.trusted)
        message = _("Verificada frente a los certificados raíz del sistema (sin comprobar revocación)") if verified else _("No verificada: certificado autofirmado o raíz desconocida")
        infos.append(SignatureInfo(field_name=embedded.field_name, signer=signer_name(cert), signing_time=str(embedded.self_reported_timestamp or ""),
                                   intact=bool(status.intact), valid=bool(status.valid), modified=modified or not status.intact, later_revisions=later and not modified,
                                   covers_whole_file=not later, chain_verified=verified, chain_message=message, timestamp=stamp,
                                   problems=[]))
    return infos


def validate_file(path):
    """Report on every signature in the file. Local only: no revocation check, no third-party services."""
    return validate_bytes(Path(path).read_bytes())


def report_text(infos):
    if not infos:
        return _("No se encontraron firmas digitales.")
    return "\n\n".join(info.text() for info in infos) + "\n\n" + _(LIMITS)
