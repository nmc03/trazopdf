import tempfile
import unittest
import shutil
from unittest.mock import patch
from pathlib import Path

import pymupdf as fitz
from pypdf import PdfReader

from pdf_editor.engine import PDFEngine


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="pdf-engine-test-", dir=Path(__file__).resolve().parent)
        self.root = Path(self.folder.name)
        self.engine = PDFEngine()

    def tearDown(self):
        self.engine.close()
        self.folder.cleanup()

    def test_save_reopen_original_unchanged_until_save(self):
        path = self.root / "document.pdf"
        self.engine.add_text(0, (50, 50, 400, 100), "Original text")
        self.engine.save(path)
        original = path.read_bytes()
        self.engine.add_text(0, (50, 150, 400, 200), "Second text")
        self.assertEqual(path.read_bytes(), original)
        self.assertTrue(self.engine.dirty)
        self.engine.save()
        self.engine.open(path)
        self.assertIn("Second text", self.engine.text(0))
        self.assertFalse(self.engine.dirty)

    def test_undo_redo_and_failed_text_rollback(self):
        self.engine.add_text(0, (50, 50, 300, 100), "Undo me")
        self.assertTrue(self.engine.can_undo)
        self.engine.undo()
        self.assertNotIn("Undo me", self.engine.text(0))
        self.engine.redo()
        self.assertIn("Undo me", self.engine.text(0))
        with self.assertRaises(ValueError):
            self.engine.replace_text(0, (50, 50, 52, 51), "Too big", 30)
        self.assertIn("Undo me", self.engine.text(0))
        self.engine.new()
        self.engine.doc[0].insert_text((50, 80), "Original", fontsize=12)
        self.engine.doc[0].insert_text((50, 100), "Neighbor", fontsize=12)
        span = self.engine.doc[0].get_text("dict")["blocks"][0]["lines"][0]["spans"][0]
        self.engine.replace_text(0, span["bbox"], "New", span["size"])
        self.assertIn("New", self.engine.text(0))
        self.assertIn("Neighbor", self.engine.text(0))
        self.assertNotIn("Original", self.engine.text(0))

    def test_redaction_removes_underlying_text_from_saved_pdf(self):
        self.engine.add_text(0, (50, 50, 400, 100), "SECRET personal data")
        hits = self.engine.search("SECRET")
        self.assertEqual(len(hits), 1)
        self.engine.annotate(0, hits[0][1], "redact")
        self.engine.apply_redactions()
        output = self.root / "redacted.pdf"
        self.engine.save(output)
        self.assertNotIn("SECRET", PdfReader(output).pages[0].extract_text())
        self.assertIn("personal", PdfReader(output).pages[0].extract_text())
        with fitz.open(output) as saved:
            streams = b"".join(saved.xref_stream(i) or b"" for i in range(1, saved.xref_length()) if saved.xref_is_stream(i))
            self.assertNotIn(b"SECRET", streams)

    def test_form_values_are_canonical_pdf_fields(self):
        self.engine.add_field(0, (50, 80, 250, 120), "Customer")
        self.engine.add_field(0, (50, 150, 75, 175), "Accepted", "checkbox")
        fields = {f["name"]: f for f in self.engine.forms()}
        self.engine.fill_form(0, fields["Customer"]["xref"], "Nahum")
        self.engine.fill_form(0, fields["Accepted"]["xref"], True)
        path = self.root / "form.pdf"
        self.engine.save(path)
        values = PdfReader(path).get_fields()
        self.assertEqual(values["Customer"]["/V"], "Nahum")
        self.assertNotEqual(values["Accepted"]["/V"], "/Off")
        self.engine.open(path)
        self.assertEqual(next(f for f in self.engine.forms() if f["name"] == "Customer")["value"], "Nahum")

    def test_password_and_failed_open_preserve_current_document(self):
        self.engine.add_text(0, (50, 50, 300, 100), "Protected")
        output = self.root / "protected.pdf"
        self.engine.save(output, password="secret", owner_password="owner")
        with self.assertRaises(ValueError):
            self.engine.open(output, "wrong")
        self.assertIn("Protected", self.engine.text(0))
        self.engine.open(output, "secret")
        self.assertIn("Protected", self.engine.text(0))
        self.engine.add_text(0, (50, 150, 300, 200), "New content")
        self.engine.save()
        with fitz.open(output) as doc:
            self.assertTrue(doc.needs_pass)
            self.assertTrue(doc.authenticate("secret"))
        with self.assertRaisesRegex(ValueError, "sin contraseña"):
            self.engine.sign_pkcs12(self.root / "forbidden.pdf", self.root / "not-needed.p12", "")
        self.assertFalse((self.root / "forbidden.pdf").exists())
        clear = self.root / "clear.pdf"
        self.engine.save(clear, password="")
        with fitz.open(clear) as doc:
            self.assertFalse(doc.needs_pass)

    def test_rotated_coordinates_and_crop(self):
        self.engine.rotate([0], 90)
        self.engine.add_text(0, (50, 50, 300, 100), "Rotated page")
        self.assertIn("Rotated page", self.engine.text(0))
        pix = self.engine.render(0)
        self.assertGreater(pix.width, pix.height)
        self.engine.crop(0, (30, 30, 400, 500))
        self.assertAlmostEqual(self.engine.doc[0].cropbox.width, 370)
        self.engine.undo()
        self.assertEqual(self.engine.doc[0].rotation, 90)

    def test_page_operations_preserve_forms_and_validate_order(self):
        self.engine.add_field(0, (50, 50, 250, 100), "Entry")
        self.engine.duplicate_page(0)
        self.assertEqual(self.engine.page_count, 2)
        self.assertEqual(len(self.engine.forms()), 2)
        self.engine.insert_blank(1)
        self.engine.reorder([2, 1, 0])
        self.assertEqual(len(self.engine.forms()), 2)
        before = self.engine.page_count
        with self.assertRaises(ValueError):
            self.engine.reorder([0, 0, 1])
        self.assertEqual(self.engine.page_count, before)
        self.engine.delete_pages([0, 1])
        with self.assertRaises(ValueError):
            self.engine.delete_pages([0])

    def test_merge_failure_rolls_back_and_extract(self):
        source = self.root / "source.pdf"
        self.engine.save(source)
        with self.assertRaises(Exception):
            self.engine.merge([source, self.root / "missing.pdf"])
        self.assertEqual(self.engine.page_count, 1)
        self.engine.merge([source])
        self.assertEqual(self.engine.page_count, 2)
        extracted = self.root / "extracted.pdf"
        self.engine.extract([1], extracted)
        self.assertEqual(len(PdfReader(extracted).pages), 1)

    def test_metadata_bookmarks_attachment_and_sanitize(self):
        self.engine.set_metadata({"author": "Private author", "title": "Document"})
        self.engine.set_bookmarks([[1, "Start", 1]])
        self.assertEqual(self.engine.bookmarks()[0][1], "Start")
        attachment = self.root / "private.txt"
        attachment.write_text("Private content", encoding="utf-8")
        self.engine.attach(attachment)
        self.assertEqual(self.engine.attachments()[0]["name"], "private.txt")
        self.engine.sanitize()
        self.assertFalse(self.engine.attachments())
        self.assertFalse(self.engine.metadata().get("author"))
        self.engine.undo()
        self.assertEqual(self.engine.metadata()["author"], "Private author")

    def test_exports_are_readable_and_excel_does_not_execute_formula(self):
        from docx import Document
        from openpyxl import load_workbook
        from pptx import Presentation
        self.engine.add_text(0, (50, 50, 500, 100), "=HYPERLINK(\"https://example.org\")")
        word, excel, slides = [self.root / name for name in ("text.docx", "tables.xlsx", "slides.pptx")]
        self.engine.export_docx(word)
        self.engine.export_xlsx(excel)
        self.engine.export_pptx(slides)
        self.assertIn("HYPERLINK", Document(word).paragraphs[0].text)
        self.assertEqual(load_workbook(excel).active["A1"].data_type, "s")
        self.assertEqual(len(Presentation(slides).slides), 1)

    @unittest.skipUnless(Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe").exists() or shutil.which("tesseract"), "Tesseract not installed")
    def test_ocr_retains_images_and_adds_searchable_text(self):
        image = self.root / "scan.png"
        with fitz.open() as fixture:
            p = fixture.new_page(width=500, height=160)
            p.insert_text((30, 80), "HELLO OCR 12345", fontsize=30)
            p.get_pixmap(matrix=fitz.Matrix(2, 2)).save(image)
        self.engine.from_images([image])
        self.assertFalse(self.engine.text(0).strip())
        images_before = len(self.engine.doc[0].get_images())
        progress = []
        with patch.object(tempfile, "tempdir", str(self.root)):
            self.engine.ocr("eng", lambda done, total: progress.append((done, total)))
        self.assertIn("HELLO", self.engine.text(0))
        self.assertEqual(len(self.engine.doc[0].get_images()), images_before)
        self.assertEqual(progress[-1], (1, 1))
        self.engine.undo()
        self.assertFalse(self.engine.text(0).strip())
        self.assertIsNone(self.engine.path)
        self.engine.close()
        self.engine.from_images([image])
        self.assertEqual(self.engine.page_count, 1)
        self.assertIsNone(self.engine.path)

    def test_pkcs12_signature_integrity_and_informational_inspection(self):
        from datetime import datetime, timedelta, timezone
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives.serialization import pkcs12
        from cryptography.x509.oid import NameOID
        from pyhanko.pdf_utils.reader import PdfFileReader
        from pyhanko.sign.validation import validate_pdf_signature
        from pyhanko_certvalidator import ValidationContext
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "TrazoPDF Test")])
        now = datetime.now(timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=1))
                .sign(key, hashes.SHA256()))
        pfx = self.root / "test.p12"
        pfx.write_bytes(pkcs12.serialize_key_and_certificates(b"test", key, cert, None, serialization.BestAvailableEncryption(b"testpass")))
        self.engine.add_text(0, (50, 50, 300, 100), "Signed content")
        signed = self.root / "signed.pdf"
        self.engine.sign_pkcs12(signed, pfx, "testpass", "Integrity test")
        with signed.open("rb") as stream:
            signature = PdfFileReader(stream).embedded_signatures[0]
            status = validate_pdf_signature(signature, signer_validation_context=ValidationContext(trust_roots=[signature.signer_cert], allow_fetching=False))
            self.assertTrue(status.intact)
            self.assertTrue(status.valid)
        self.engine.open(signed)
        self.assertIn("TrazoPDF Test", self.engine.inspect_signatures())

    @unittest.skipUnless(Path(r"C:\Program Files\LibreOffice\program\soffice.exe").exists() or shutil.which("soffice"), "LibreOffice not installed")
    def test_office_conversion_creates_untitled_document(self):
        from docx import Document
        source = self.root / "office.docx"
        word = Document()
        word.add_paragraph("LibreOffice conversion test")
        word.save(source)
        old_path = self.root / "old.pdf"
        self.engine.save(old_path)
        with patch.object(tempfile, "tempdir", str(self.root)):
            self.engine.convert_office(source)
        self.assertIn("LibreOffice conversion test", self.engine.text(0))
        self.assertIsNone(self.engine.path)
        self.assertTrue(self.engine.dirty)
        with fitz.open(old_path) as original:
            self.assertFalse(original[0].get_text().strip())


if __name__ == "__main__":
    unittest.main()
