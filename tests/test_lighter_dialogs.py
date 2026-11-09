"""Lighter tool dialogs: banners with Deshacer, one protect dialog, OCR languages, export and print, Office guard."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf as fitz
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QInputDialog, QLabel, QMenu, QMessageBox, QPushButton

from pdf_editor import doctools_dialogs as dd, ui_tools
from pdf_editor.app import EditorWindow, STYLE
from pdf_editor.toast import banner_for


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    a.setStyleSheet(STYLE)
    return a


@pytest.fixture
def window(app, tmp_path):
    w = EditorWindow(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
    w.engine.new()
    w.engine.doc[0].insert_text((72, 100), "Texto de prueba", fontsize=12)
    w.engine.doc.new_page().insert_text((72, 100), "Segunda pagina", fontsize=12)
    w.engine.dirty = True
    w.refresh()
    yield w
    w.engine.dirty = False
    w.close()
    app.processEvents()


def banner_actions(window):
    """Labels of the buttons on the visible banner, or [] when it is hidden."""
    banner = banner_for(window)
    if banner.isHidden():
        return []
    labels = []
    for index in range(banner.action_layout.count()):
        widget = banner.action_layout.itemAt(index).widget()
        if widget is not None:
            labels.append(widget.text())
    return labels


def click_banner(window, label):
    banner = banner_for(window)
    for index in range(banner.action_layout.count()):
        widget = banner.action_layout.itemAt(index).widget()
        if widget is not None and widget.text() == label:
            widget.click()
            return
    raise AssertionError(f"{label!r} not on the banner")


def script_dialog(monkeypatch, cls, **values):
    monkeypatch.setattr(cls, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(cls, "values", lambda self: dict(values))


# ---------------------------------------------------------------- vocabulary

def test_redaction_dialog_uses_censurar(app):
    dialog = dd.RedactSearchDialog()
    assert "censurar" in dialog.windowTitle().lower() and "ocultar" not in dialog.windowTitle().lower()
    assert dialog.ok_button.text() == "Marcar para censurar"
    dialog.close()


# ----------------------------------------------------------------- banners

def test_watermark_is_a_banner_with_undo(window, monkeypatch):
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("BORRADOR", True))
    window.watermark()
    assert "BORRADOR" in window.engine.text(0)
    assert banner_actions(window) == ["Deshacer"]
    click_banner(window, "Deshacer")
    assert "BORRADOR" not in window.engine.text(0)


def test_number_pages_is_a_banner_with_undo(window, monkeypatch):
    monkeypatch.setattr(QInputDialog, "getInt", lambda *a, **k: (5, True))
    window.number_pages()
    assert "5" in window.engine.text(0)
    assert "Deshacer" in banner_actions(window)
    click_banner(window, "Deshacer")
    assert window.engine.page_labels() == ["1", "2"]


def test_sanitize_runs_without_confirmation_and_undoes(window, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: pytest.fail("sanear no debe pedir confirmación"))
    window.engine.doc.set_metadata({"title": "Titulo"})
    window.sanitize()
    assert not window.engine.doc.metadata.get("title")
    assert "Deshacer" in banner_actions(window)
    click_banner(window, "Deshacer")
    assert window.engine.doc.metadata.get("title") == "Titulo"


def test_flatten_reports_count_with_undo(window, monkeypatch):
    window.engine.annotate(0, (50, 200, 150, 230), "rectangle")
    script_dialog(monkeypatch, dd.FlattenDialog, annotations=True, forms=True)
    window.flatten()
    assert banner_actions(window) == ["Deshacer"]
    click_banner(window, "Deshacer")
    assert len(list(window.engine.doc[0].annots() or [])) == 1


# ------------------------------------------------------------------ protect

def test_password_strength_levels():
    assert dd.password_strength("") == ("", 0)
    assert dd.password_strength("abc") == ("Débil", 0)
    assert dd.password_strength("Abcdef12!xyz")[0] == "Fuerte"


def test_protect_dialog_validates_inline(app):
    dialog = dd.ProtectDialog()
    dialog.password.setText("corta")
    assert "al menos 8" in dialog.error.text()
    dialog.password.setText("clave-larga-1")
    dialog.repeat.setText("otra-cosa-2")
    assert "no coinciden" in dialog.error.text()
    assert dialog.validate() == "Las contraseñas no coinciden."
    dialog.repeat.setText("clave-larga-1")
    assert dialog.error.text() == "" and dialog.validate() is None
    assert dialog.values() == {"password": "clave-larga-1", "owner": "", "restrict": False}
    dialog.close()


def test_protect_dialog_reveal_toggle_shows_both_fields(app):
    dialog = dd.ProtectDialog()
    dialog.reveal.setChecked(True)
    assert dialog.password.echoMode() == dialog.repeat.echoMode() == dialog.owner.echoMode() == dialog.password.EchoMode.Normal
    dialog.close()


def test_protect_restricted_copy_blocks_print_and_copy(window, monkeypatch, tmp_path):
    script_dialog(monkeypatch, dd.ProtectDialog, password="abrir-1234", owner="duena-1234", restrict=True)
    target = tmp_path / "restringido.pdf"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), "PDF"))
    assert window.protect() is True
    with fitz.open(target) as saved:
        # Permissions bind the reader who opens with the opening password; the owner keeps full rights.
        assert saved.authenticate("abrir-1234") & 2
        assert not saved.permissions & fitz.PDF_PERM_PRINT
        assert not saved.permissions & fitz.PDF_PERM_COPY
        assert saved.permissions & fitz.PDF_PERM_ACCESSIBILITY
    with fitz.open(target) as owner_view:
        assert owner_view.authenticate("duena-1234") & 4


def test_protect_cancel_in_dialog_writes_nothing(window, monkeypatch, tmp_path):
    monkeypatch.setattr(dd.ProtectDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: pytest.fail("no debe elegir archivo"))
    assert window.protect() is False


# --------------------------------------------------------------------- OCR

def test_bundled_languages_follow_tessdata():
    langs = ui_tools.bundled_languages()
    assert langs[:2] == ["spa", "eng"] and set(langs) <= set(ui_tools.TESSDATA_LANGUAGES)


def test_ocr_offers_language_checkboxes_when_several_installed(window, monkeypatch):
    script_dialog(monkeypatch, dd.OcrLanguagesDialog, languages=["spa"])
    seen = []
    monkeypatch.setattr(window, "external_job", lambda operation, text, **kwargs: seen.append(kwargs["language"]))
    window.ocr()
    assert seen == ["spa"]


def test_ocr_with_single_language_still_asks_for_deskew(window, monkeypatch):
    monkeypatch.setattr(ui_tools, "bundled_languages", lambda: ["eng"])
    script_dialog(monkeypatch, dd.OcrLanguagesDialog, languages=["eng"], deskew=True)
    seen = []
    monkeypatch.setattr(window, "external_job", lambda operation, text, **kwargs: seen.append((kwargs["language"], kwargs["deskew"])))
    window.ocr()
    assert seen == [("eng", True)]


def test_ocr_language_dialog_needs_one_language(app):
    dialog = dd.OcrLanguagesDialog(["spa", "eng"])
    for check in dialog.checks.values():
        check.setChecked(False)
    assert dialog.validate() == "Elige al menos un idioma."
    dialog.close()


# ------------------------------------------------------------ export, print

def test_export_submenu_goes_straight_to_the_file(window, monkeypatch):
    monkeypatch.setattr(window, "confirm_unprotected_output", lambda what: True)
    monkeypatch.setattr(QInputDialog, "getItem", lambda *a, **k: pytest.fail("exportar no debe usar getItem"))
    asked = []
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: asked.append(a[2]) or ("", ""))
    window.export_as("export_text")
    assert asked and asked[0].endswith(".txt")


def test_export_submenu_cancel_writes_nothing(window, monkeypatch):
    monkeypatch.setattr(window, "confirm_unprotected_output", lambda what: True)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: ("", ""))
    monkeypatch.setattr(window.engine, "export_docx", lambda *a, **k: pytest.fail("no debe escribir nada"))
    window.export_as("export_docx")


def test_print_pages_render_at_printer_resolution(window, tmp_path):
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(str(tmp_path / "impresion.pdf"))
    printer.setResolution(150)
    window.paint_pages(printer)
    with fitz.open(tmp_path / "impresion.pdf") as printed:
        assert printed.page_count == 2


def test_print_opens_preview_dialog(window, monkeypatch):
    opened = []
    monkeypatch.setattr(window, "show_print_preview", lambda printer: opened.append(printer.resolution()))
    window.print_document()
    assert len(opened) == 1


# ---------------------------------------------------------- Office guard

def test_office_conversion_refuses_pdf_and_keeps_document(window, monkeypatch, tmp_path):
    source = tmp_path / "otro.pdf"
    window.engine.save(source)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(source), "PDF"))
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a[2]))
    monkeypatch.setattr(window, "external_job", lambda *a, **k: pytest.fail("no debe convertir un PDF"))
    monkeypatch.setattr(window, "confirm_discard", lambda: pytest.fail("no debe descartar el documento"))
    before = window.engine.page_count
    window.from_office()
    assert warnings and "no se ha cambiado" in warnings[0]
    assert window.engine.page_count == before == 2 and window.engine.text(0)


# -------------------------------------------------------------- stamps

def test_stamp_gallery_places_on_preset_click(app):
    dialog = dd.StampDialog()
    assert dialog.ok_button.isHidden()
    dialog.list.setCurrentRow(0)
    dialog.list.itemClicked.emit(dialog.list.currentItem())
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.values()["kind"] == "preset"
    dialog.close()


# ------------------------------------------------------------- metadata

def test_metadata_dialog_shows_size_version_and_encryption(window, monkeypatch):
    seen = []
    monkeypatch.setattr(QDialog, "exec", lambda self: seen.append(self) or 0)
    window.metadata()
    dialog = seen[0]
    texts = [label.text() for label in dialog.findChildren(QLabel)]
    assert any(text.endswith(" B") or text.endswith(" KB") for text in texts)
    assert any(text.startswith("PDF") for text in texts)
    assert "No" in texts
    buttons = [b.text() for b in dialog.findChildren(QPushButton)]
    assert {"Guardar", "Cancelar"} <= set(buttons)
