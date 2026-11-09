"""Complete, irreversible anonymisation of a PDF (pure logic, no Qt, no network).

``anonymize(path_in, path_out, rules, options) -> Report`` works on a copy: the
original is never touched. Steps: detect personal data (the doctools patterns, a few
extra ones and the user's own terms/regular expressions), burn in the redactions with
the engine's own logic, strip every hidden channel (metadata, XMP, attachments,
JavaScript, annotations quoting the text, bookmarks, thumbnails), rewrite the whole file
without incremental history and VERIFY the result by re-reading it. The output only
reaches ``path_out`` when verification passed. Reports never repeat the removed data.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf as fitz

from . import doctools
from .engine import PDFEngine
from .lang import _, N_

# Extra patterns that doctools does not have: key -> (label, regex)
OWN_PATTERNS = {
    "seg_social": (N_("Nº de Seguridad Social"), r"(?<!\d)\d{2}[/ \-]?\d{8,10}[/ \-]?\d{2}(?!\d)"),
    "matricula": (N_("Matrícula"), r"(?<![A-Za-z0-9])\d{4}[ \-]?[BCDFGHJKLMNPRSTVWXYZ]{3}(?![A-Za-z0-9])"),
    "ip": (N_("Dirección IP"), r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])"),
}
REMOVED_INFO, REMOVED_XMP = N_("Metadatos del documento"), N_("Metadatos XMP")
REMOVED_ATT, REMOVED_JS = N_("Archivos adjuntos"), N_("Scripts JavaScript")
REMOVED_TOC, REMOVED_THUMB = N_("Marcadores"), N_("Miniaturas")
REMOVED_ANN = N_("Anotaciones y campos que citan los datos")
LOCATIONS = {"texto": N_("Texto de las páginas"), "anotaciones": N_("Anotaciones y campos"), "metadatos": N_("Metadatos"),
             "marcadores": N_("Marcadores"), "adjuntos": N_("Archivos adjuntos")}
USER_TYPES = {"terminos": N_("Términos del usuario"), "regex": N_("Expresiones del usuario")}


def pattern_choices():
    """[(key, Spanish label)] of every built-in pattern (doctools plus the extra ones)."""
    return doctools.pattern_choices() + [(k, _(v[0])) for k, v in OWN_PATTERNS.items()]


def type_label(key):
    if key in OWN_PATTERNS:
        return _(OWN_PATTERNS[key][0])
    if key in USER_TYPES:
        return _(USER_TYPES[key])
    if key in doctools.PATTERNS:
        return _(doctools.PATTERNS[key][0])
    return key


@dataclass
class Rules:
    patterns: tuple = None          # None = every built-in pattern
    terms: tuple = ()               # literal texts
    regexes: tuple = ()             # user regular expressions
    case_sensitive: bool = False
    whole_word: bool = False
    pages: tuple = None             # zero based page indices, None = all
    exclude: frozenset = frozenset()  # ids (see detect) the user unticked in the preview

    @classmethod
    def coerce(cls, value):
        if isinstance(value, cls):
            return value
        data = dict(value or {})
        for name in ("terms", "regexes"):
            data[name] = tuple(t for t in (data.get(name) or ()) if str(t).strip())
        if data.get("patterns") is not None:
            data["patterns"] = tuple(data["patterns"])
        data["exclude"] = frozenset(data.get("exclude") or ())
        return cls(**data)

    def keys(self):
        return list(self.patterns) if self.patterns is not None else [k for k, _l in pattern_choices()]


@dataclass
class Options:
    fill: tuple = (0, 0, 0)
    remove_all_annotations: bool = False   # also drop annotations that do not quote the data
    keep_bookmarks: bool = False


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class Report:
    ok: bool = False
    output: str = None
    pages: int = 0
    matches_by_type: dict = field(default_factory=dict)   # type key -> occurrences (text + hidden places)
    locations: dict = field(default_factory=dict)         # where they were found
    removed: dict = field(default_factory=dict)           # what was stripped
    checks: list = field(default_factory=list)

    def to_dict(self):
        return {"ok": self.ok, "output": self.output, "pages": self.pages,
                "matches_by_type": dict(self.matches_by_type), "locations": dict(self.locations),
                "removed": dict(self.removed),
                "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in self.checks]}

    def to_json(self):
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def to_text(self):
        lines = [_("INFORME DE ANONIMIZACIÓN"), "",
                 _("Resultado: {result}", result=_("verificado correctamente") if self.ok else _("la verificación ha fallado; no se ha generado el archivo")),
                 _("Páginas: {n}", n=self.pages), "", _("Coincidencias eliminadas por tipo:")]
        lines += [f"  {type_label(k)}: {n}" for k, n in sorted(self.matches_by_type.items())] or ["  " + _("ninguna")]
        lines += ["", _("Dónde se encontraron:")]
        lines += [f"  {_(LOCATIONS.get(k, k))}: {n}" for k, n in self.locations.items()]
        lines += ["", _("Elementos eliminados:")]
        lines += [f"  {_(k)}: {n}" for k, n in self.removed.items()]
        lines += ["", _("Verificación:")]
        lines += [f"  [{_('correcto') if c.ok else _('FALLO')}] {c.name}" + (f" ({c.detail})" if c.detail else "") for c in self.checks]
        lines += ["", _("Este informe no contiene los datos eliminados.")]
        return "\n".join(lines) + "\n"


def write_report(report, path):
    """Save the report as .json or .txt (by extension)."""
    path = Path(path)
    data = report.to_json() if path.suffix.lower() == ".json" else report.to_text()
    PDFEngine._atomic_write(path, data.encode("utf-8"))


# ---------------------------------------------------------------- detection

class _Compiled:
    """Validated rules: raises ValueError (Spanish) for bad input before touching anything."""

    def __init__(self, rules):
        self.rules = rules
        for key in rules.keys():
            if key not in doctools.PATTERNS and key not in OWN_PATTERNS:
                raise ValueError(_("Patrón desconocido: {key}.", key=key))
        self.terms = [(t, doctools._custom_regex(t, False, rules.case_sensitive, rules.whole_word)) for t in rules.terms]
        self.regexes = []
        for rx in rules.regexes:
            self.regexes.append((rx, self._compile_regex(rx)))
        if not rules.keys() and not self.terms and not self.regexes:
            raise ValueError(_("Elige al menos un patrón o escribe un texto a buscar."))
        flags = re.I
        self.own = {k: re.compile(OWN_PATTERNS[k][1], flags) for k in rules.keys() if k in OWN_PATTERNS}

    def _compile_regex(self, source):
        try:
            return doctools._custom_regex(source, True, self.rules.case_sensitive, self.rules.whole_word)
        except ValueError as exc:
            raise ValueError(_("La expresión regular «{rx}» no es válida: {error}", rx=source, error=str(exc))) from None

    def scan(self, text):
        """[(type key, matched string)] in a plain string (hidden places)."""
        found = doctools.find_in_text(text, [k for k in self.rules.keys() if k in doctools.PATTERNS])
        for key, rx in self.own.items():
            found += [(key, m.group(0)) for m in rx.finditer(text or "") if m.group(0).strip()]
        for _t, rx in self.terms:
            found += [("terminos", m.group(0)) for m in rx.finditer(text or "") if m.group(0).strip()]
        for _t, rx in self.regexes:
            found += [("regex", m.group(0)) for m in rx.finditer(text or "") if m.group(0).strip()]
        return found


def _reject_encrypted(path):
    with fitz.open(str(path)) as doc:
        if doc.needs_pass or doc.is_encrypted:
            raise ValueError(_("El documento está cifrado o protegido con contraseña. Quita la protección antes de anonimizarlo."))


def detect(doc, rules):
    """Matches in the page text, in a stable order: dicts of doctools.find_matches plus "id" and "label".

    ``rules.exclude`` is NOT applied here (the preview needs every match); anonymize() applies it.
    """
    rules = Rules.coerce(rules)
    compiled = _Compiled(rules)
    pages = list(rules.pages) if rules.pages is not None else None
    found = []
    builtin = [k for k in rules.keys() if k in doctools.PATTERNS]
    if builtin:
        found += doctools.find_matches(doc, builtin, pages=pages)
    for key in compiled.own:
        found += [dict(m, pattern=key, label=type_label(key))
                  for m in doctools.find_matches(doc, custom=OWN_PATTERNS[key][1], custom_is_regex=True, pages=pages)]
    for term, _rx in compiled.terms:
        found += [dict(m, pattern="terminos", label=type_label("terminos"))
                  for m in doctools.find_matches(doc, custom=term, case_sensitive=rules.case_sensitive,
                                                 whole_word=rules.whole_word, pages=pages)]
    for source, _rx in compiled.regexes:
        found += [dict(m, pattern="regex", label=type_label("regex"))
                  for m in doctools.find_matches(doc, custom=source, custom_is_regex=True, case_sensitive=rules.case_sensitive,
                                                 whole_word=rules.whole_word, pages=pages)]
    kept = []
    for m in found:  # the same characters may match several rules: keep the first
        if any(k["page"] == m["page"] and any(fitz.Rect(a).intersects(b) for a in k["rects"] for b in m["rects"]) for k in kept):
            continue
        kept.append(m)
    kept.sort(key=lambda m: (m["page"], round(m["rect"].y0), m["rect"].x0))
    for i, m in enumerate(kept):
        m["id"] = i
    return kept


def preview(path_in, rules):
    """Matches in a file on disk, for the selection step. Rejects encrypted files."""
    _reject_encrypted(path_in)
    with fitz.open(str(path_in)) as doc:
        return detect(doc, rules)


# ---------------------------------------------- hidden places and cleaning

def _annotation_texts(doc, annot):
    info = annot.info or {}
    texts = [info.get(k, "") for k in ("content", "subject", "title", "name")]
    try:
        texts.append(doc.xref_object(annot.xref))
    except Exception:
        pass
    return [t for t in texts if t]


def _widget_texts(widget):
    return [str(t) for t in (widget.field_value, widget.field_name, getattr(widget, "field_label", None)) if t]


def _attachment_texts(doc):
    texts = []
    try:
        names = doc.embfile_names()
    except Exception:
        return texts
    for name in names:
        texts.append(name)
        try:
            data = doc.embfile_get(name)
        except Exception:
            continue
        texts.append(data.decode("utf-8", "ignore"))
        texts.append(data.decode("latin-1", "ignore"))
    return texts


def _hidden_sources(doc):
    """[(location key, text)] for every place outside the page content that may quote data."""
    sources = [("metadatos", v) for k, v in (doc.metadata or {}).items() if k not in ("format", "encryption") and v]
    sources += [("metadatos", doc.get_xml_metadata() or "")]
    for value, _x in _info_entries(doc):
        sources.append(("metadatos", value))
    sources += [("marcadores", item[1]) for item in doc.get_toc()]
    sources += [("adjuntos", t) for t in _attachment_texts(doc)]
    for page in doc:
        for annot in page.annots() or ():
            sources += [("anotaciones", t) for t in _annotation_texts(doc, annot)]
        for widget in page.widgets() or ():
            sources += [("anotaciones", t) for t in _widget_texts(widget)]
    return sources


def _info_entries(doc):
    """Values of every key in the Info dictionary (including custom keys): [(value, xref)]."""
    kind, value = doc.xref_get_key(-1, "Info")
    if kind != "xref":
        return []
    xref = int(value.split()[0])
    out = []
    for key in doc.xref_get_keys(xref):
        out.append((doc.xref_get_key(xref, key)[1], xref))
    return out


def _clear_info(doc):
    kind, value = doc.xref_get_key(-1, "Info")
    if kind != "xref":
        return 0
    xref = int(value.split()[0])
    keys = doc.xref_get_keys(xref)
    for key in keys:
        doc.xref_set_key(xref, key, "null")
    return len(keys)


def _has_javascript(doc):
    return doctools._has_javascript(doc)


def _cites(texts, secrets):
    blob = " ".join(texts).casefold()
    squeezed = re.sub(r"\s+", "", blob)
    return any(s.casefold() in blob or re.sub(r"\s+", "", s.casefold()) in squeezed for s in secrets if s.strip())


def _deep_sanitize(engine, secrets, options):
    """engine.sanitize() plus what it leaves behind. Returns counts of what was removed."""
    doc = engine.doc
    removed = {}
    removed[REMOVED_INFO] = _clear_info(doc) + len([1 for k, v in (doc.metadata or {}).items() if k not in ("format", "encryption") and v])
    removed[REMOVED_XMP] = 1 if (doc.get_xml_metadata() or "").strip() else 0
    removed[REMOVED_ATT] = doc.embfile_count()
    removed[REMOVED_JS] = 1 if _has_javascript(doc) else 0
    removed[REMOVED_TOC] = len(doc.get_toc())
    removed[REMOVED_THUMB] = sum(1 for p in doc if doc.xref_get_key(p.xref, "Thumb")[0] != "null")
    engine.sanitize()
    if not options.keep_bookmarks and doc.get_toc():
        doc.set_toc([])
    elif options.keep_bookmarks:
        removed[REMOVED_TOC] = 0
    annots = 0
    for page in doc:
        for widget in list(page.widgets() or ()):
            if _cites(_widget_texts(widget), secrets):
                page.delete_widget(widget)
                annots += 1
        for annot in list(page.annots() or ()):
            if options.remove_all_annotations or _cites(_annotation_texts(doc, annot), secrets):
                page.delete_annot(annot)
                annots += 1
    removed[REMOVED_ANN] = annots
    return removed


# ----------------------------------------------------------- verification

def _variants(secret):
    """Byte forms a secret can take in a PDF: plain, UTF-16BE, and the hex strings text operators use. Lowercase."""
    forms = set()
    for text in {secret, secret.lower(), secret.upper(), secret.casefold()}:
        for raw in (text.encode("utf-8"), text.encode("latin-1", "ignore"), text.encode("utf-16-be")):
            if raw:
                forms.add(raw.lower())
                forms.add(raw.hex().encode())          # <48656c6c6f> in content streams
    return forms


_JOIN = re.compile(rb"[>)]\s*-?[\d.]*\s*[<(]")        # kerning gaps inside a TJ array


def _all_text_places(doc):
    for page in doc:
        yield "texto", page.get_text()
    for place, text in _hidden_sources(doc):
        yield place, text


def verify_file(path, secrets):
    """Re-read ``path`` and look for any of ``secrets`` everywhere. Returns a list of Check (no secret in them)."""
    secrets = [s for s in dict.fromkeys(secrets) if s and s.strip()]
    checks = []
    data = Path(path).read_bytes()
    with fitz.open(str(path)) as doc:
        checks.append(Check(_("El archivo no está cifrado"), not (doc.needs_pass or doc.is_encrypted)))
        by_place = {}
        for place, text in _all_text_places(doc):
            if _cites([text], secrets):
                by_place[place] = by_place.get(place, 0) + 1
        for place, label in (("texto", N_("Texto de todas las páginas (incluidas capas OCR)")),
                             ("anotaciones", N_("Anotaciones y campos de formulario")),
                             ("metadatos", N_("Metadatos Info y XMP")),
                             ("marcadores", N_("Marcadores")),
                             ("adjuntos", N_("Archivos adjuntos"))):
            checks.append(Check(_(label), place not in by_place))
        checks.append(Check(_("Sin adjuntos, scripts ni metadatos residuales"),
                            doc.embfile_count() == 0 and not _has_javascript(doc) and not (doc.get_xml_metadata() or "").strip()
                            and not _info_entries_nonnull(doc)))
        # Raw bytes and every object body / decompressed stream.
        variants = set()
        for s in secrets:
            variants |= _variants(s)
        leaks = 0
        if any(v in data.lower() or v in _JOIN.sub(b"", data.lower()) for v in variants):
            leaks += 1
        compact = [re.sub(rb"\s+", b"", v) for v in variants]
        for xref in range(1, doc.xref_length()):
            try:
                chunks = [doc.xref_object(xref, compressed=False).encode("latin-1", "ignore")]
                if doc.xref_is_stream(xref):
                    chunks.append(doc.xref_stream(xref) or b"")
            except Exception:
                continue
            for chunk in chunks:
                low = chunk.lower()
                joined = _JOIN.sub(b"", low)
                if any(v in low or v in joined for v in variants) or any(c in re.sub(rb"\s+", b"", joined) for c in compact if len(c) >= 4):
                    leaks += 1
        checks.append(Check(_("Ningún byte del archivo, descomprimido, contiene los datos"), leaks == 0,
                            _("{n} objeto(s) con restos", n=leaks) if leaks else ""))
        history = data.count(b"%%EOF")
        checks.append(Check(_("Archivo reescrito completo, sin historial incremental"), history <= 1 and data.count(b"startxref") <= 1))
        checks.append(Check(_("Sin objetos huérfanos"), _no_orphans(doc)))
    return checks


def _info_entries_nonnull(doc):
    return [v for v, _x in _info_entries(doc) if v not in ("null", "")]


def _no_orphans(doc):
    try:
        compact = fitz.open("pdf", doc.tobytes(garbage=4, clean=True))
    except Exception:
        return False
    with compact:
        return compact.xref_length() >= doc.xref_length()


# ------------------------------------------------------------------- main

def anonymize(path_in, path_out, rules, options=None):
    """Anonymise ``path_in`` into the new file ``path_out`` and verify it. Returns a Report.

    Raises ValueError (Spanish message) for encrypted files, bad rules or equal paths.
    When verification fails the output file is NOT created (``report.ok`` is False).
    """
    rules = Rules.coerce(rules)
    options = options or Options()
    path_in, path_out = Path(path_in), Path(path_out)
    if path_in.resolve() == path_out.resolve():
        raise ValueError(_("El archivo de salida debe ser distinto del original: el original no se modifica."))
    _compiled = _Compiled(rules)  # validate before doing any work
    _reject_encrypted(path_in)
    engine = PDFEngine()
    tmp = path_out.resolve().parent / (".anonimizar-" + uuid.uuid4().hex + ".pdf")
    try:
        engine.open(path_in)
        doc = engine.doc
        report = Report(pages=len(doc))
        matches = [m for m in detect(doc, rules) if m["id"] not in rules.exclude]
        excluded = {m["text"].casefold() for m in detect(doc, rules) if m["id"] in rules.exclude}
        secrets, by_type, locations = [], {}, {}
        for m in matches:
            secrets.append(m["text"])
            by_type[m["pattern"]] = by_type.get(m["pattern"], 0) + 1
        if matches:
            locations["texto"] = len(matches)
        for place, text in _hidden_sources(doc):
            for key, found in _compiled.scan(text):
                if found.casefold() in excluded:
                    continue
                secrets.append(found)
                by_type[key] = by_type.get(key, 0) + 1
                locations[place] = locations.get(place, 0) + 1
        secrets += [t for t, _rx in _compiled.terms]
        if matches:
            doctools.add_redactions(doc, matches, fill=options.fill)
        if matches or any(a.type[0] == fitz.PDF_ANNOT_REDACT for p in doc for a in (p.annots() or ())):
            engine.apply_redactions()
        report.removed = _deep_sanitize(engine, secrets, options)
        report.matches_by_type, report.locations = by_type, locations
        engine.save(tmp)
        report.checks = verify_file(tmp, secrets)
        report.ok = all(c.ok for c in report.checks)
        if report.ok:
            os.replace(tmp, path_out)
            report.output = str(path_out.resolve())
        return report
    finally:
        engine.close()
        if tmp.exists():
            tmp.unlink()
