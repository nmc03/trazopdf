"""Document-level tools (headers, Bates, redaction search, optimize, ...).

Pure functions over a ``fitz.Document``; no Qt. Pages are zero based, rects are
unrotated PDF points (the same convention as PDFEngine). Colours are RGB tuples
with components in 0..1. Invalid input raises ValueError with a Spanish message.
"""
from __future__ import annotations

import datetime as _dt
import difflib
import io
import math
import re
from pathlib import Path

import pymupdf as fitz

from .lang import _, N_

# ---------------------------------------------------------------- helpers

PAGE_SIZES = {
    "A4": (595.276, 841.89),
    "Carta": (612.0, 792.0),
    "A3": (841.89, 1190.55),
    "A5": (419.53, 595.276),
}

TOKENS = ("{page}", "{pages}", "{date}", "{filename}")


def _require(doc):
    if doc is None or getattr(doc, "is_closed", False):
        raise ValueError(_("No hay un documento abierto."))
    return doc


def _color(color):
    try:
        c = tuple(float(v) for v in color)
    except (TypeError, ValueError):
        raise ValueError(_("El color no es válido.")) from None
    if len(c) != 3 or not all(0.0 <= v <= 1.0 for v in c):
        raise ValueError(_("El color debe tener tres componentes entre 0 y 1."))
    return c


def parse_page_range(spec, count):
    """'1-3, 5, 8-' -> sorted zero based indices. Empty spec means every page."""
    if count < 1:
        raise ValueError(_("El documento no tiene páginas."))
    spec = (spec or "").strip()
    if not spec:
        return list(range(count))
    result = set()
    for part in re.split(r"[,;]", spec):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r"(\d*)\s*-\s*(\d*)", part)
        if m and (m.group(1) or m.group(2)):
            a = int(m.group(1) or 1)
            b = int(m.group(2) or count)
        elif part.isdigit():
            a = b = int(part)
        else:
            raise ValueError(_("Rango de páginas no válido: «{part}».", part=part))
        if a < 1 or b > count or a > b:
            raise ValueError(_("El rango «{part}» está fuera del documento (1-{count}).", part=part, count=count))
        result.update(range(a - 1, b))
    if not result:
        raise ValueError(_("Selecciona al menos una página."))
    return sorted(result)


def _pages(doc, pages):
    n = len(_require(doc))
    if pages is None:
        return list(range(n))
    if isinstance(pages, str):
        return parse_page_range(pages, n)
    values = sorted(set(pages))
    if not values:
        raise ValueError(_("Selecciona al menos una página."))
    for p in values:
        if not isinstance(p, int) or not 0 <= p < n:
            raise ValueError(_("Número de página fuera del documento."))
    return values


def _date_text(date):
    if date is None:
        date = _dt.date.today()
    if isinstance(date, (_dt.date, _dt.datetime)):
        return date.strftime("%d/%m/%Y")
    return str(date)


def expand_tokens(text, page, pages, filename="", date=None):
    """Replace {page}, {pages}, {date}, {filename}. ``page`` is zero based."""
    return (str(text or "").replace("{page}", str(page + 1)).replace("{pages}", str(pages))
            .replace("{date}", _date_text(date)).replace("{filename}", str(filename or "")))


def _place_text(page, text, anchor, baseline, margin_side, fontsize, color, fontname="helv"):
    """Draw ``text`` on the visual page at a visual baseline, honouring page rotation."""
    if not text:
        return False
    width = fitz.get_text_length(text, fontname=fontname, fontsize=fontsize)
    visual = page.rect
    if anchor == "left":
        x = margin_side
    elif anchor == "right":
        x = visual.width - margin_side - width
    else:
        x = (visual.width - width) / 2
    point = fitz.Point(x, baseline) * page.derotation_matrix
    page.insert_text(point, text, fontsize=fontsize, fontname=fontname, color=color, rotate=page.rotation)
    return True


def _check_size(value, name, low=0.0, high=1000.0):
    if not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(_("{name} no es válido.", name=name))
    return float(value)


# ------------------------------------------------- 1. headers and footers

def add_header_footer(doc, *, header=("", "", ""), footer=("", "", ""), fontsize=10, color=(0, 0, 0),
                      margin_top=36, margin_bottom=36, margin_side=36, pages=None, filename="", date=None):
    """Stamp left/center/right header and footer text. Returns the number of pages touched.

    ``header``/``footer`` are (left, center, right) strings that may use the tokens
    {page}, {pages}, {date} and {filename}. ``pages`` is a list of zero based indices,
    a range string such as "1-3,5", or None for every page.
    """
    _require(doc)
    header, footer = tuple(header or ("", "", "")), tuple(footer or ("", "", ""))
    if len(header) != 3 or len(footer) != 3:
        raise ValueError(_("El encabezado y el pie deben tener tres textos (izquierda, centro, derecha)."))
    if not any(header) and not any(footer):
        raise ValueError(_("Escribe al menos un texto de encabezado o de pie."))
    fontsize = _check_size(fontsize, _("El tamaño de letra"), 4, 144)
    color = _color(color)
    margin_top = _check_size(margin_top, _("El margen superior"), 0, 400)
    margin_bottom = _check_size(margin_bottom, _("El margen inferior"), 0, 400)
    margin_side = _check_size(margin_side, _("El margen lateral"), 0, 400)
    indexes = _pages(doc, pages)
    total = len(doc)
    for index in indexes:
        page = doc[index]
        if margin_top + margin_bottom + fontsize * 2 > page.rect.height:
            raise ValueError(_("Los márgenes son demasiado grandes para la página."))
        for texts, baseline in ((header, margin_top + fontsize), (footer, page.rect.height - margin_bottom)):
            for anchor, text in zip(("left", "center", "right"), texts):
                _place_text(page, expand_tokens(text, index, total, filename, date), anchor, baseline,
                            margin_side, fontsize, color)
    return len(indexes)


