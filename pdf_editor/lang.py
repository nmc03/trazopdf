"""Interfaz multilingüe. El español es el idioma de origen: las claves de los catálogos son los textos en español.

Uso en el código:   _("Guardar")      _("Página {n} de {total}", n=3, total=10)
Los catálogos están en assets/locales/<código>.json ({"texto en español": "traducción"}).
El idioma se elige en Ayuda > Idioma, con la variable PDFEDITOR_LANG o, por defecto, según el sistema.
"""
from __future__ import annotations

import json
import locale
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCALES = ROOT / "assets" / "locales"
SOURCE = "es"
NAMES = {"es": "Español", "en": "English", "fr": "Français", "de": "Deutsch", "pt": "Português"}
FALLBACK = "en"          # idioma del sistema no soportado

_catalog: dict[str, str] = {}
_current = SOURCE
_reverse = None


def available():
    """Códigos con catálogo (más el español de origen), en el orden de NAMES."""
    found = {code for code in NAMES if code == SOURCE or (LOCALES / f"{code}.json").is_file()}
    return [code for code in NAMES if code in found]


def system_language():
    for getter in (lambda: locale.getlocale()[0], lambda: os.environ.get("LANG", ""), lambda: os.environ.get("LC_ALL", "")):
        try:
            value = (getter() or "").lower()
        except Exception:
            value = ""
        code = value.replace("-", "_").split("_")[0]
        if code in NAMES and code in available():
            return code
    if os.name == "nt":
        try:
            import ctypes
            buffer = ctypes.create_unicode_buffer(85)
            ctypes.windll.kernel32.GetUserDefaultLocaleName(buffer, 85)
            code = buffer.value.lower().replace("-", "_").split("_")[0]
            if code in NAMES and code in available():
                return code
        except Exception:
            pass
    return FALLBACK if FALLBACK in available() else SOURCE


def resolve(choice):
    """`choice` es un código, "system" o vacío. Devuelve un código soportado."""
    choice = (choice or "system").lower()
    if choice == "system":
        return system_language()
    return choice if choice in available() else system_language()


def set_language(choice="system"):
    """Carga el catálogo del idioma elegido y lo deja activo. Devuelve el código resuelto."""
    global _catalog, _current
    code = resolve(os.environ.get("PDFEDITOR_LANG") or choice)
    _current = code
    _catalog = {}
    if code != SOURCE:
        try:
            _catalog = json.loads((LOCALES / f"{code}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _catalog = {}
    os.environ["PDFEDITOR_LANG"] = code      # los procesos de trabajo heredan el idioma
    return code


def original(text):
    """Devuelve el texto español de origen de una traducción exacta (o el mismo texto si no se conoce)."""
    global _reverse
    if _reverse is None or _reverse[0] is not _catalog:
        _reverse = (_catalog, {v: k for k, v in _catalog.items() if v})
    return _reverse[1].get(text, text)


def current():
    return _current


def _(text, **values):
    """Traduce `text` (en español) al idioma activo; `values` rellena los {marcadores}."""
    out = _catalog.get(text, text)
    if values:
        try:
            return out.format(**values)
        except (KeyError, IndexError, ValueError):
            return text.format(**values)
    return out


def ntext(count, one, many, **values):
    """Plural simple: `one` si count == 1, si no `many`. Ambos son claves del catálogo."""
    return _(one if count == 1 else many, n=count, **values)


def N_(text):
    """Marca un texto para extraerlo sin traducirlo aún (constantes de módulo). Se traduce al mostrarlo con _(variable)."""
    return text
