import os
import socket
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf as fitz
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from pyhanko.pdf_utils.reader import PdfFileReader
from PySide6.QtWidgets import QApplication

from pdf_editor import signing
from pdf_editor.engine import PDFEngine
from pdf_editor.signing import Appearance, FieldSpec, sign_file, validate_file
from pdf_editor.signing_ui import SignatureAppearanceDialog


def make_pfx(root, name, filename):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=30)).sign(key, hashes.SHA256()))
    pfx = root / filename
    pfx.write_bytes(pkcs12.serialize_key_and_certificates(b"t", key, cert, None, serialization.BestAvailableEncryption(b"pw")))
    return pfx


class VisibleSigningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        doc = fitz.open()
        doc.new_page().insert_text((72, 72), "Contrato")
        doc.new_page()
        self.source = self.root / "in.pdf"
        doc.save(self.source)
        doc.close()
        self.alice = make_pfx(self.root, "Alicia Pérez", "a.p12")
        self.bob = make_pfx(self.root, "Beto López", "b.p12")

    def tearDown(self):
        self.dir.cleanup()

    def test_visible_signature_has_rectangle_and_appearance(self):
        out = self.root / "v.pdf"
        report = sign_file(self.source, out, self.alice, "pw", FieldSpec(page=1, rect=(100, 100, 300, 160)),
                           Appearance(reason="Aprobación", location="Madrid"))
        self.assertTrue(report.visible)
        self.assertEqual(report.signer, "Alicia Pérez")
        with fitz.open(out) as doc:
            self.assertEqual(len(list(doc[0].widgets())), 0)
            widgets = list(doc[1].widgets())
            self.assertEqual(len(widgets), 1)
            self.assertAlmostEqual(widgets[0].rect.x0, 100, delta=1)
            self.assertAlmostEqual(widgets[0].rect.y0, 100, delta=1)
            self.assertAlmostEqual(widgets[0].rect.width, 200, delta=1)
            self.assertAlmostEqual(widgets[0].rect.height, 60, delta=1)
            text = doc[1].get_text()
            self.assertIn("Alicia", text)
            self.assertIn("Aprobaci", text)
        with out.open("rb") as handle:
            sig = PdfFileReader(handle).embedded_signatures[0]
            self.assertEqual(sig.sig_field["/Rect"][2] - sig.sig_field["/Rect"][0], 200)
        info = validate_file(out)[0]
        self.assertTrue(info.valid and info.intact and not info.modified)

    def test_visible_signature_with_image(self):
        image = self.root / "s.png"
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 20), False)
        pix.set_rect(pix.irect, (20, 20, 120))
        pix.save(image)
        out = self.root / "i.pdf"
        sign_file(self.source, out, self.alice, "pw", FieldSpec(rect=(50, 50, 250, 120)), Appearance(image_path=str(image)))
        with fitz.open(out) as doc:
            self.assertEqual(len(list(doc[0].widgets())), 1)
        self.assertTrue(validate_file(out)[0].valid)

    def test_invisible_signature_still_works(self):
        out = self.root / "n.pdf"
        report = sign_file(self.source, out, self.alice, "pw")
        self.assertFalse(report.visible)
        with fitz.open(out) as doc:
            self.assertTrue(all(w.rect.is_empty for w in doc[0].widgets()))
        self.assertEqual(len(validate_file(out)), 1)

    def test_rect_outside_or_tiny_is_rejected(self):
        with self.assertRaises(ValueError):
            sign_file(self.source, self.root / "x.pdf", self.alice, "pw", FieldSpec(rect=(10, 10, 15, 15)))
        with self.assertRaises(ValueError):
            sign_file(self.source, self.root / "x.pdf", self.alice, "pw", FieldSpec(page=9, rect=(10, 10, 200, 100)))
        self.assertFalse((self.root / "x.pdf").exists())

    def test_wrong_password(self):
        with self.assertRaises(ValueError):
            sign_file(self.source, self.root / "x.pdf", self.alice, "mal")

    def test_second_signature_keeps_the_first(self):
        first, second = self.root / "1.pdf", self.root / "2.pdf"
        sign_file(self.source, first, self.alice, "pw", FieldSpec(rect=(50, 50, 250, 110)))
        report = sign_file(first, second, self.bob, "pw", FieldSpec(page=1, rect=(50, 50, 250, 110)))
        self.assertEqual(report.previous_signatures, 1)
        infos = validate_file(second)
        self.assertEqual([i.signer for i in infos], ["Alicia Pérez", "Beto López"])
        for info in infos:
            self.assertTrue(info.valid and info.intact)
            self.assertFalse(info.modified)
        self.assertTrue(infos[0].later_revisions)
        self.assertFalse(infos[1].later_revisions)

    def test_modified_bytes_are_reported(self):
        out = self.root / "m.pdf"
        sign_file(self.source, out, self.alice, "pw", FieldSpec(rect=(50, 50, 250, 110)))
        data = bytearray(out.read_bytes())
        at = data.index(b"Contrato") if b"Contrato" in data else data.index(b"/Type")
        data[at] ^= 0x01
        tampered = self.root / "t.pdf"
        tampered.write_bytes(bytes(data))
        info = validate_file(tampered)[0]
        self.assertTrue(info.modified)
        self.assertFalse(info.intact)
        self.assertIn("modificado", info.summary)

    def test_content_added_after_signing_is_reported(self):
        out = self.root / "s.pdf"
        sign_file(self.source, out, self.alice, "pw")
        with fitz.open(out) as doc:
            doc[0].insert_text((72, 200), "Añadido")
            doc.saveIncr()
        info = validate_file(out)[0]
        self.assertTrue(info.modified)
        self.assertIn("modificado", info.summary)

    def test_self_signed_chain_is_not_verified_without_failing(self):
        out = self.root / "c.pdf"
        sign_file(self.source, out, self.alice, "pw")
        info = validate_file(out)[0]
        self.assertTrue(info.valid)
        self.assertFalse(info.chain_verified)
        self.assertIn("no verificada", info.chain_message.lower())
        self.assertIn("autofirmado", info.chain_message)
        self.assertFalse(info.revocation_checked)
        self.assertIsNone(info.timestamp)
        text = signing.report_text([info])
        self.assertIn("Revocación: no comprobada", text)
        self.assertIn("eIDAS", text)

    def test_works_offline(self):
        real = socket.socket.connect

        def blocked(sock, address, *args, **kwargs):
            host = address[0] if isinstance(address, tuple) else ""
            if host in ("127.0.0.1", "::1", "localhost"):       # asyncio (Windows) usa un socketpair local
                return real(sock, address, *args, **kwargs)
            raise AssertionError("network access")
        socket.socket.connect = blocked
        try:
            out = self.root / "o.pdf"
            sign_file(self.source, out, self.alice, "pw", FieldSpec(rect=(50, 50, 250, 110)))
            self.assertEqual(len(validate_file(out)), 1)
        finally:
            socket.socket.connect = real

    def test_signing_module_needs_no_qt(self):
        import subprocess
        import sys
        code = "import sys; import pdf_editor.signing; sys.exit(1 if any(m.startswith('PySide6') for m in sys.modules) else 0)"
        root = Path(__file__).resolve().parent.parent
        self.assertEqual(subprocess.run([sys.executable, "-c", code], cwd=root).returncode, 0)

    def test_engine_signs_visible_and_reports_existing(self):
        engine = PDFEngine()
        engine.open(self.source)
        first = self.root / "e1.pdf"
        engine.sign_pkcs12(first, self.alice, "pw", field_spec=FieldSpec(rect=(50, 50, 250, 110)), appearance=Appearance(reason="Prueba"))
        engine.open(first)
        self.assertEqual(engine.signature_count(), 1)
        second = self.root / "e2.pdf"
        engine.sign_pkcs12(second, self.bob, "pw")
        self.assertIn("Alicia", engine.inspect_signatures())
        engine.open(second)
        text = engine.inspect_signatures()
        self.assertIn("Beto", text)
        self.assertIn("Revocación: no comprobada", text)
        engine.close()

    def test_dialog_requires_rectangle_and_returns_spec(self):
        doc = fitz.open(self.source)
        dialog = SignatureAppearanceDialog(None, doc, 1, "Alicia")
        self.assertIsNone(dialog.field_spec())
        dialog.visible.setChecked(True)
        dialog.accept_choice()
        self.assertNotEqual(dialog.result(), dialog.DialogCode.Accepted)
        dialog.page.setValue(2)
        dialog.view.set_rect((10, 20, 210, 90))
        dialog.reason.setText("Conforme")
        dialog.accept_choice()
        spec = dialog.field_spec()
        self.assertEqual(spec.page, 1)
        self.assertAlmostEqual(spec.rect[2] - spec.rect[0], 200, delta=1)
        self.assertEqual(dialog.appearance().reason, "Conforme")
        doc.close()


if __name__ == "__main__":
    unittest.main()