# ------------------------------------------------------- 2. Bates numbering

BATES_POSITIONS = ("top-left", "top-center", "top-right", "bottom-left", "bottom-center", "bottom-right")


def bates_label(number, prefix="", suffix="", digits=6):
    return f"{prefix}{int(number):0{int(digits)}d}{suffix}"


def add_bates(doc, *, prefix="", suffix="", start=1, digits=6, position="bottom-right", fontsize=10,
              color=(0, 0, 0), margin=36, pages=None):
    """Stamp consecutive Bates numbers. Returns the last number used."""
    _require(doc)
    if position not in BATES_POSITIONS:
        raise ValueError(_("Posición de la numeración Bates no válida."))
    if not isinstance(start, int) or start < 0:
        raise ValueError(_("El número inicial debe ser un entero igual o mayor que 0."))
    if not isinstance(digits, int) or not 1 <= digits <= 12:
        raise ValueError(_("El número de dígitos debe estar entre 1 y 12."))
    fontsize = _check_size(fontsize, _("El tamaño de letra"), 4, 144)
    margin = _check_size(margin, _("El margen"), 0, 400)
    color = _color(color)
    indexes = _pages(doc, pages)
    vertical, anchor = position.split("-")
    number = start
    last = start - 1
    for index in indexes:
        page = doc[index]
        label = bates_label(number, prefix, suffix, digits)
        baseline = margin + fontsize if vertical == "top" else page.rect.height - margin
        _place_text(page, label, anchor, baseline, margin, fontsize, color)
        last = number
        number += 1
    return last


# ----------------------------------------------- 3. search and redact

def _luhn(digits):
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total += d
    return total % 10 == 0


def _dni_letter(number):
    return "TRWAGMYFPDXBNJZSQVHLCKE"[int(number) % 23]


def _ok_text(text):
    return text


def _check_card(text):
    digits = re.sub(r"\D", "", text)
    return text if 13 <= len(digits) <= 19 and _luhn(digits) else None


def _check_iban(text):
    # The pattern may swallow trailing words; shrink until the checksum holds.
    candidate = text
    while True:
        compact = candidate.replace(" ", "").upper()
        if 15 <= len(compact) <= 34:
            rearranged = compact[4:] + compact[:4]
            numeric = "".join(str(int(c, 36)) for c in rearranged)
            if int(numeric) % 97 == 1:
                return candidate
        if " " not in candidate.strip():
            return None
        candidate = candidate.rstrip().rsplit(" ", 1)[0]


def _check_dni_nie(text):
    t = re.sub(r"[\s.\-]", "", text).upper()
    if t[0] in "XYZ":
        number, letter = str("XYZ".index(t[0])) + t[1:-1], t[-1]
    else:
        number, letter = t[:-1], t[-1]
    return text if _dni_letter(number) == letter else None


def _check_nif_cif(text):
    t = re.sub(r"[\s\-]", "", text).upper()
    if t[0] in "KLM":
        return text if _dni_letter(t[1:-1]) == t[-1] else None
    digits = t[1:8]
    even = sum(int(digits[i]) for i in (1, 3, 5))
    odd = 0
    for i in (0, 2, 4, 6):
        d = int(digits[i]) * 2
        odd += d // 10 + d % 10
    control = (10 - (even + odd) % 10) % 10
    letter = "JABCDEFGHI"[control]
    last = t[-1]
    if t[0] in "PQRSNW" or digits[:0]:
        return text if last == letter else None
    if t[0] in "ABEH":
        return text if last == str(control) else None
    return text if last in (str(control), letter) else None


def _check_phone_intl(text):
    digits = re.sub(r"\D", "", text)
    return text if 8 <= len(digits) <= 15 else None


def _valid_date(day, month, year):
    try:
        _dt.date(year if year > 99 else 2000 + year, month, day)
        return True
    except ValueError:
        return False


def _check_date(text):
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        return text if _valid_date(int(m.group(3)), int(m.group(2)), int(m.group(1))) else None
    m = re.fullmatch(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})", text)
    if m:
        d, mo, y = (int(g) for g in m.groups())
        if len(m.group(3)) == 3:
            return None
        return text if _valid_date(d, mo, y) else None
    return text  # long Spanish form: months are fixed by the pattern


_MONTHS = "enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre"

