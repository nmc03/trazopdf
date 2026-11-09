import errno
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QLibraryInfo, QSettings, QTranslator
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from pdf_editor import toast
from pdf_editor.app import EditorWindow, STYLE
from pdf_editor.i18n import FallbackTranslator, friendly_error, install_translations


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    a.setStyleSheet(STYLE)
    return a


@pytest.fixture
def window(app, tmp_path):
    w = EditorWindow(QSettings(str(tmp_path / "m.ini"), QSettings.Format.IniFormat))
    w.engine.new()
    w.engine.add_text(0, (50, 50, 350, 100), "Texto de prueba")
    w.refresh()
    yield w
    w.engine.dirty = False
    w.close()


def banner(window):
    return window.toast_banner


def test_friendly_error_hides_technical_text_from_the_message():
    message, technical = friendly_error(FileNotFoundError(2, "No such file", "C:/x.pdf"))
    assert message.startswith("No se encuentra el archivo")
    assert "FileNotFoundError" in technical

    message, _ = friendly_error(OSError(errno.ENOSPC, "No space left"))
    assert "espacio suficiente" in message

    message, technical = friendly_error(PermissionError(13, "Acceso denegado", r"C:\doc\.pdf-editor-x1.pdf"))
    assert message == "No se puede escribir en esa ubicación; elige otra carpeta o archivo."
    assert "pdf-editor-x1" not in message and "pdf-editor-x1" in technical

    message, _ = friendly_error(RuntimeError("Failed to open stream"))
    assert message == "El archivo está dañado o vacío y no se puede abrir."
    message, _ = friendly_error(RuntimeError("Cannot open empty stream"))
    assert message == "El archivo está dañado o vacío y no se puede abrir."

    message, technical = friendly_error(ValueError("invalid literal for int() with base 10: 'x'"))
    assert "invalid literal" not in message and "1,3-5" in message
    assert "invalid literal" in technical

    message, technical = friendly_error(ValueError("No se pudo completar el procesamiento: Traceback\n  File x"))
    assert "\n" not in message and "Traceback" not in message and "Traceback" in technical

    message, _ = friendly_error(ValueError("Las páginas deben estar dentro del documento."))
    assert message == "Las páginas deben estar dentro del documento."

    message, _ = friendly_error(RuntimeError("boom"))
    assert message.startswith("No se pudo completar la operación")


def test_run_shows_a_banner_instead_of_a_warning_box(window, monkeypatch):
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a))

    def fail():
        raise ValueError("Rango de páginas no válido.")

    assert window.run(fail) is None
    assert warnings == []
    assert banner(window).label.text() == "Rango de páginas no válido."
    assert banner(window).property("kind") == "error"
    assert not banner(window).details_button.isHidden()
    banner(window).dismiss()


def test_info_banner_hides_itself_and_error_stays(window):
    toast.notify(window, "Aviso", timeout=toast.INFO_SECONDS)
    assert banner(window).timer.isActive()
    toast.notify(window, "Fallo", kind="error")
    assert not banner(window).timer.isActive()
    banner(window).dismiss()


def test_banner_action_runs_callback_and_closes(window):
    calls = []
    toast.notify(window, "Hecho", actions=[("Deshacer", lambda: calls.append("undo"))])
    button = banner(window).action_layout.itemAt(0).widget()
    assert button.text() == "Deshacer"
    button.click()
    assert calls == ["undo"]
    assert banner(window).isHidden()


def test_discard_prompt_names_the_file_and_offers_three_choices(window, monkeypatch, tmp_path):
    window.engine.path = str(tmp_path / "informe.pdf")
    seen = {}

    def fake_choose(title, text, buttons, icon=None, detail="", cancel="Cancelar"):
        seen.update(title=title, text=text, buttons=buttons)
        return "No guardar"

    monkeypatch.setattr(window, "choose", fake_choose)
    assert window.confirm_discard() is True
    assert "«informe.pdf»" in seen["text"]
    assert seen["buttons"] == ["Guardar", "No guardar", "Cancelar"]


def test_discard_prompt_cancel_keeps_the_document(window, monkeypatch):
    monkeypatch.setattr(window, "choose", lambda *a, **k: None)
    assert window.confirm_discard() is False
    assert window.engine.dirty


def test_save_reports_the_file_with_open_actions(window, monkeypatch, tmp_path):
    target = tmp_path / "salida.pdf"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), "PDF"))
    assert window.save(True) is True
    assert banner(window).label.text() == "Guardado en salida.pdf"
    labels = [banner(window).action_layout.itemAt(i).widget().text() for i in range(banner(window).action_layout.count())]
    assert labels == ["Abrir carpeta", "Abrir"]
    banner(window).dismiss()


def test_reveal_in_folder_selects_the_file_on_windows(monkeypatch, tmp_path):
    if sys.platform != "win32":
        pytest.skip("explorer /select is Windows only")
    calls = []
    monkeypatch.setattr(toast.subprocess, "Popen", lambda args, **k: calls.append(args))
    target = tmp_path / "con espacio.pdf"
    toast.reveal_in_folder(target)
    assert calls[0][0] == "explorer" and calls[0][1].startswith("/select,")
    assert calls[0][1].endswith("con espacio.pdf")


def test_qt_spanish_catalogs_load_when_installed():
    folder = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    translator = QTranslator()
    if not translator.load("qtbase_es", folder):
        pytest.skip("PySide6 without Spanish Qt catalogs")
    assert translator.translate("QPlatformTheme", "Cancel") == "Cancelar"
    assert translator.translate("QPlatformTheme", "Discard") == "Descartar"


def test_fallback_translator_answers_dialog_texts():
    translator = FallbackTranslator()
    assert translator.translate("QPushButton", "Cancel") == "Cancelar"
    assert translator.translate("QPushButton", "Yes") == "Sí"
    assert translator.translate("QPushButton", "Desconocido") == ""


def test_fallback_is_used_by_qt_translate(app):
    translator = FallbackTranslator(app)
    app.installTranslator(translator)
    try:
        assert QCoreApplication.translate("QPushButton", "Cancel") == "Cancelar"
    finally:
        app.removeTranslator(translator)


def test_install_translations_returns_installed_translators(app):
    installed = install_translations(app)
    try:
        assert installed
    finally:
        for translator in installed:
            app.removeTranslator(translator)
