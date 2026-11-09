from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from pdf_editor import lang
import i18n_check

LANGS = ["en", "fr", "de", "pt"]


def test_catalogs_complete_and_placeholders_match():
    source = i18n_check.keys()
    for code in LANGS:
        data = json.loads((lang.LOCALES / f"{code}.json").read_text(encoding="utf-8"))
        missing = [k for k in source if not data.get(k)]
        assert not missing, (code, missing[:5])
        for key, text in data.items():
            assert sorted(re.findall(r"\{\w+\}", key)) == sorted(re.findall(r"\{\w+\}", text)), (code, key)


def test_translate_format_and_fallback():
    try:
        lang.set_language("en")
        assert lang._("Guardar") == "Save"
        assert lang._("texto que no existe {x}", x=1) == "texto que no existe 1"
        assert lang.original("Save") == "Guardar"
    finally:
        os.environ.pop("PDFEDITOR_LANG", None)
        lang.set_language("es")
        os.environ.pop("PDFEDITOR_LANG", None)
    assert lang._("Guardar") == "Guardar"


def test_friendly_error_matches_in_every_language():
    from pdf_editor.i18n import friendly_error
    for code in ["es"] + LANGS:
        lang.set_language(code)
        message, _ = friendly_error(ValueError(lang._("Contraseña incorrecta o requerida.")))
        assert message == lang._("Este PDF necesita la contraseña correcta para abrirse."), code
    os.environ.pop("PDFEDITOR_LANG", None)
    lang.set_language("es")
    os.environ.pop("PDFEDITOR_LANG", None)


@pytest.mark.parametrize("code", ["es"] + LANGS)
def test_window_builds_in_language(code):
    app = QApplication.instance() or QApplication([])
    from pdf_editor.theme import STYLE
    lang.set_language(code)
    try:
        from pdf_editor.app import EditorWindow
        with tempfile.TemporaryDirectory() as folder:
            app.setStyleSheet(STYLE)
            window = EditorWindow(QSettings(str(Path(folder) / "s.ini"), QSettings.Format.IniFormat))
            titles = [a.text() for a in window.menuBar().actions()]
            assert titles[0] == lang._("Archivo")
            if code != "es":
                assert titles[0] != "Archivo"
            window.close()
    finally:
        os.environ.pop("PDFEDITOR_LANG", None)
        lang.set_language("es")
        os.environ.pop("PDFEDITOR_LANG", None)