# key -> (label, regex, checker)
PATTERNS = {
    "email": (N_("Correo electrónico"), r"(?<![\w.%+\-])[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}", _ok_text),
    "iban": ("IBAN", r"(?<![A-Za-z0-9])[A-Za-z]{2}\d{2}(?: ?[A-Za-z0-9]{4}){2,7}(?: ?[A-Za-z0-9]{1,4})?(?![A-Za-z0-9])", _check_iban),
    "tarjeta": (N_("Tarjeta bancaria"), r"(?<![\d\-])\d{4}(?:[ \-]?\d{4}){2}[ \-]?\d{1,7}(?![\d\-])|(?<![\d\-])\d{4}[ \-]?\d{6}[ \-]?\d{5}(?![\d\-])", _check_card),
    "dni_nie": ("DNI / NIE", r"(?<![A-Za-z0-9])(?:(?:\d{8}|\d{2}[. ]\d{3}[. ]\d{3})[ \-]?[A-Za-z]|[XYZxyz][ \-]?\d{7}[ \-]?[A-Za-z])(?![A-Za-z0-9])", _check_dni_nie),
    "nif_cif": (N_("NIF / CIF"), r"(?<![A-Za-z0-9])(?:[ABCDEFGHJNPQRSUVWabcdefghjnpqrsuvw][ \-]?\d{7}[ \-]?[0-9A-Ja-j]|[KLMklm][ \-]?\d{7}[ \-]?[A-Za-z])(?![A-Za-z0-9])", _check_nif_cif),
    "telefono_es": (N_("Teléfono (España)"), r"(?<![\w+])(?:(?:\(?\+34\)?|0034)[ .\-]?)?[6789]\d{2}[ .\-]?\d{3}[ .\-]?\d{3}(?![\d\-])", _ok_text),
    "telefono_intl": (N_("Teléfono (internacional)"), r"(?<![\w+])\+(?!34\b)\d{1,3}(?:[ .\-]?\(?\d{1,4}\)?){2,5}(?!\d)", _check_phone_intl),
    "fecha": ("Fecha", r"(?<![\d/.\-])(?:\d{4}-\d{2}-\d{2}|\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}|\d{1,2} de (?:" + _MONTHS + r") de \d{4})(?![\d])", _check_date),
}
_COMPILED = {k: re.compile(v[1], re.I) for k, v in PATTERNS.items()}


def pattern_choices():
    """[(key, Spanish label)] for UIs."""
    return [(k, _(v[0])) for k, v in PATTERNS.items()]


def find_in_text(text, patterns):
    """Matches of the named patterns inside a plain string: [(key, matched text)]. Same validation as find_matches."""
    found = []
    for key in patterns:
        if key not in PATTERNS:
            raise ValueError(_("Patrón desconocido: {key}.", key=key))
        for m in _COMPILED[key].finditer(text or ""):
            if m.group(0).strip():
                matched = PATTERNS[key][2](m.group(0))
                if matched is not None:
                    found.append((key, matched))
    return found


