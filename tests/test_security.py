"""Encryption, credentials and external-tool resolution (synthetic PDFs only)."""
import os
from pathlib import Path

import pymupdf as fitz
import pytest
from pypdf import PdfReader

from pdf_editor import engine as engine_module
from pdf_editor.engine import PDFEngine, SecurityPreservationError, encryption_info

RESTRICTED = fitz.PDF_PERM_ACCESSIBILITY | fitz.PDF_PERM_PRINT  # no modify / copy / annotate


def make_pdf(path, text="Body text", **encryption):
    with fitz.open() as doc:
        doc.new_page().insert_text((72, 100), text)
        doc.save(str(path), **encryption) if encryption else doc.save(str(path))
    return Path(path)


def aes(method=fitz.PDF_ENCRYPT_AES_256, **kw):
    return dict(encryption=method, **kw)


def probe(path, password):
    """(rc, permissions) for one password on a fresh handle."""
    with fitz.open(str(path)) as doc:
        rc = doc.authenticate(password)
        return rc, doc.permissions


def trailer_p(path):
    return PdfReader(str(path)).trailer["/Encrypt"]["/P"]


@pytest.fixture
def engine():
    e = PDFEngine()
    yield e
    e.close()


def edit(engine):
    engine.add_text(0, (50, 200, 300, 240), "edited")


# --- F1: owner-restricted file that opens without a prompt -----------------

@pytest.mark.parametrize("method", [fitz.PDF_ENCRYPT_AES_256, fitz.PDF_ENCRYPT_AES_128,
                                    fitz.PDF_ENCRYPT_RC4_128, fitz.PDF_ENCRYPT_RC4_40])
def test_restricted_file_without_open_password_is_detected_and_never_saved_unencrypted(tmp_path, engine, method):
    src = make_pdf(tmp_path / "a.pdf", **aes(method, user_pw="", owner_pw="o", permissions=RESTRICTED))
    with fitz.open(str(src)) as d:
        assert not d.needs_pass  # the trap: nothing asks for a password
    engine.open(src)
    assert engine.is_protected and engine.has_restrictions and not engine.has_owner_rights
    edit(engine)
    before = src.read_bytes()
    with pytest.raises(SecurityPreservationError) as caught:
        engine.save()
    assert caught.value.reason == "owner_unknown"
    assert "contraseña de propietario" in str(caught.value)
    assert src.read_bytes() == before
    assert not list(tmp_path.glob(".pdf-editor-*.tmp"))
    assert engine.dirty


def test_restricted_file_saves_with_same_method_permissions_after_owner_unlock(tmp_path, engine):
    src = make_pdf(tmp_path / "a.pdf", **aes(fitz.PDF_ENCRYPT_AES_128, user_pw="", owner_pw="o", permissions=RESTRICTED))
    p_before = trailer_p(src)
    engine.open(src)
    assert not engine.unlock_owner("wrong")
    assert engine.unlock_owner("o")
    edit(engine)
    engine.save()
    info = encryption_info(fitz.open(str(src)))
    assert info["method"] == fitz.PDF_ENCRYPT_AES_128  # method preserved
    assert trailer_p(src) == p_before
    assert probe(src, "o")[0] & 4
    assert probe(src, "")[0] == 2  # empty user password still opens, without owner rights
    assert probe(src, "")[1] != -4
    with fitz.open(str(src)) as d:
        assert "edited" in d[0].get_text()


def test_unprotected_file_is_still_saved_unprotected(tmp_path, engine):
    src = make_pdf(tmp_path / "plain.pdf")
    engine.open(src)
    edit(engine)
    engine.save()
    assert encryption_info(fitz.open(str(src))) is None


# --- F2: credential roles --------------------------------------------------

def test_user_password_never_promoted_to_owner(tmp_path, engine):
    src = make_pdf(tmp_path / "b.pdf", **aes(user_pw="u", owner_pw="o", permissions=RESTRICTED))
    engine.open(src, "u")
    assert not engine.has_owner_rights
    edit(engine)
    with pytest.raises(SecurityPreservationError):
        engine.save()
    assert probe(src, "u")[0] == 2  # file untouched


def test_user_password_then_owner_unlock_preserves_both(tmp_path, engine):
    src = make_pdf(tmp_path / "b.pdf", **aes(user_pw="u", owner_pw="o", permissions=RESTRICTED))
    engine.open(src, "u")
    assert engine.unlock_owner("o")
    edit(engine)
    engine.save()
    assert probe(src, "u")[0] == 2
    assert probe(src, "o")[0] & 4
    assert probe(src, "x")[0] == 0
    assert probe(src, "u")[1] != -4


