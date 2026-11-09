import pymupdf as fitz
import pytest
from PySide6.QtWidgets import QApplication, QLineEdit

from pdf_editor.engine import PDFEngine
from pdf_editor.ui_security import MAX_PASSWORD_ATTEMPTS, PasswordDialog


@pytest.fixture
def window(tmp_path):
    from PySide6.QtCore import QSettings
    from pdf_editor.app import EditorWindow
    QApplication.instance() or QApplication([])
    w = EditorWindow(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
    w.engine.new()
    yield w
    w.engine.dirty = False
    w.close()


@pytest.fixture
def protected(tmp_path):
    e = PDFEngine()
    e.doc[0].insert_text((72, 100), "Protegido", fontsize=12)
    e.protect(tmp_path / "p.pdf", "abrir", "duena")
    e.close()
    return str(tmp_path / "p.pdf")


def make(check=None):
    QApplication.instance() or QApplication([])
    return PasswordDialog(None, "Documento protegido", "Contraseña:", check)


def test_wrong_password_shows_inline_error_and_stays_open():
    d = make(lambda text: text == "bien")
    d.show()
    d.edit.setText("mal")
    d.submit()
    assert d.isVisible() and d.password is None
    assert "incorrecta" in d.error.text() and "4 intentos" in d.error.text()
    d.edit.setText("bien")
    d.submit()
    assert d.password == "bien" and not d.isVisible()


def test_attempt_limit_blocks_further_tries_with_message():
    d = make(lambda text: text == "bien")
    for _ in range(MAX_PASSWORD_ATTEMPTS):
        d.edit.setText("mal")
        d.submit()
    assert d.exhausted and "Demasiados intentos" in d.error.text()
    d.edit.setText("bien")
    d.submit()
    assert d.password is None


def test_show_toggle_reveals_text():
    d = make()
    assert d.edit.echoMode() == QLineEdit.EchoMode.Password
    d.show_box.setChecked(True)
    assert d.edit.echoMode() == QLineEdit.EchoMode.Normal


def test_open_with_password_uses_inline_dialog(window, monkeypatch, protected):
    seen = []

    def fake_exec(dialog):
        for text in ("mala", "abrir"):
            dialog.edit.setText(text)
            dialog.submit()
            seen.append(dialog.error.text())
            if dialog.password is not None:
                return 1
        return 0

    monkeypatch.setattr(PasswordDialog, "exec", fake_exec)
    engine = PDFEngine()
    assert window.open_with_password(engine, protected) is True
    assert seen[0].startswith("Contraseña incorrecta") and engine.is_protected
    engine.close()


def test_open_with_password_cancel_returns_false(window, monkeypatch, protected):
    monkeypatch.setattr(PasswordDialog, "exec", lambda d: 0)
    engine = PDFEngine()
    assert window.open_with_password(engine, protected) is False
    engine.close()


def test_no_input_dialog_left_in_security_module():
    from pathlib import Path
    import pdf_editor.ui_security as module
    assert "QInputDialog" not in Path(module.__file__).read_text(encoding="utf-8")