def _page_chars(page):
    """Return (text, boxes): text of the page with '\\n' between lines and a bbox per character."""
    chars, boxes = [], []
    raw = page.get_text("rawdict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                for ch in span["chars"]:
                    chars.append(ch["c"])
                    boxes.append(fitz.Rect(ch["bbox"]))
            chars.append("\n")
            boxes.append(None)
    return "".join(chars), boxes


def _span_rects(boxes, start, end):
    """Union of the character boxes of [start, end) per text line."""
    rects, current = [], None
    for i in range(start, end):
        b = boxes[i]
        if b is None:
            if current is not None:
                rects.append(current)
                current = None
            continue
        if b.is_empty and b.width == 0:
            continue
        current = fitz.Rect(b) if current is None else current | b
    if current is not None:
        rects.append(current)
    return rects


def _custom_regex(custom, is_regex, case_sensitive, whole_word):
    if not custom:
        return None
    flags = 0 if case_sensitive else re.I
    if is_regex:
        source = custom
    else:
        source = re.escape(custom)
    if whole_word:
        source = r"(?<!\w)(?:" + source + r")(?!\w)"
    try:
        return re.compile(source, flags)
    except re.error as exc:
        raise ValueError(_("La expresión regular no es válida: {error}", error=exc)) from None


def find_matches(doc, patterns=(), *, custom="", custom_is_regex=False, case_sensitive=False,
                 whole_word=False, pages=None):
    """Find sensitive data. Returns a list of dicts ordered by page and position:

    {"page": int, "rect": fitz.Rect (first line), "rects": [fitz.Rect, ...] (one per line),
     "text": str, "pattern": key or "custom", "label": Spanish name}.
    """
    _require(doc)
    patterns = list(patterns or ())
    for key in patterns:
        if key not in PATTERNS:
            raise ValueError(_("Patrón desconocido: {key}.", key=key))
    custom_re = _custom_regex(custom, custom_is_regex, case_sensitive, whole_word)
    if not patterns and custom_re is None:
        raise ValueError(_("Elige al menos un patrón o escribe un texto a buscar."))
    jobs = [(k, _(PATTERNS[k][0]), _COMPILED[k], PATTERNS[k][2]) for k in patterns]
    if custom_re is not None:
        jobs.append(("custom", _("Texto personalizado"), custom_re, _ok_text))
    found = []
    for index in _pages(doc, pages):
        page = doc[index]
        text, boxes = _page_chars(page)
        taken = []  # spans already claimed on this page
        page_matches = []
        for key, label, regex, check in jobs:
            for m in regex.finditer(text):
                if not m.group(0).strip():
                    continue
                matched = check(m.group(0))
                if matched is None:
                    continue
                start, end = m.start(), m.start() + len(matched)
                if any(start < e and s < end for s, e in taken):
                    continue
                rects = _span_rects(boxes, start, end)
                if not rects:
                    continue
                taken.append((start, end))
                page_matches.append((start, {"page": index, "rect": rects[0], "rects": rects,
                                             "text": text[start:end].replace("\n", " "), "pattern": key, "label": label}))
        found.extend(m for _, m in sorted(page_matches, key=lambda t: t[0]))
    return found


def add_redactions(doc, matches, *, fill=(0, 0, 0)):
    """Add (not apply) redaction annotations for the given matches. Returns the annotation count."""
    _require(doc)
    fill = _color(fill)
    if not matches:
        raise ValueError(_("Selecciona al menos una coincidencia."))
    count = 0
    for match in matches:
        index = match["page"]
        if not isinstance(index, int) or not 0 <= index < len(doc):
            raise ValueError(_("Número de página fuera del documento."))
        page = doc[index]
        for rect in match.get("rects") or [match["rect"]]:
            rect = fitz.Rect(rect)
            if rect.is_empty or rect.is_infinite:
                raise ValueError(_("El área seleccionada no es válida."))
            annot = page.add_redact_annot(rect)
            annot.set_colors(stroke=fill, fill=fill)
            annot.set_info(content=match.get("label", ""))
            annot.update()
            count += 1
    return count


# --------------------------------------------------- 4. optimize / compress

def _downsample_images(doc, dpi, quality):
    changed = 0
    done = set()
    for page in doc:
        for item in page.get_images(full=True):
            xref, smask = item[0], item[1]
            if xref in done:
                continue
            done.add(xref)
            if smask:
                continue
            rects = page.get_image_rects(xref)
            if not rects:
                continue
            try:
                info = doc.extract_image(xref)
                pix = fitz.Pixmap(doc, xref)
            except Exception:
                continue
            if pix.alpha or pix.width < 2 or pix.height < 2:
                continue
            shown_w = max(r.width for r in rects) / 72.0
            shown_h = max(r.height for r in rects) / 72.0
            if shown_w <= 0 or shown_h <= 0:
                continue
            current = max(pix.width / shown_w, pix.height / shown_h)
            if current <= dpi * 1.05:
                continue
            ratio = dpi / current
            new_w, new_h = max(1, round(pix.width * ratio)), max(1, round(pix.height * ratio))
            if pix.colorspace is not None and pix.colorspace.n not in (1, 3):
                pix = fitz.Pixmap(fitz.csRGB, pix)
            small = fitz.Pixmap(pix, new_w, new_h)
            data = small.tobytes("jpeg", jpg_quality=quality)
            if len(data) >= len(info.get("image", b"")):
                continue
            page.replace_image(xref, stream=data)
            changed += 1
    return changed


def optimize(doc, *, dpi=None, jpeg_quality=75, garbage=4, deflate=True, remove_metadata=False,
             remove_unused=True):
    """Compress a copy of ``doc`` and return a result dict; ``doc`` itself is not modified.

    Result: {"data": bytes (valid PDF), "before": int, "after": int, "saved": int,
    "images_resampled": int, "pages": int}. ``data`` is the original serialisation when
    optimizing would make the file bigger. ``dpi`` (e.g. 150, 96) downsamples images that
    exceed it and re-encodes them as JPEG at ``jpeg_quality``; None keeps images untouched.
    """
    _require(doc)
    if dpi is not None and (not isinstance(dpi, (int, float)) or not 36 <= dpi <= 1200):
        raise ValueError(_("Los DPI deben estar entre 36 y 1200."))
    if not isinstance(jpeg_quality, int) or not 1 <= jpeg_quality <= 100:
        raise ValueError(_("La calidad JPEG debe estar entre 1 y 100."))
    if garbage not in (0, 1, 2, 3, 4):
        raise ValueError(_("Nivel de limpieza no válido."))
    original = doc.tobytes(garbage=0, deflate=False, encryption=fitz.PDF_ENCRYPT_NONE)
    before = len(doc.tobytes(garbage=0, deflate=True, encryption=fitz.PDF_ENCRYPT_NONE))
    work = fitz.open(stream=original, filetype="pdf")
    try:
        resampled = _downsample_images(work, dpi, jpeg_quality) if dpi else 0
        if remove_metadata:
            work.set_metadata({})
            work.del_xml_metadata()
        data = work.tobytes(garbage=garbage if remove_unused else min(garbage, 1), deflate=bool(deflate),
                            deflate_images=bool(deflate), deflate_fonts=bool(deflate), clean=True,
                            encryption=fitz.PDF_ENCRYPT_NONE)
    finally:
        work.close()
    with fitz.open(stream=data, filetype="pdf") as check:
        if len(check) != len(doc):
            raise ValueError(_("La optimización cambió el número de páginas; se ha descartado."))
    if len(data) >= before and not remove_metadata:
        data = doc.tobytes(garbage=0, deflate=True, encryption=fitz.PDF_ENCRYPT_NONE)
    after = len(data)
    return {"data": data, "before": before, "after": after, "saved": before - after,
            "images_resampled": resampled, "pages": len(doc)}


# ----------------------------------------------------------- 5. flatten

def flatten(doc, *, annotations=True, forms=True):
    """Bake annotations and/or form fields into the page content. Returns the number baked."""
    _require(doc)
    if not annotations and not forms:
        raise ValueError(_("Elige qué aplanar: anotaciones, formularios o ambos."))
    widgets = sum(1 for page in doc for _ in (page.widgets() or []))
    skipped = (fitz.PDF_ANNOT_WIDGET, fitz.PDF_ANNOT_LINK, fitz.PDF_ANNOT_POPUP, fitz.PDF_ANNOT_REDACT)
    annots = sum(1 for page in doc for a in page.annots() if a.type[0] not in skipped)
    count = (annots if annotations else 0) + (widgets if forms else 0)
    if not count:
        return 0
    # Baking a redaction mark would turn it into plain appearance content and leave the text it covers in
    # the file. Marks are never baked: they are set aside while baking and put back afterwards.
    held = []
    if annotations:
        for page in doc:
            for annot in list(page.annots(types=[fitz.PDF_ANNOT_REDACT]) or ()):
                held.append((page.number, fitz.Rect(annot.rect), annot.colors.get("fill"), annot.info.get("content", "")))
                page.delete_annot(annot)
    try:
        doc.bake(annots=bool(annotations), widgets=bool(forms))
    finally:
        for number, rect, fill, content in held:
            mark = doc[number].add_redact_annot(rect, fill=fill or (0, 0, 0))
            if content:
                mark.set_info(content=content)
                mark.update(fill=fill or (0, 0, 0))
    return count


# ------------------------------------------------------- 6. page labels

LABEL_STYLES = {
    "arabic": "D", "roman_lower": "r", "roman_upper": "R", "letters_lower": "a", "letters_upper": "A", "none": "",
}
LABEL_STYLE_NAMES = {
    "arabic": "1, 2, 3", "roman_lower": "i, ii, iii", "roman_upper": "I, II, III",
    "letters_lower": "a, b, c", "letters_upper": "A, B, C", "none": N_("Solo prefijo"),
}


def set_page_labels(doc, rules):
    """Replace the page labelling. ``rules``: list of dicts

    {"start": zero based first page of the range, "style": key of LABEL_STYLES,
     "prefix": str (optional), "first": first number (optional, default 1)}.
    Pages before the first rule are labelled with plain arabic numbers.
    """
    _require(doc)
    if not rules:
        raise ValueError(_("Añade al menos un rango de etiquetas."))
    n = len(doc)
    ordered = sorted(rules, key=lambda r: r.get("start", 0))
    labels, seen = [], set()
    for rule in ordered:
        start, style = rule.get("start", 0), rule.get("style", "arabic")
        if not isinstance(start, int) or not 0 <= start < n:
            raise ValueError(_("El inicio del rango está fuera del documento."))
        if start in seen:
            raise ValueError(_("Dos rangos empiezan en la misma página."))
        seen.add(start)
        if style not in LABEL_STYLES:
            raise ValueError(_("Estilo de numeración desconocido."))
        first = rule.get("first", 1)
        if not isinstance(first, int) or first < 1:
            raise ValueError(_("El primer número debe ser 1 o mayor."))
        label = {"startpage": start, "prefix": str(rule.get("prefix", "") or ""), "style": LABEL_STYLES[style],
                 "firstpagenum": first}
        labels.append(label)
    if labels[0]["startpage"] != 0:
        labels.insert(0, {"startpage": 0, "prefix": "", "style": "D", "firstpagenum": 1})
    doc.set_page_labels(labels)
    return len(labels)


def page_label_names(doc):
    """List with the visible label of every page (falls back to the page number)."""
    _require(doc)
    return [doc[i].get_label() or str(i + 1) for i in range(len(doc))]


# ------------------------------------------------------ 7. insert pages

def _size(size, width, height, landscape):
    if size == "Personalizado" or size is None:
        if width is None or height is None:
            raise ValueError(_("Indica el ancho y el alto de la página."))
        w, h = float(width), float(height)
    elif size in PAGE_SIZES:
        w, h = PAGE_SIZES[size]
    else:
        raise ValueError(_("Tamaño de página desconocido."))
    if not (20 <= w <= 14400 and 20 <= h <= 14400):
        raise ValueError(_("Las dimensiones de página deben estar entre 20 y 14400 puntos."))
    if landscape and h > w:
        w, h = h, w
    return w, h


def _after(doc, after):
    if not isinstance(after, int) or not -1 <= after < len(doc):
        raise ValueError(_("Posición de inserción no válida."))
    return after + 1


def insert_blank_page(doc, after, size="A4", width=None, height=None, landscape=False):
    """Insert a blank page after page ``after`` (-1 = at the start). Returns the new page index."""
    _require(doc)
    at = _after(doc, after)
    w, h = _size(size, width, height, landscape)
    doc.new_page(pno=at, width=w, height=h)
    return at


def insert_image_page(doc, after, image, size=None, width=None, height=None, landscape=False, margin=0):
    """Insert a page containing ``image`` (path or bytes). Without ``size`` the page matches the
    image; with a size the image is fitted and centred. Returns the new page index."""
    _require(doc)
    at = _after(doc, after)
    margin = _check_size(margin, _("El margen"), 0, 400)
    try:
        if isinstance(image, (bytes, bytearray)):
            pix = fitz.Pixmap(bytes(image))
            stream, filename = bytes(image), None
        else:
            pix = fitz.Pixmap(str(image))
            stream, filename = None, str(image)
    except Exception:
        raise ValueError(_("No se pudo leer la imagen.")) from None
    if size is None:
        xres = pix.xres if pix.xres and pix.xres > 1 else 72
        yres = pix.yres if pix.yres and pix.yres > 1 else 72
        w, h = pix.width * 72.0 / xres, pix.height * 72.0 / yres
        scale = min(1.0, 14400 / max(w, h))
        w, h = max(20.0, w * scale), max(20.0, h * scale)
    else:
        w, h = _size(size, width, height, landscape)
    page = doc.new_page(pno=at, width=w, height=h)
    area = fitz.Rect(margin, margin, w - margin, h - margin)
    if area.is_empty:
        raise ValueError(_("El margen es demasiado grande para la página."))
    page.insert_image(area, stream=stream, filename=filename, keep_proportion=True)
    return at


def duplicate_page(doc, page, copies=1):
    """Duplicate ``page`` right after itself ``copies`` times. Returns the new page indices."""
    _require(doc)
    if not isinstance(page, int) or not 0 <= page < len(doc):
        raise ValueError(_("Número de página fuera del documento."))
    if not isinstance(copies, int) or not 1 <= copies <= 100:
        raise ValueError(_("El número de copias debe estar entre 1 y 100."))
    with fitz.open(stream=doc.tobytes(garbage=0, encryption=fitz.PDF_ENCRYPT_NONE), filetype="pdf") as source:
        for _copy in range(copies):
            doc.insert_pdf(source, from_page=page, to_page=page, start_at=page + 1, widgets=True)
    return list(range(page + 1, page + 1 + copies))


# ---------------------------------------------------------------- 8. stamps

STAMPS = {
    "APROBADO": (0.0, 0.50, 0.20),
    "BORRADOR": (0.45, 0.45, 0.45),
    "CONFIDENCIAL": (0.78, 0.10, 0.10),
    "REVISADO": (0.10, 0.30, 0.75),
    "PAGADO": (0.0, 0.50, 0.20),
    "COPIA": (0.85, 0.45, 0.0),
}


def _stamp_pixmap(text, color, ratio_hint=None):
    """Render the stamp on a transparent pixmap (so it can become a stamp annotation)."""
    width, height = 300.0, 90.0
    scratch = fitz.open()
    try:
        page = scratch.new_page(width=width, height=height)
        _draw_stamp(page, fitz.Rect(4, 4, width - 4, height - 4), text, color)
        return page.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=True)
    finally:
        scratch.close()


