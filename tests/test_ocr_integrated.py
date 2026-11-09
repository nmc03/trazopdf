"""OCR local integrado: resolución del Tesseract incluido, idiomas, enderezado y ocr_file."""
import os
import shutil
import stat
import sys
from pathlib import Path

import pymupdf as fitz
import pytest

from pdf_editor import engine as engine_module
from pdf_editor import ocr_batch

TESSERACT = shutil.which("tesseract")
needs_tesseract = pytest.mark.skipif(not TESSERACT, reason="Tesseract no instalado")
TEXT = "The quick brown fox jumps over the lazy dog. Packaging reports are searchable today."


def fake_tool(folder):
    name = "tesseract.exe" if os.name == "nt" else "tesseract"
    path = Path(folder) / "tesseract" / name
    path.parent.mkdir(parents=True)
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def scan(path, angle=0):
    """Image-only one-page PDF whose text lines are tilted by `angle` degrees."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    for row in range(12):
        page.insert_text((50, 100 + row * 40), TEXT, fontsize=14)
    image = Path(path).with_suffix(".png")
    page.get_pixmap(matrix=fitz.Matrix(2, 2).prerotate(angle), alpha=False).save(image)
    out = fitz.open()
    with fitz.open(image) as picture:
        out.insert_pdf(fitz.open("pdf", picture.convert_to_pdf()))
    out.save(path)
    return path


def found(path):
    with fitz.open(path) as doc:
        return len(doc[0].search_for("quick")) + len(doc[0].search_for("searchable"))


def test_resolution_prefers_the_copy_next_to_the_app(tmp_path, monkeypatch):
    bundled = fake_tool(tmp_path / "app")
    other = tmp_path / "system"
    other.mkdir()
    system = other / bundled.name
    system.write_text("#!/bin/sh\n")
    system.chmod(0o755)
    monkeypatch.delenv("PDFEDITOR_TESSERACT", raising=False)
    monkeypatch.setenv("PATH", str(other))
    monkeypatch.setattr(engine_module, "bundled_tool_dirs", lambda: [tmp_path / "app"])
    assert engine_module.resolve_external_tool("tesseract") == (str(bundled.resolve()), "incluido")


def test_bundled_copy_is_found_when_frozen(tmp_path, monkeypatch):
    bundled = fake_tool(tmp_path)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "TrazoPDF.exe"))
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert bundled.resolve() in [d / "tesseract" / bundled.name for d in engine_module.bundled_tool_dirs()]


def test_bundled_copy_in_a_rejected_folder_is_refused(tmp_path, monkeypatch):
    bundled = fake_tool(tmp_path)
    monkeypatch.delenv("PDFEDITOR_TESSERACT", raising=False)
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(engine_module, "bundled_tool_dirs", lambda: [tmp_path])
    # A system tesseract may still be found elsewhere; the refused copy must not be.
    assert engine_module.resolve_external_tool("tesseract", [bundled.parent])[0] != str(bundled.resolve())
    monkeypatch.chdir(bundled.parent)
    assert engine_module.resolve_external_tool("tesseract")[0] != str(bundled.resolve())


def test_relative_and_missing_bundled_copies_are_ignored(tmp_path, monkeypatch):
    monkeypatch.delenv("PDFEDITOR_TESSERACT", raising=False)
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(engine_module, "bundled_tool_dirs", lambda: [Path("relativa"), tmp_path / "vacia"])
    path, source = engine_module.resolve_external_tool("tesseract")
    assert source != "incluido"


def test_language_selection(tmp_path):
    for code in ("spa", "fra", "osd"):
        (tmp_path / f"{code}.traineddata").write_bytes(b"x")
    assert ocr_batch.available_languages(tmp_path) == ["fra", "spa"]
    assert ocr_batch.normalize_languages(["spa", "fra"]) == "spa+fra"
    assert ocr_batch.normalize_languages("spa+eng") == "spa+eng"
    assert ocr_batch.normalize_languages(None) is None
    for bad in ([], "", ["../x"], ["spa; rm"]):
        with pytest.raises(ValueError):
            ocr_batch.normalize_languages(bad)
    from pdf_editor import ui_tools
    assert {"spa", "eng", "fra", "deu", "por"} <= set(ui_tools.TESSDATA_LANGUAGES)


def test_dialog_offers_installed_languages_and_deskew(qtbot=None):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from pdf_editor import doctools_dialogs as dd
    QApplication.instance() or QApplication([])
    dialog = dd.OcrLanguagesDialog(["spa", "eng", "fra", "deu", "por"])
    assert set(dialog.checks) == {"spa", "eng", "fra", "deu", "por"}
    assert dialog.values()["deskew"] is False
    dialog.deskew.setChecked(True)
    assert dialog.values()["deskew"] is True
    dialog.close()


def test_no_network_modules_are_used_by_ocr():
    source = Path(ocr_batch.__file__).read_text(encoding="utf-8")
    assert not any(word in source for word in ("urllib", "requests", "socket", "http"))


@needs_tesseract
def test_detect_skew_reports_the_tilt(tmp_path):
    with fitz.open(scan(tmp_path / "tilt.pdf", 5)) as doc:
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(100 / 72, 100 / 72), colorspace=fitz.csGRAY, alpha=False)
    assert abs(abs(ocr_batch.detect_skew(pix)) - 5) < 1
    with fitz.open(scan(tmp_path / "flat.pdf", 0)) as doc:
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(100 / 72, 100 / 72), colorspace=fitz.csGRAY, alpha=False)
    assert ocr_batch.detect_skew(pix) == 0.0


@needs_tesseract
def test_deskew_on_a_tilted_scan_improves_or_matches_detection(tmp_path):
    source = scan(tmp_path / "tilt.pdf", 5)
    plain = ocr_batch.ocr_file(source, tmp_path / "plain.pdf", ["eng"], deskew=False)
    straight = ocr_batch.ocr_file(source, tmp_path / "straight.pdf", ["eng"], deskew=True)
    assert found(tmp_path / "straight.pdf") >= found(tmp_path / "plain.pdf")
    assert straight.words >= plain.words
    assert abs(abs(straight.skew[0]) - 5) < 1 and found(tmp_path / "straight.pdf") >= 20


@needs_tesseract
def test_orientation_is_detected_for_a_turned_scan(tmp_path):
    if not (Path(ocr_batch._bundled_tessdata()) / "osd.traineddata").is_file():
        pytest.skip("Falta osd.traineddata (tools/fetch_tessdata.ps1)")
    source = scan(tmp_path / "flat.pdf", 0)
    with fitz.open(source) as doc:
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(1, 1).prerotate(90), alpha=False)
        pix.save(tmp_path / "turned.png")
    report = ocr_batch.ocr_file(tmp_path / "turned.png", tmp_path / "turned.pdf", ["eng"], deskew=True)
    assert report.rotation.get(0) in (90, 270) and found(tmp_path / "turned.pdf") >= 20


@needs_tesseract
def test_ocr_file_makes_a_searchable_layer_with_progress(tmp_path):
    source = scan(tmp_path / "scan.pdf", 0)
    with fitz.open(source) as doc:
        assert not doc[0].get_text().strip()
    ticks = []
    report = ocr_batch.ocr_file(source, tmp_path / "out" / "scan-ocr.pdf", "eng", progress=lambda d, t: ticks.append((d, t)))
    assert ticks == [(1, 1)] and report.pages == 1 and report.skipped == 0 and report.words > 100
    assert report.path_out == str(tmp_path / "out" / "scan-ocr.pdf")
    with fitz.open(tmp_path / "out" / "scan-ocr.pdf") as doc:
        assert doc[0].search_for("quick") and "lazy" in doc[0].get_text()
        assert doc[0].get_images()
    # Already searchable: nothing is added again.
    again = ocr_batch.ocr_file(tmp_path / "out" / "scan-ocr.pdf", tmp_path / "again.pdf", "eng")
    assert again.words == 0  # mixed page: its recognized words are not duplicated


@needs_tesseract
def test_ocr_file_cancellation_leaves_no_output(tmp_path):
    source = scan(tmp_path / "scan.pdf", 0)
    with pytest.raises(InterruptedError):
        ocr_batch.ocr_file(source, tmp_path / "never.pdf", "eng", cancelled=lambda: True)
    assert not (tmp_path / "never.pdf").exists()
