"""Regression tests for the review findings: flatten gate, worker flags, stale temp folders, patterns, theme."""
import json
import os
import subprocess
import sys
import time

import pymupdf as fitz
import pytest

from pdf_editor import doctools as dt
from test_review_fixes import SECRET, app_window, pick, qapp  # noqa: F401  (fixtures)


# --------------------------------------------------------------- C1 flatten

def test_doctools_flatten_never_bakes_redaction_marks():
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), SECRET, fontsize=14)
    page.add_redact_annot(page.search_for(SECRET)[0], fill=(0, 0, 0))
    page.add_highlight_annot(page.search_for(SECRET)[0])
    assert dt.flatten(doc) == 1
    assert [a.type[0] for a in doc[0].annots()] == [fitz.PDF_ANNOT_REDACT]
    assert SECRET in doc[0].get_text()


def test_engine_flatten_is_gated_by_pending_redactions():
    from pdf_editor.engine import PDFEngine, PendingRedactionsError
    engine = PDFEngine()
    engine.new()
    engine.doc[0].insert_text((72, 100), SECRET, fontsize=14)
    engine.annotate(0, (60, 80, 320, 118), "redact")
    with pytest.raises(PendingRedactionsError):
        engine.flatten()
    assert engine.pending_redactions()
    engine.flatten(allow_pending_redactions=True)
    assert engine.pending_redactions()   # flattening must not hide them from the save gate
    with pytest.raises(PendingRedactionsError):
        engine.save(os.devnull)


def test_flatten_action_offers_apply_now(app_window, monkeypatch):
    from pdf_editor import doctools_dialogs
    monkeypatch.setattr(doctools_dialogs.FlattenDialog, "exec", lambda self: 1)
    monkeypatch.setattr(doctools_dialogs.FlattenDialog, "values", lambda self: {"annotations": True, "forms": True})
    app_window.engine.annotate(0, (60, 80, 320, 118), "redact")
    pick(monkeypatch, "Aplicar censuras ahora")
    app_window.flatten()
    assert not app_window.engine.pending_redactions()
    assert SECRET not in app_window.engine.text(0)


# ------------------------------------------------------- C2 / P1 worker

def test_worker_forwards_allow_pending_and_reject_dirs(tmp_path, monkeypatch):
    from pdf_editor import engine as engine_module
    from pdf_editor.worker import run_worker
    source = fitz.open()
    page = source.new_page()
    page.insert_text((72, 100), "texto", fontsize=14)
    page.add_redact_annot(fitz.Rect(60, 80, 200, 110))
    source.save(tmp_path / "source.pdf")
    seen = []
    real = engine_module.resolve_external_tool
    monkeypatch.setattr(engine_module, "resolve_external_tool",
                        lambda name, reject_dirs=(): seen.append(list(reject_dirs)) or real(name, reject_dirs))

    def run(allow):
        for leftover in ("result.json", "output.pdf"):
            (tmp_path / leftover).unlink(missing_ok=True)
        request = {"operation": "ocr", "language": "eng", "allow_pending": allow, "reject_dirs": [str(tmp_path / "original")]}
        (tmp_path / "request.json").write_text(json.dumps(request), encoding="utf-8")
        run_worker(tmp_path / "request.json")
        return json.loads((tmp_path / "result.json").read_text())

    refused = run(False)
    assert not refused["ok"] and "censura" in refused["error"]
    allowed = run(True)
    assert allowed["ok"], allowed
    assert (tmp_path / "output.pdf").is_file()
    assert any(str(tmp_path / "original") in dirs for dirs in seen)


def test_external_job_sends_flag_and_document_folder(app_window, monkeypatch, tmp_path):
    import pdf_editor.app as app_module
    document = tmp_path / "doc.pdf"
    app_window.engine.save(document)
    sent = []
    real = app_module.QProcess.start

    def spy(process, program, arguments):
        sent.append(json.loads(open(arguments[-1], encoding="utf-8").read()))
        return real(process, program, arguments)

    monkeypatch.setattr(app_module.QProcess, "start", spy)
    app_window.external_job("check", "Comprobando", allow_pending=True)
    assert sent[0]["allow_pending"] is True
    assert sent[0]["reject_dirs"] == [str(tmp_path.resolve())]


# ------------------------------------------------------------------ P2

