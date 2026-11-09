import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from pyhanko.pdf_utils.reader import PdfFileReader
from asn1crypto import keys, x509 as asn1_x509
from pyhanko.sign.timestamps import TimeStamper
from pyhanko.sign.timestamps.dummy_client import DummyTimeStamper
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from pdf_editor.engine import PDFEngine, TimestampError
from pdf_editor.signing import SETTINGS_ENABLED, SETTINGS_URL, SigningOptionsDialog


class FailingStamper(TimeStamper):
    def __init__(self):
        super().__init__()
        self.calls = 0

    async def async_request_tsa_response(self, req):
        self.calls += 1
        raise ConnectionError("network down")

    def request_tsa_response(self, req):
        self.calls += 1
        raise ConnectionError("network down")


def local_stamper():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Local TSA")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=1))
            .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.TIME_STAMPING]), critical=True)
            .sign(key, hashes.SHA256()))
    der_key = key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    return DummyTimeStamper(asn1_x509.Certificate.load(cert.public_bytes(serialization.Encoding.DER)),
                            keys.PrivateKeyInfo.load(der_key))


def has_token(signature):
    info = signature.signed_data["signer_infos"][0]
    return any(a["type"].native == "signature_time_stamp_token" for a in (info["unsigned_attrs"] or []))


def make_pfx(root):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Stamp Test")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=1)).sign(key, hashes.SHA256()))
    pfx = root / "t.p12"
    pfx.write_bytes(pkcs12.serialize_key_and_certificates(b"t", key, cert, None, serialization.BestAvailableEncryption(b"pw")))
    return pfx


class TimestampTests(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        self.engine = PDFEngine()
        self.engine.new()
        self.pfx = make_pfx(self.root)

    def tearDown(self):
        self.engine.close()
        self.dir.cleanup()

    def test_no_stamper_signs_without_network(self):
        out = self.root / "a.pdf"
        self.engine.sign_pkcs12(out, self.pfx, "pw")
        with out.open("rb") as f:
            self.assertEqual(len(PdfFileReader(f).embedded_signatures), 1)

    def test_stamper_adds_timestamp_token(self):
        stamped, plain = self.root / "s.pdf", self.root / "p.pdf"
        self.engine.sign_pkcs12(stamped, self.pfx, "pw", timestamper=local_stamper())
        self.engine.sign_pkcs12(plain, self.pfx, "pw")
        with stamped.open("rb") as f:
            self.assertTrue(has_token(PdfFileReader(f).embedded_signatures[0]))
        with plain.open("rb") as f:
            self.assertFalse(has_token(PdfFileReader(f).embedded_signatures[0]))

    def test_network_error_reports_and_leaves_no_file(self):
        out = self.root / "b.pdf"
        stamper = FailingStamper()
        with self.assertRaises(TimestampError) as ctx:
            self.engine.sign_pkcs12(out, self.pfx, "pw", timestamper=stamper)
        self.assertIn("sello de tiempo", str(ctx.exception))
        self.assertEqual(stamper.calls, 1)
        self.assertFalse(out.exists())
        self.engine.sign_pkcs12(out, self.pfx, "pw")
        self.assertTrue(out.exists())

    def test_options_dialog_remembers_and_defaults_off(self):
        settings = QSettings(str(self.root / "s.ini"), QSettings.Format.IniFormat)
        dialog = SigningOptionsDialog(None, settings)
        self.assertFalse(dialog.use_timestamp.isChecked())
        self.assertEqual(dialog.url.text(), "")
        self.assertIsNone(dialog.timestamp_url())
        dialog.use_timestamp.setChecked(True)
        dialog.url.setText("https://tsa.example/ts")
        dialog.accept_options()
        self.assertEqual(dialog.timestamp_url(), "https://tsa.example/ts")
        again = SigningOptionsDialog(None, settings)
        self.assertTrue(again.use_timestamp.isChecked())
        self.assertEqual(again.url.text(), "https://tsa.example/ts")
        self.assertTrue(settings.value(SETTINGS_ENABLED, False, type=bool))
        self.assertEqual(settings.value(SETTINGS_URL, "", type=str), "https://tsa.example/ts")


if __name__ == "__main__":
    unittest.main()