def _draw_stamp(page, rect, text, color, opacity=1.0, rotate=0):
    if rotate not in (0, 90, 180, 270):
        raise ValueError(_("La rotación debe ser 0, 90, 180 o 270 grados."))
    shape = page.new_shape()
    # On a rotated page the stamp is laid out upright in visual space; ``rotate`` (the page rotation) turns
    # it about the centre of ``rect`` so it reads upright once the viewer applies the page rotation.
    morph = (rect.tl + (rect.br - rect.tl) / 2, fitz.Matrix(rotate)) if rotate else None
    border = max(1.5, min(rect.width, rect.height) * 0.06)
    shape.draw_rect(rect + (border / 2, border / 2, -border / 2, -border / 2), radius=0.12)
    shape.finish(color=color, fill=None, width=border, fill_opacity=opacity, stroke_opacity=opacity, morph=morph)
    size = rect.height * 0.5
    inner = rect.width - 2 * border - 6
    length = fitz.get_text_length(text, fontname="hebo", fontsize=size)
    if length > inner:
        size *= inner / length
    length = fitz.get_text_length(text, fontname="hebo", fontsize=size)
    origin = fitz.Point(rect.x0 + (rect.width - length) / 2, rect.y0 + rect.height / 2 + size * 0.35)
    shape.insert_text(origin, text, fontname="hebo", fontsize=size, color=color, fill_opacity=opacity,
                      stroke_opacity=opacity, morph=morph)
    shape.commit()