@pytest.mark.skipif(os.name != "nt", reason="uses Windows process names")
def test_purge_removes_orphaned_job_folders_regardless_of_age(tmp_path):
    from pdf_editor.app import OWNER_FILE, purge_stale_jobs
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    other = subprocess.Popen(["ping", "-n", "20", "127.0.0.1"], stdout=subprocess.DEVNULL)
    try:
        folders = {}
        for name, pid in (("orphan", dead.pid), ("live", os.getpid()), ("reused", other.pid)):
            folder = tmp_path / f"pdf-editor-job-{name}"
            folder.mkdir()
            (folder / "source.pdf").write_bytes(b"x")
            (folder / OWNER_FILE).write_text(str(pid))
            folders[name] = folder
        (tmp_path / "pdf-editor-compare-orphan").mkdir()
        (tmp_path / "pdf-editor-compare-orphan" / OWNER_FILE).write_text(str(dead.pid))
        assert purge_stale_jobs(tmp_path) == 3
        assert folders["live"].exists()
        assert not folders["orphan"].exists() and not folders["reused"].exists()
        assert not (tmp_path / "pdf-editor-compare-orphan").exists()
    finally:
        other.kill()
        other.wait()


def test_job_folders_record_their_owner(app_window, monkeypatch):
    import pdf_editor.app as app_module
    seen = []
    real = app_module.QProcess.start

    def spy(process, program, arguments):
        folder = os.path.dirname(arguments[-1])
        seen.append(open(os.path.join(folder, app_module.OWNER_FILE)).read())
        return real(process, program, arguments)

    monkeypatch.setattr(app_module.QProcess, "start", spy)
    app_window.external_job("check", "Comprobando")
    assert seen == [str(os.getpid())]


# ------------------------------------------------------------------ P3

def test_compare_text_goes_through_the_redaction_gate(app_window, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog
    other = fitz.open()
    other.new_page().insert_text((72, 100), "otro", fontsize=12)
    path = tmp_path / "otro.pdf"
    other.save(path)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(path), "PDF"))
    shown = []
    monkeypatch.setattr(app_window, "text_report", lambda title, text: shown.append(text))
    app_window.engine.annotate(0, (60, 80, 320, 118), "redact")
    pick(monkeypatch, "Cancelar")
    app_window.compare_text()
    assert not shown
    pick(monkeypatch, "Continuar de todos modos")
    app_window.compare_text()
    assert shown


def test_engine_compare_text_requires_no_pending_redactions():
    from pdf_editor.engine import PDFEngine, PendingRedactionsError
    engine = PDFEngine()
    engine.new()
    engine.annotate(0, (60, 80, 320, 118), "redact")
    with pytest.raises(PendingRedactionsError):
        engine.compare_text(fitz.open())


# ------------------------------------------------------------------ P4

def test_theme_survives_unwritable_asset_folder(qapp, monkeypatch):
    from pdf_editor import theme
    monkeypatch.setattr(theme, "_asset_paths", {})
    monkeypatch.setattr(theme, "write_assets", lambda *a, **k: (_ for _ in ()).throw(PermissionError("no")))
    qapp.setStyleSheet("")
    name = theme.apply_theme(qapp, "light")
    assert name == "light"
    assert qapp.styleSheet() == theme.build_style(theme.THEMES["light"])
    qapp.setStyleSheet(theme.STYLE)


# ------------------------------------------------------------------ C4

@pytest.mark.parametrize("text,expected", [
    ("DNI 12.345.678-Z fin", "12.345.678-Z"),
    ("DNI 12.345.678 Z fin", "12.345.678 Z"),
    ("DNI 12345678Z fin", "12345678Z"),
    ("Tel (+34) 612345678 fin", "(+34) 612345678"),
    ("Tel (+34) 612 345 678 fin", "(+34) 612 345 678"),
    ("Tel +34 612345678 fin", "+34 612345678"),
])
def test_dni_and_phone_variants_are_detected_whole(text, expected):
    doc = fitz.open()
    doc.new_page().insert_text((40, 100), text, fontsize=11)
    found = dt.find_matches(doc, ["dni_nie", "telefono_es"])
    assert [m["text"] for m in found] == [expected]


def test_dotted_dni_with_wrong_letter_or_plain_numbers_are_ignored():
    doc = fitz.open()
    doc.new_page().insert_text((40, 100), "12.345.678-A  1.234.567  12.345.678  45.123.456", fontsize=11)
    assert dt.find_matches(doc, ["dni_nie"]) == []
