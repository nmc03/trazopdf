"""Spanish texts for Qt's own dialogs and friendly messages for common failures."""
from __future__ import annotations

import errno

import pymupdf as fitz

from .lang import _, original
from PySide6.QtCore import QLibraryInfo, QTranslator

QT_CATALOGS = ("qtbase_es", "qt_es")   # español; para otro idioma se usa qtbase_<código>

# Used only when the installed PySide6 has no Spanish Qt catalogs (for example in a frozen build).
FALLBACK = {
    "Yes": "Sí",
    "No": "No",
    "OK": "Aceptar",
    "Cancel": "Cancelar",
    "Save": "Guardar",
    "Save All": "Guardar todo",
    "Discard": "Descartar",
    "Close": "Cerrar",
    "Open": "Abrir",
    "Apply": "Aplicar",
    "Help": "Ayuda",
    "Retry": "Reintentar",
    "Ignore": "Ignorar",
    "Yes to All": "Sí a todo",
    "No to All": "No a todo",
    "Reset": "Restablecer",
    "Restore Defaults": "Restaurar valores predeterminados",
    "Look in:": "Buscar en:",
    "File name:": "Nombre de archivo:",
    "Files of type:": "Tipo de archivo:",
    "Create New Folder": "Crear carpeta nueva",
    "Back": "Atrás",
    "Forward": "Adelante",
    "Parent Directory": "Carpeta superior",
    "Detail View": "Vista de detalles",
    "List View": "Vista de lista",
    "Show hidden files": "Mostrar archivos ocultos",
    "All Files (*)": "Todos los archivos (*)",
    "Choose a directory": "Elegir una carpeta",
    "Select a directory": "Seleccionar una carpeta",
    "Basic Colors": "Colores básicos",
    "Custom Colors": "Colores personalizados",
    "Print": "Imprimir",
    "Print to File ...": "Imprimir en archivo…",
    "Print Preview": "Vista previa de impresión",
}


class FallbackTranslator(QTranslator):
    """Answers the strings in FALLBACK for any context; an empty string means "no translation"."""

    def translate(self, context, source_text, disambiguation=None, n=-1):
        return FALLBACK.get(source_text, "")


def install_translations(app, code="es"):
    """Load Qt's catalogs for `code`, or the built-in Spanish fallback when missing. Returns the installed translators."""
    folder = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    installed = []
    if code == "en":
        return installed
    for name in (QT_CATALOGS if code == "es" else (f"qtbase_{code}", f"qt_{code}")):
        translator = QTranslator(app)
        if translator.load(name, folder):
            app.installTranslator(translator)
            installed.append(translator)
    if not installed and code == "es":
        fallback = FallbackTranslator(app)
        app.installTranslator(fallback)
        installed.append(fallback)
    return installed


DAMAGED_ERRORS = tuple(getattr(fitz, name) for name in ("FileDataError", "EmptyFileError") if hasattr(fitz, name))


def friendly_error(error):
    """Return (message for the user, technical detail). The detail is shown only under "Detalles"."""
    text = str(error)
    lowered = original(text).lower()   # se busca en el texto español de origen, aunque la interfaz esté traducida
    technical = f"{type(error).__name__}: {text}" if text else type(error).__name__
    if isinstance(error, FileNotFoundError):
        message = _("No se encuentra el archivo. Puede que se haya movido o renombrado.")
    elif isinstance(error, PermissionError):
        message = _("No se puede escribir en esa ubicación; elige otra carpeta o archivo.")
    elif isinstance(error, OSError) and getattr(error, "errno", None) == errno.ENOSPC:
        message = _("No hay espacio suficiente en el disco. Libera espacio o elige otra carpeta.")
    elif (DAMAGED_ERRORS and isinstance(error, DAMAGED_ERRORS)) or "broken document" in lowered or "damaged" in lowered \
            or "failed to open stream" in lowered or "cannot open empty stream" in lowered:
        message = _("El archivo está dañado o vacío y no se puede abrir.")
    elif "contraseña" in lowered and ("incorrecta" in lowered or "requerida" in lowered):
        message = _("Este PDF necesita la contraseña correcta para abrirse.")
    elif isinstance(error, NotImplementedError) or "no soportad" in lowered or "no es compatible" in lowered:
        message = _("Esta acción no es compatible con este documento.")
    elif isinstance(error, ValueError) and "invalid literal for int" in lowered:
        message = _("Revisa los números introducidos; usa el formato 1,3-5.")
    elif "no se pudo completar el procesamiento" in lowered:
        message = _("No se pudo completar el procesamiento del documento. Inténtalo de nuevo.")
    elif isinstance(error, ValueError) and text and "\n" not in text and len(text) <= 200:
        message = text
    else:
        message = _("No se pudo completar la operación. Revisa el documento e inténtalo de nuevo.")
    return message, technical