def test_owner_opening_keeps_user_password_or_refuses(tmp_path, engine):
    src = make_pdf(tmp_path / "c.pdf", **aes(user_pw="u", owner_pw="o", permissions=RESTRICTED))
    engine.open(src, "o")
    assert engine.has_owner_rights
    edit(engine)
    with pytest.raises(SecurityPreservationError) as caught:
        engine.save()
    assert caught.value.reason == "user_unknown"
    # never "user_pw = o": the file on disk is intact
    assert probe(src, "u")[0] == 2 and probe(src, "o")[0] & 4


def test_unrestricted_user_only_file_keeps_user_password_with_fresh_owner(tmp_path, engine):
    src = make_pdf(tmp_path / "d.pdf", **aes(user_pw="secret", owner_pw="owner"))
    engine.open(src, "secret")
    edit(engine)
    engine.save()
    assert probe(src, "secret")[0] == 2  # user does not become owner
    assert probe(src, "owner")[0] == 0   # original owner password cannot be kept
    assert engine.save_notes


def test_wrong_password_leaves_current_document(tmp_path, engine):
    src = make_pdf(tmp_path / "e.pdf", **aes(user_pw="u", owner_pw="o"))
    engine.add_text(0, (50, 50, 300, 100), "current")
    with pytest.raises(ValueError):
        engine.open(src, "nope")
    assert "current" in engine.text(0)
    engine.open(src, "u")
    assert "Body text" in engine.text(0)


# --- F3: protecting a copy -------------------------------------------------

def test_protect_copy_does_not_reuse_old_password(tmp_path, engine):
    src = make_pdf(tmp_path / "x.pdf", **aes(user_pw="x", owner_pw="xo"))
    engine.open(src, "x")
    out = tmp_path / "y.pdf"
    owner = engine.protect(out, "y")
    assert owner and owner not in ("x", "xo", "y") and len(owner) >= 24
    assert probe(out, "x")[0] == 0 and probe(out, "xo")[0] == 0
    assert probe(out, "y")[0] == 2
    assert probe(out, owner)[0] & 4


def test_protect_copy_of_unprotected_document_generates_owner_and_explicit_owner_is_used(tmp_path, engine):
    engine.add_text(0, (50, 50, 300, 100), "hello")
    a = tmp_path / "a.pdf"
    generated = engine.protect(a, "pw")
    assert generated and probe(a, generated)[0] & 4 and probe(a, "pw")[0] == 2
    b = tmp_path / "b.pdf"
    assert engine.protect(b, "pw2", owner_password="boss") == "boss"
    assert probe(b, "boss")[0] & 4
    with pytest.raises(ValueError):
        engine.protect(tmp_path / "c.pdf", "same", owner_password="same")
    with pytest.raises(ValueError):
        engine.protect(tmp_path / "d.pdf", "")


def test_generated_owner_is_kept_for_following_saves(tmp_path, engine):
    out = tmp_path / "p.pdf"
    owner = engine.protect(out, "pw", permissions=RESTRICTED)
    edit(engine)
    engine.save()
    assert probe(out, "pw")[0] == 2 and probe(out, owner)[0] & 4
    assert probe(out, "pw")[1] != -4


def test_explicit_unprotected_copy(tmp_path, engine):
    src = make_pdf(tmp_path / "r.pdf", **aes(user_pw="", owner_pw="o", permissions=RESTRICTED))
    engine.open(src)
    out = tmp_path / "open.pdf"
    engine.save_unprotected_copy(out)
    assert encryption_info(fitz.open(str(out))) is None
    assert not engine.is_protected


# --- security state survives history operations ---------------------------

def test_security_survives_edit_link_undo_redo_save(tmp_path, engine):
    src = make_pdf(tmp_path / "h.pdf", **aes(user_pw="u", owner_pw="o", permissions=RESTRICTED))
    p_before = trailer_p(src)
    engine.open(src, "u")
    assert engine.unlock_owner("o")
    edit(engine)
    engine.set_link(0, (50, 300, 200, 330), uri="https://example.com")
    engine.undo()
    engine.redo()
    engine.save()
    assert trailer_p(src) == p_before
    assert probe(src, "u")[0] == 2 and probe(src, "o")[0] & 4