def _turn_png(data, degrees):
    """PNG bytes of an image turned counter-clockwise by a multiple of 90 degrees."""
    if not degrees:
        return data
    from PIL import Image
    with Image.open(io.BytesIO(data)) as image:
        out = io.BytesIO()
        image.convert("RGBA").rotate(degrees, expand=True).save(out, format="PNG")
    return out.getvalue()


def _visual_size(page, rect):
    """Width and height of an unrotated-space rect as the viewer shows it on the rotated page."""
    visual = fitz.Rect(rect) * page.rotation_matrix
    return visual.width, visual.height


def _in_pdf_space(page, centre, width, height):
    """Unrotated-space rect for a box of the given visual size centred on an unrotated point."""
    if page.rotation in (90, 270):
        width, height = height, width
    return fitz.Rect(centre.x - width / 2, centre.y - height / 2, centre.x + width / 2, centre.y + height / 2)


def add_preset_stamp(doc, page, rect, name, *, color=None, as_annotation=True, opacity=1.0):
    """Place one of STAMPS (APROBADO, BORRADOR, ...) at ``rect`` on ``page``.

    ``as_annotation`` creates a stamp annotation (removable); otherwise it is drawn into the page.
    ``color`` overrides the preset colour. Returns the annotation xref, or 0 when drawn.
    """
    _require(doc)
    name = str(name or "").upper()
    if name not in STAMPS:
        raise ValueError(_("Sello desconocido."))
    if not isinstance(page, int) or not 0 <= page < len(doc):
        raise ValueError(_("Número de página fuera del documento."))
    color = _color(color) if color is not None else STAMPS[name]
    if not 0.05 <= opacity <= 1:
        raise ValueError(_("La opacidad debe estar entre 0,05 y 1."))
    target = doc[page]
    rect = fitz.Rect(rect)
    if rect.is_empty or rect.is_infinite:
        raise ValueError(_("El área del sello no es válida."))
    visual_w, visual_h = _visual_size(target, rect)
    if visual_w < 20 or visual_h < 10:
        raise ValueError(_("El área del sello no es válida."))
    rect &= target.rect * target.derotation_matrix
    if rect.is_empty:
        raise ValueError(_("El área está fuera de la página."))
    rotation = target.rotation
    if as_annotation:
        annot = target.add_stamp_annot(rect, stamp=_turn_png(_stamp_pixmap(name, color).tobytes("png"), rotation))
        annot.set_info(title="Sello", content=name)
        annot.set_opacity(opacity)
        annot.update()
        return annot.xref
    width, height = _visual_size(target, rect)
    centre = rect.tl + (rect.br - rect.tl) / 2
    _draw_stamp(target, fitz.Rect(centre.x - width / 2, centre.y - height / 2, centre.x + width / 2, centre.y + height / 2), name, color, opacity, rotate=rotation)
    return 0


