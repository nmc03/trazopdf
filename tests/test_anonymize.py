"""Anonymisation: nothing personal survives in any decompressed byte; the original is untouched."""
import hashlib
import json
import socket
import zlib
from pathlib import Path

import pymupdf as fitz
import pytest

from pdf_editor import anonymize as an

DNI = "12345678Z"
IBAN = "ES9121000418450200051332"
MAIL = "maria.lopez@example.com"
META = "73456789X"          # valid DNI used only in metadata
ATT = "87654321X"           # valid DNI used only in the attachment
NOTE = "11111111H"          # valid DNI used only in an annotation
SECRETS = [DNI, IBAN, MAIL, META, ATT, NOTE]


def build(path, *, encrypt=False):
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((72, 100), f"DNI {DNI} del titular", fontsize=12)
        page.insert_text((72, 130), f"IBAN {IBAN}", fontsize=12)
        page.insert_text((72, 160), f"Correo {MAIL}", fontsize=12)
        page.insert_text((72, 400), "Parrafo publico sin datos", fontsize=12)
        note = page.add_text_annot((300, 300), f"Anotacion con {NOTE}")
        note.set_info(title="Autor", subject="Nota")
        note.update()
        doc.set_metadata({"title": f"Ficha {META}", "author": "Autor"})
        doc.embfile_add("datos.txt", f"cliente {ATT}".encode())
        doc.set_toc([[1, f"Seccion {DNI}", 1]])
        if encrypt:
            doc.save(str(path), encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="u", owner_pw="o")
        else:
            doc.save(str(path), garbage=0)
            # incremental update: a second revision, as editors produce
            with fitz.open(str(path)) as again:
                again[0].insert_text((72, 450), "revision", fontsize=8)
                again.saveIncr()
    return Path(path)


def everything(path):
    data = Path(path).read_bytes()
    chunks = [data]
    with fitz.open(str(path)) as doc:
        for xref in range(1, doc.xref_length()):
            try:
                chunks.append(doc.xref_object(xref).encode("latin-1", "replace"))
                if doc.xref_is_stream(xref):
                    chunks.append(doc.xref_stream(xref) or b"")
            except Exception:
                pass
    return b"\n".join(chunks)


def has(blob, secret):
    """Plain, hex-string (content streams) or UTF-16 forms of a secret inside the blob."""
    blob = blob.lower()
    forms = [secret.encode().lower(), secret.encode().hex().encode(), secret.encode("utf-16-be").lower()]
    return any(f in blob for f in forms)


@pytest.fixture
def src(tmp_path):
    return build(tmp_path / "in.pdf")


def test_no_secret_survives_and_original_untouched(src, tmp_path):
    before = hashlib.sha256(src.read_bytes()).hexdigest()
    assert all(has(everything(src), s) for s in SECRETS)
    out = tmp_path / "out.pdf"
    report = an.anonymize(src, out, {"patterns": ["email", "iban", "dni_nie"]})
    assert report.ok and report.output == str(out.resolve())
    assert hashlib.sha256(src.read_bytes()).hexdigest() == before
    blob = everything(out).lower()
    for secret in SECRETS:
        assert not has(blob, secret)
    with fitz.open(str(out)) as doc:
        assert "Parrafo publico" in doc[0].get_text()
        assert doc.embfile_count() == 0 and not doc.get_toc() and not (doc.get_xml_metadata() or "").strip()
        assert not [a for a in doc[0].annots()]
    assert out.read_bytes().count(b"%%EOF") == 1
    assert not list(tmp_path.glob(".anonimizar-*"))


def test_report_counts_by_type_without_the_data(src, tmp_path):
    report = an.anonymize(src, tmp_path / "o.pdf", {"patterns": ["email", "iban", "dni_nie"]})
    assert report.matches_by_type["email"] == 1
    assert report.matches_by_type["iban"] == 1
    assert report.matches_by_type["dni_nie"] >= 4   # text, bookmark, metadata, attachment, annotation
    assert set(report.locations) >= {"texto", "anotaciones", "metadatos", "adjuntos"}
    text, as_json = report.to_text(), report.to_json()
    for secret in SECRETS:
        assert secret not in text and secret not in as_json
    assert json.loads(as_json)["ok"] is True
    for suffix in ("txt", "json"):
        an.write_report(report, tmp_path / f"r.{suffix}")
        assert (tmp_path / f"r.{suffix}").read_text(encoding="utf-8")


