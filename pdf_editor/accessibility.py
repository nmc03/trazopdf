"""Accessibility checker: per-item report on title, language, tags, scanned pages, figure alt text and bookmarks."""
from pathlib import Path

import pymupdf as fitz

from .lang import _, N_

OK, WARNING, ERROR = "ok", "warning", "error"
LONG_DOCUMENT_PAGES = 20
LANGUAGES = (("es", N_("Español")), ("en", N_("Inglés")), ("fr", N_("Francés")), ("de", N_("Alemán")), ("pt", N_("Portugués")), ("it", N_("Italiano")), ("ca", N_("Catalán")))
STATUS_TEXT = {OK: N_("Correcto"), WARNING: N_("Aviso"), ERROR: N_("Error")}


def language(doc):
    kind, value = doc.xref_get_key(doc.pdf_catalog(), "Lang")
    return value.strip("()") if kind == "string" else ""


def has_structure(doc):
    return doc.xref_get_key(doc.pdf_catalog(), "StructTreeRoot")[0] != "null"


def is_tagged(doc):
    return has_structure(doc) and "true" in doc.xref_get_key(doc.pdf_catalog(), "MarkInfo/Marked")[1].lower()


def pages_without_text(doc):
    return [i for i, page in enumerate(doc) if not page.get_text("text").strip() and (page.get_images() or page.get_drawings())]


def figures_without_alt(doc):
    missing = 0
    for xref in range(1, doc.xref_length()):
        try:
            if doc.xref_get_key(xref, "S")[1] == "/Figure" and doc.xref_get_key(xref, "Alt")[0] == "null":
                missing += 1
        except (RuntimeError, ValueError):
            continue
    return missing


def _item(key, label, status, detail, fix=None):
    return {"key": key, "label": label, "status": status, "detail": detail, "fix": fix}


def check(doc):
    """List of results: key, label, status, detail and fix (None, 'title' or 'language')."""
    results = []
    title = (doc.metadata or {}).get("title", "").strip()
    results.append(_item("title", _("Título del documento"), OK if title else ERROR,
                         _("«{title}»", title=title) if title else _("El documento no tiene título."), None if title else "title"))
    lang = language(doc)
    results.append(_item("language", _("Idioma del documento"), OK if lang else ERROR,
                         _("Idioma: {lang}", lang=lang) if lang else _("No se ha indicado el idioma."), None if lang else "language"))
    tagged = is_tagged(doc)
    results.append(_item("tagged", _("PDF etiquetado"), OK if tagged else WARNING,
                         _("El documento tiene estructura etiquetada.") if tagged else _("Sin etiquetas: los lectores de pantalla no podrán seguir el orden de lectura.")))
    blank = pages_without_text(doc)
    if blank:
        shown = ", ".join(str(i + 1) for i in blank[:10]) + ("…" if len(blank) > 10 else "")
        results.append(_item("text", _("Páginas con texto"), WARNING, _("{count} página(s) sin texto (posible escaneo sin OCR): {shown}.", count=len(blank), shown=shown)))
    else:
        results.append(_item("text", _("Páginas con texto"), OK, _("Todas las páginas con contenido tienen texto.")))
    if has_structure(doc):
        missing = figures_without_alt(doc)
        results.append(_item("alt", _("Texto alternativo de imágenes"), WARNING if missing else OK,
                             _("{count} imagen(es) sin texto alternativo.", count=missing) if missing else _("Las imágenes etiquetadas tienen texto alternativo.")))
    else:
        results.append(_item("alt", _("Texto alternativo de imágenes"), OK, _("Sin estructura etiquetada: no se puede comprobar.")))
    if doc.page_count > LONG_DOCUMENT_PAGES:
        has = bool(doc.get_toc())
        results.append(_item("bookmarks", _("Marcadores"), OK if has else WARNING,
                             _("El documento tiene marcadores.") if has else _("Documento de {count} páginas sin marcadores.", count=doc.page_count)))
    else:
        results.append(_item("bookmarks", _("Marcadores"), OK, _("No se necesitan en documentos cortos.")))
    return results


def error_count(results):
    return sum(1 for r in results if r["status"] == ERROR)


def title_from_name(path):
    return Path(path).stem.replace("_", " ").replace("-", " ").strip() if path else ""


def fix_title(engine, title=None):
    title = (title or title_from_name(engine.path) or _("Documento sin título")).strip()
    values = dict(engine.metadata())
    values["title"] = title
    engine.set_metadata(values)


def fix_language(engine, code):
    # The engine has no language setter; reuse its mutation context so undo still works.
    with engine._mutation():
        engine.doc.xref_set_key(engine.doc.pdf_catalog(), "Lang", fitz.get_pdf_str(code))


def report_text(results, name=""):
    lines = [_("Informe de accesibilidad: {name}", name=name) if name else _("Informe de accesibilidad"), ""]
    for r in results:
        lines.append(_("[{status}] {label}: {detail}", status=_(STATUS_TEXT[r["status"]]), label=_(r["label"]), detail=_(r["detail"])))
    warnings = sum(1 for r in results if r["status"] == WARNING)
    lines += ["", _("Errores: {errors}. Avisos: {warnings}.", errors=error_count(results), warnings=warnings)]
    return "\n".join(lines)