def add_image_stamp(doc, page, rect, image, *, as_annotation=True, opacity=1.0):
    """Place an image (path or bytes, PNG alpha respected) fitted inside ``rect``.
    Returns the annotation xref, or 0 when drawn into the content."""
    _require(doc)
    if not isinstance(page, int) or not 0 <= page < len(doc):
        raise ValueError(_("Número de página fuera del documento."))
    if not 0.05 <= opacity <= 1:
        raise ValueError(_("La opacidad debe estar entre 0,05 y 1."))
    target = doc[page]
    rect = fitz.Rect(rect)
    if rect.is_empty or rect.is_infinite:
        raise ValueError(_("El área del sello no es válida."))
    rect &= target.rect * target.derotation_matrix
    if rect.is_empty:
        raise ValueError(_("El área está fuera de la página."))
    try:
        data = bytes(image) if isinstance(image, (bytes, bytearray)) else Path(image).read_bytes()
        pix = fitz.Pixmap(data)
    except Exception:
        raise ValueError(_("No se pudo leer la imagen del sello.")) from None
    # Fit while keeping proportions, centred in the requested area.
    visual_w, visual_h = _visual_size(target, rect)
    scale = min(visual_w / pix.width, visual_h / pix.height)
    centre = rect.tl + (rect.br - rect.tl) / 2
    fitted = _in_pdf_space(target, centre, pix.width * scale, pix.height * scale)
    rotation = target.rotation
    if as_annotation:
        annot = target.add_stamp_annot(fitted, stamp=_turn_png(data, rotation))
        annot.set_info(title="Sello", content="Imagen")
        annot.set_opacity(opacity)
        annot.update()
        return annot.xref
    target.insert_image(fitted, stream=data, keep_proportion=True, overlay=True, rotate=rotation)
    return 0


# ---------------------------------------- 9. statistics / accessibility check

SEVERITIES = ("error", "warning", "info", "ok")


def _catalog_key(doc, key):
    try:
        kind, value = doc.xref_get_key(doc.pdf_catalog(), key)
    except Exception:
        return None
    return None if kind == "null" else value


def _has_javascript(doc):
    for xref in range(1, doc.xref_length()):
        try:
            obj = doc.xref_object(xref, compressed=True)
        except Exception:
            continue
        if "/JavaScript" in obj or re.search(r"/JS\b", obj):
            return True
    return False


