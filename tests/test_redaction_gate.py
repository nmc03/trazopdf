"""Pending redactions must block output; applying them must leave no trace."""
from pathlib import Path

import pymupdf as fitz
import pytest

from pdf_editor.engine import PDFEngine, PendingRedactionsError

SECRET = "ZEBRA-4417-CONFIDENTIAL"


@pytest.fixture
def engine():
    e = PDFEngine()
    yield e
    e.close()


def marked_engine(engine):
    """One page with a secret plus a widget, a link and a note under it."""
    page = engine.doc[0]
    page.insert_text((72, 100), SECRET, fontsize=14)
    page.insert_text((72, 300), "Public paragraph", fontsize=14)
    engine.add_field(0, (72, 90, 300, 110), "secretfield")
    engine.fill_form(0, engine.forms()[0]["xref"], SECRET + "-widget")
    engine.set_link(0, (72, 85, 300, 112), uri="https://example.com/" + "leak")
    engine.annotate(0, (80, 80, 90, 90), "note", SECRET + " note")
    engine.set_metadata({"title": "Report " + SECRET, "author": "Someone"})
    engine.set_bookmarks([[1, "Section " + SECRET, 1]])
    engine.annotate(0, (60, 80, 320, 118), "redact")
    return engine


def everything(data):
    """All decoded object bodies and streams, plus the raw bytes."""
    chunks = [data]
    with fitz.open(stream=data, filetype="pdf") as doc:
        for xref in range(1, doc.xref_length()):
            try:
                chunks.append(doc.xref_object(xref).encode("latin-1", "replace"))
                if doc.xref_is_stream(xref):
                    chunks.append(doc.xref_stream(xref) or b"")
            except Exception:
                pass
    return b"\n".join(chunks)


def test_pending_redactions_listed(engine):
    assert engine.pending_redactions() == []
    engine.annotate(0, (50, 50, 150, 80), "redact")
    pending = engine.pending_redactions()
    assert len(pending) == 1 and pending[0]["page"] == 0


@pytest.mark.parametrize("call", [
    lambda e, r: e.save(r / "o.pdf"),
    lambda e, r: e.save(r / "o.pdf", password="x"),
    lambda e, r: e.protect(r / "o.pdf", "x"),
    lambda e, r: e.extract([0], r / "o.pdf"),
    lambda e, r: e.split(r / "split"),
    lambda e, r: e.export_text(r / "o.txt"),
    lambda e, r: e.export_images(r / "imgs"),
    lambda e, r: e.export_docx(r / "o.docx"),
    lambda e, r: e.export_xlsx(r / "o.xlsx"),
    lambda e, r: e.export_pptx(r / "o.pptx"),
    lambda e, r: e.sign_pkcs12(r / "o.pdf", r / "nope.p12", "pw"),
    lambda e, r: e.require_no_pending_redactions(),
])
def test_output_operations_refuse_pending_redactions(tmp_path, engine, call):
    engine.doc[0].insert_text((72, 100), SECRET)
    engine.annotate(0, (60, 80, 320, 118), "redact")
    with pytest.raises(PendingRedactionsError) as caught:
        call(engine, tmp_path)
    assert len(caught.value.pending) == 1
    assert "censura" in str(caught.value)
    assert not any(p.is_file() and p.suffix in (".pdf", ".txt", ".docx", ".xlsx", ".pptx", ".png") for p in tmp_path.rglob("*"))


def test_explicit_flag_allows_saving_pending(tmp_path, engine):
    engine.annotate(0, (60, 80, 320, 118), "redact")
    engine.save(tmp_path / "o.pdf", allow_pending_redactions=True)
    engine.extract([0], tmp_path / "e.pdf", allow_pending_redactions=True)
    assert (tmp_path / "o.pdf").exists() and (tmp_path / "e.pdf").exists()


def test_after_applying_everything_is_allowed_and_secret_is_gone(tmp_path, engine):
    marked_engine(engine)
    assert SECRET.encode() in everything(engine._bytes())  # sanity: it is really there
    engine.apply_redactions()
    assert engine.pending_redactions() == []
    out = tmp_path / "clean.pdf"
    engine.save(out)
    data = everything(out.read_bytes())
    assert SECRET.encode() not in data
    assert b"ZEBRA" not in data
    with fitz.open(str(out)) as doc:
        text = doc[0].get_text()
        assert "Public paragraph" in text and "ZEBRA" not in text
        assert not list(doc[0].widgets() or ())
        assert not doc[0].get_links()
        assert not list(doc[0].annots() or ())
        assert SECRET not in doc.metadata["title"] and doc.metadata["author"] == "Someone"
        assert all("ZEBRA" not in item[1] for item in doc.get_toc())


def test_other_exports_are_clean_after_applying(tmp_path, engine):
    marked_engine(engine)
    engine.apply_redactions()
    engine.export_text(tmp_path / "t.txt")
    engine.extract([0], tmp_path / "e.pdf")
    assert "ZEBRA" not in (tmp_path / "t.txt").read_text(encoding="utf-8")
    assert b"ZEBRA" not in everything((tmp_path / "e.pdf").read_bytes())


def test_redaction_leaves_unrelated_widget_and_link(tmp_path, engine):
    engine.add_field(0, (72, 500, 300, 520), "keep")
    engine.set_link(0, (72, 600, 200, 620), uri="https://example.com/ok")
    engine.doc[0].insert_text((72, 100), SECRET)
    engine.annotate(0, (60, 80, 320, 118), "redact")
    engine.apply_redactions()
    assert [f["name"] for f in engine.forms()] == ["keep"]
    assert len(engine.links(0)) == 1


def test_undo_restores_pending_marks(engine):
    marked_engine(engine)
    engine.apply_redactions()
    engine.undo()
    assert len(engine.pending_redactions()) == 1
    with pytest.raises(PendingRedactionsError):
        engine.save(Path("unused.pdf"))