def test_failed_mutation_keeps_security_state(tmp_path, engine):
    src = make_pdf(tmp_path / "h.pdf", **aes(user_pw="u", owner_pw="o", permissions=RESTRICTED))
    engine.open(src, "u")
    with pytest.raises(ValueError):
        engine.add_text(0, (50, 50, 51, 51), "does not fit in this tiny area " * 5)
    assert engine.is_protected and engine.has_restrictions


# --- batch path ------------------------------------------------------------

def test_batch_style_worker_errors_without_writing_output(tmp_path):
    src = make_pdf(tmp_path / "g.pdf", **aes(user_pw="", owner_pw="o", permissions=RESTRICTED))
    target = tmp_path / "g_procesado.pdf"
    worker = PDFEngine()
    try:
        worker.open(src)
        worker.number_pages()
        with pytest.raises(SecurityPreservationError):
            worker.save(str(target))
    finally:
        worker.close()
    assert not target.exists()


# --- comments removal rollback --------------------------------------------

def test_delete_annotation_rolls_back_on_failure(tmp_path, engine, monkeypatch):
    engine.annotate(0, (50, 50, 100, 100), "note", "hi")
    engine.save(tmp_path / "n.pdf")  # garbage collection may renumber live xrefs
    xref = next(engine.doc[0].annots()).xref
    undo_depth = len(engine._undo)
    monkeypatch.setattr(fitz.Page, "delete_annot", lambda self, annot: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        engine.delete_annotation(0, xref)
    assert len(engine._undo) == undo_depth
    assert len(list(engine.doc[0].annots())) == 1
    monkeypatch.undo()
    engine.delete_annotation(0, xref)
    assert not list(engine.doc[0].annots())
    engine.undo()
    assert len(list(engine.doc[0].annots())) == 1


# --- F8 external tools -----------------------------------------------------

def fake_tool(folder, name="tesseract"):
    folder.mkdir(parents=True, exist_ok=True)
    exe = folder / (name + (".exe" if os.name == "nt" else ""))
    exe.write_bytes(b"x")
    exe.chmod(0o755)
    return exe


def test_env_override_wins_over_path(tmp_path, monkeypatch):
    trusted = fake_tool(tmp_path / "trusted")
    on_path = fake_tool(tmp_path / "pathdir")
    monkeypatch.setenv("PDFEDITOR_TESSERACT", str(trusted))
    monkeypatch.setenv("PATH", str(on_path.parent))
    path, source = engine_module.resolve_external_tool("tesseract")
    assert Path(path) == trusted.resolve() and source == "variable de entorno"
    assert engine_module.external_tools()["tesseract"] == path


def test_tool_in_cwd_or_document_folder_is_rejected(tmp_path, monkeypatch):
    planted = fake_tool(tmp_path / "docs")
    other = fake_tool(tmp_path / "elsewhere")
    monkeypatch.setattr(engine_module, "_tool_candidates", lambda name: iter([("PATH", str(planted)), ("PATH", str(other))]))
    monkeypatch.chdir(tmp_path / "elsewhere")
    assert engine_module.resolve_external_tool("tesseract", [str(tmp_path / "docs")]) == (None, None)
    monkeypatch.chdir(tmp_path)
    path, _ = engine_module.resolve_external_tool("tesseract", [str(tmp_path / "docs")])
    assert Path(path) == other.resolve()


def test_relative_and_missing_candidates_are_ignored(tmp_path, monkeypatch):
    fake_tool(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PDFEDITOR_TESSERACT", raising=False)
    monkeypatch.setattr(engine_module, "_tool_candidates", lambda name: iter([("PATH", "tesseract"), ("PATH", "."), ("PATH", str(tmp_path / "nope.exe"))]))
    assert engine_module.resolve_external_tool("tesseract") == (None, None)


def test_engine_excludes_open_document_folder(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    planted = fake_tool(docs)
    monkeypatch.setenv("PDFEDITOR_TESSERACT", str(planted))
    monkeypatch.chdir(tmp_path)
    e = PDFEngine()
    try:
        e.save(docs / "a.pdf")
        assert e.external_tools()["tesseract"] != str(planted.resolve())
        assert engine_module.resolve_external_tool("tesseract")[0] == str(planted.resolve())
        with pytest.raises(ValueError):
            monkeypatch.setattr(engine_module, "_tool_candidates", lambda name: iter([("variable de entorno", str(planted))]))
            e.ocr("eng")
    finally:
        e.close()