def check_document(doc):
    """Quick structural / accessibility review. Returns a dict:

    {"summary": {...numbers and flags...}, "pages": [{page, has_text, images, scanned, blank}],
     "fonts": [{name, embedded, pages}], "findings": [{id, severity, message, page?}]}
    where severity is one of "error", "warning", "info", "ok".
    """
    _require(doc)
    pages, fonts = [], {}
    images_total = form_fields = 0
    for i, page in enumerate(doc):
        text = page.get_text("text").strip()
        imgs = page.get_images(full=True)
        covered = 0.0
        area = max(page.rect.width * page.rect.height, 1.0)
        for item in imgs:
            for r in page.get_image_rects(item[0]):
                covered = max(covered, (r & page.rect).get_area() / area)
        has_text = bool(text)
        scanned = (not has_text) and covered >= 0.7
        pages.append({"page": i, "has_text": has_text, "images": len(imgs), "scanned": scanned,
                      "blank": not has_text and not imgs and not page.get_drawings()})
        images_total += len(imgs)
        form_fields += sum(1 for _ in (page.widgets() or []))
        for item in page.get_fonts(full=True):
            xref, ext, kind, base, name = item[:5]
            label = base.split("+", 1)[-1] if base else (name or str(xref))
            info = fonts.setdefault(xref, {"name": base or name or str(xref), "label": label,
                                           "embedded": ext != "n/a" or kind == "Type3", "pages": []})
            info["pages"].append(i)
    font_list = [{"name": f["name"], "embedded": f["embedded"], "pages": f["pages"]} for f in fonts.values()]
    unembedded = [f for f in font_list if not f["embedded"]]
    metadata = doc.metadata or {}
    title = (metadata.get("title") or "").strip()
    language = (_catalog_key(doc, "Lang") or "").strip("() ")
    has_tags = _catalog_key(doc, "StructTreeRoot") is not None
    marked = "true" in (doc.xref_get_key(doc.pdf_catalog(), "MarkInfo")[1] or "").lower() if _catalog_key(doc, "MarkInfo") else False
    js = _has_javascript(doc)
    encrypted = bool(doc.is_encrypted) or doc.xref_get_key(-1, "Encrypt")[0] != "null"
    scanned_pages = [p["page"] for p in pages if p["scanned"]]
    no_text_pages = [p["page"] for p in pages if not p["has_text"] and not p["scanned"] and not p["blank"]]
    blank_pages = [p["page"] for p in pages if p["blank"]]
    summary = {
        "pages": len(doc), "images": images_total, "fonts": len(font_list), "fonts_not_embedded": len(unembedded),
        "form_fields": form_fields, "encrypted": encrypted, "has_javascript": js,
        "has_tags": has_tags, "marked": marked, "title": title, "language": language,
        "scanned_pages": scanned_pages, "pages_with_text": sum(1 for p in pages if p["has_text"]),
        "blank_pages": blank_pages,
    }
    findings = []

    def add(id_, severity, message, page=None):
        item = {"id": id_, "severity": severity, "message": message}
        if page is not None:
            item["page"] = page
        findings.append(item)

    if scanned_pages:
        listing = ", ".join(str(p + 1) for p in scanned_pages[:10]) + ("…" if len(scanned_pages) > 10 else "")
        add("scanned", "error", _("{count} página(s) parecen escaneadas, sin texto seleccionable (páginas: {listing}). Ejecuta OCR para poder buscar y accesibilizar el texto.", count=len(scanned_pages), listing=listing), page=scanned_pages[0])
    else:
        add("scanned", "ok", _("Todas las páginas con contenido tienen capa de texto."))
    if no_text_pages:
        add("no_text", "warning", _("{count} página(s) no contienen texto (solo gráficos o imágenes pequeñas).", count=len(no_text_pages)))
    if blank_pages:
        add("blank", "info", _("{count} página(s) están en blanco.", count=len(blank_pages)))
    if unembedded:
        names = ", ".join(f["name"] for f in unembedded[:5])
        add("fonts", "warning", _("{count} fuente(s) no están incrustadas ({names}); el aspecto puede variar en otros equipos.", count=len(unembedded), names=names))
    elif font_list:
        add("fonts", "ok", _("Todas las fuentes están incrustadas."))
    if has_tags:
        add("tags", "ok", _("El documento tiene estructura etiquetada (accesible para lectores de pantalla)."))
    else:
        add("tags", "warning", _("El documento no tiene etiquetas de estructura; los lectores de pantalla no podrán seguir el orden de lectura."))
    if title:
        add("title", "ok", _("Título del documento: «{title}».", title=title))
    else:
        add("title", "warning", _("Falta el título en los metadatos del documento."))
    if language:
        add("language", "ok", _("Idioma del documento: {language}.", language=language))
    else:
        add("language", "warning", _("No se ha indicado el idioma del documento."))
    if encrypted:
        add("encryption", "info", _("El documento está cifrado con contraseña."))
    if js:
        add("javascript", "warning", _("El documento contiene JavaScript, que puede ser un riesgo de seguridad."))
    if form_fields:
        add("forms", "info", _("El documento contiene {count} campo(s) de formulario.", count=form_fields))
    if images_total:
        add("images", "info", _("El documento contiene {count} imagen(es).", count=images_total))
    order = {s: i for i, s in enumerate(SEVERITIES)}
    findings.sort(key=lambda f: order[f["severity"]])
    summary["errors"] = sum(1 for f in findings if f["severity"] == "error")
    summary["warnings"] = sum(1 for f in findings if f["severity"] == "warning")
    return {"summary": summary, "pages": pages, "fonts": font_list, "findings": findings}


# ------------------------------------------------------- 10. compare text

def _page_lines(doc, index):
    if index >= len(doc):
        return []
    return [line.strip() for line in doc[index].get_text("text").splitlines() if line.strip()]


def compare_text(doc_a, doc_b):
    """Per-page line diff of two documents.

    Returns {"pages": [{"page": i, "added": [...], "removed": [...], "changed": bool}],
    "changed_pages": [i, ...], "total_pages": n, "pages_a": n, "pages_b": n,
    "added": total, "removed": total}. "removed" lines exist only in ``doc_a`` and
    "added" lines only in ``doc_b``.
    """
    _require(doc_a)
    _require(doc_b)
    total = max(len(doc_a), len(doc_b))
    pages, changed_pages, added_total, removed_total = [], [], 0, 0
    for i in range(total):
        a, b = _page_lines(doc_a, i), _page_lines(doc_b, i)
        added, removed = [], []
        for tag, a0, a1, b0, b1 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
            if tag in ("replace", "delete"):
                removed.extend(a[a0:a1])
            if tag in ("replace", "insert"):
                added.extend(b[b0:b1])
        changed = bool(added or removed)
        pages.append({"page": i, "added": added, "removed": removed, "changed": changed})
        if changed:
            changed_pages.append(i)
        added_total += len(added)
        removed_total += len(removed)
    return {"pages": pages, "changed_pages": changed_pages, "total_pages": total, "pages_a": len(doc_a),
            "pages_b": len(doc_b), "added": added_total, "removed": removed_total}