def test_user_terms_and_regex(tmp_path):
    path = tmp_path / "t.pdf"
    with fitz.open() as doc:
        doc.new_page().insert_text((72, 100), "Cliente Acme Corp expediente EXP-2291 firmado", fontsize=12)
        doc.save(str(path))
    out = tmp_path / "t-out.pdf"
    report = an.anonymize(path, out, {"patterns": [], "terms": ["Acme Corp"], "regexes": [r"EXP-\d{4}"]})
    assert report.ok
    assert report.matches_by_type == {"terminos": 1, "regex": 1}
    blob = everything(out)
    assert not has(blob, "Acme") and not has(blob, "EXP-2291")
    with fitz.open(str(out)) as doc:
        assert "Cliente" in doc[0].get_text()


def test_exclusions_from_preview(src, tmp_path):
    rules = {"patterns": ["email", "iban"]}
    found = an.preview(src, rules)
    assert {m["pattern"] for m in found} == {"email", "iban"}
    keep = next(m["id"] for m in found if m["pattern"] == "email")
    out = tmp_path / "o.pdf"
    report = an.anonymize(src, out, {**rules, "exclude": [keep]})
    assert report.matches_by_type.get("email", 0) == 0 and report.matches_by_type["iban"] == 1
    with fitz.open(str(out)) as doc:
        assert MAIL in doc[0].get_text() and IBAN not in doc[0].get_text()


def test_encrypted_is_rejected(tmp_path):
    enc = build(tmp_path / "enc.pdf", encrypt=True)
    with pytest.raises(ValueError, match="cifrado"):
        an.anonymize(enc, tmp_path / "o.pdf", {"patterns": ["email"]})
    with pytest.raises(ValueError, match="cifrado"):
        an.preview(enc, {"patterns": ["email"]})
    assert not (tmp_path / "o.pdf").exists()


def test_invalid_regex_gives_clear_error(src, tmp_path):
    with pytest.raises(ValueError, match="expresión regular"):
        an.anonymize(src, tmp_path / "o.pdf", {"patterns": [], "regexes": ["(sin cerrar"]})
    assert not (tmp_path / "o.pdf").exists()


def test_rules_need_something_and_paths_differ(src, tmp_path):
    with pytest.raises(ValueError):
        an.anonymize(src, tmp_path / "o.pdf", {"patterns": []})
    with pytest.raises(ValueError, match="distinto"):
        an.anonymize(src, src, {"patterns": ["email"]})


def test_ocr_layer_text_is_removed(tmp_path):
    path = tmp_path / "ocr.pdf"
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((72, 100), f"Escaneado {MAIL}", fontsize=12, render_mode=3)  # invisible OCR text
        doc.save(str(path))
    out = tmp_path / "ocr-out.pdf"
    report = an.anonymize(path, out, {"patterns": ["email"]})
    assert report.ok and not has(everything(out), MAIL)


def test_verification_failure_withholds_output(src, tmp_path, monkeypatch):
    monkeypatch.setattr(an, "_deep_sanitize", lambda engine, secrets, options: {})
    out = tmp_path / "bad.pdf"
    report = an.anonymize(src, out, {"patterns": ["email"]})
    assert not report.ok and report.output is None and not out.exists()
    assert any(not c.ok for c in report.checks)


def test_verify_file_detects_leftovers(src):
    assert any(not c.ok for c in an.verify_file(src, [DNI]))


def test_works_offline(src, tmp_path, monkeypatch):
    def deny(*a, **k):
        raise AssertionError("network access")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "getaddrinfo", deny)
    assert an.anonymize(src, tmp_path / "o.pdf", {"patterns": ["email"]}).ok


def test_dialog_flow(src, tmp_path):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from pdf_editor.anonymize_dialog import AnonymizeDialog
    QApplication.instance() or QApplication([])
    dialog = AnonymizeDialog(src)
    dialog.output.setText(str(tmp_path / "dlg.pdf"))
    dialog.search()
    assert dialog.matches and dialog.ok_button.isEnabled()
    dialog.results.item(0).setCheckState(__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.Unchecked)
    assert len(dialog.excluded_ids()) == 1
    dialog.run_anonymize()
    assert dialog.report.ok and (tmp_path / "dlg.pdf").exists()
    assert MAIL not in dialog.report_view.toPlainText()
