import datetime
from types import SimpleNamespace
import io

import pymupdf as fitz
import pytest
from PIL import Image

from pdf_editor import doctools as dt


def make_doc(pages=3, texts=None, size=(612, 792)):
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=size[0], height=size[1])
        body = texts[i] if texts else f"Contenido de la pagina {i + 1}"
        page.insert_text((72, 200), body, fontsize=12)
    return doc


def annots(doc, index=0):
    page = doc[index]
    return [SimpleNamespace(type=a.type, rect=fitz.Rect(a.rect)) for a in page.annots()]


def png(color=(200, 30, 30, 255), size=(60, 30)):
    buf = io.BytesIO()
    Image.new("RGBA", size, color).save(buf, "PNG")
    return buf.getvalue()


def noisy_jpeg(w, h):
    import os
    img = Image.frombytes("RGB", (w, h), os.urandom(w * h * 3))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=95)
    return buf.getvalue()


# ------------------------------------------------------------- helpers

def test_parse_page_range():
    assert dt.parse_page_range("", 5) == [0, 1, 2, 3, 4]
    assert dt.parse_page_range("1-2, 4", 5) == [0, 1, 3]
    assert dt.parse_page_range("3-", 5) == [2, 3, 4]
    assert dt.parse_page_range("-2", 5) == [0, 1]
    for bad in ("0", "9", "3-1", "a", "1-9"):
        with pytest.raises(ValueError):
            dt.parse_page_range(bad, 5)


def test_expand_tokens():
    out = dt.expand_tokens("{filename} {page}/{pages} {date}", 1, 7, "x.pdf", datetime.date(2024, 3, 5))
    assert out == "x.pdf 2/7 05/03/2024"
    assert dt.expand_tokens("sin tokens", 0, 1) == "sin tokens"


# ------------------------------------------------- headers and footers

def test_header_footer_tokens_and_range():
    doc = make_doc(4)
    n = dt.add_header_footer(doc, header=("{filename}", "Informe", "{date}"), footer=("", "Pag {page} de {pages}", ""),
                             pages=[1, 2], filename="a.pdf", date="01/02/2024")
    assert n == 2
    assert "Informe" not in doc[0].get_text()
    t = doc[1].get_text()
    assert "a.pdf" in t and "Informe" in t and "01/02/2024" in t and "Pag 2 de 4" in t
    assert "Pag 3 de 4" in doc[2].get_text()
    assert "Pag" not in doc[3].get_text()


def test_header_footer_positions_and_color():
    doc = make_doc(1)
    dt.add_header_footer(doc, header=("IZQ", "CEN", "DER"), fontsize=12, color=(1, 0, 0), margin_top=30, margin_side=40)
    words = {w[4]: fitz.Rect(w[:4]) for w in doc[0].get_text("words")}
    assert words["IZQ"].x0 == pytest.approx(40, abs=1)
    assert words["DER"].x1 == pytest.approx(612 - 40, abs=1.5)
    assert (words["CEN"].x0 + words["CEN"].x1) / 2 == pytest.approx(306, abs=1.5)
    assert words["IZQ"].y1 < 60
    span = next(s for b in doc[0].get_text("dict")["blocks"] for l in b["lines"] for s in l["spans"] if "IZQ" in s["text"])
    assert span["color"] == 0xFF0000 and span["size"] == 12


def test_footer_bottom_and_string_range():
    doc = make_doc(3)
    assert dt.add_header_footer(doc, footer=("", "pie", ""), pages="2-3", margin_bottom=20) == 2
    w = [w for w in doc[2].get_text("words") if w[4] == "pie"][0]
    assert w[3] == pytest.approx(792 - 20, abs=4)


@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_header_on_rotated_page_reads_upright(rotation):
    doc = make_doc(1)
    doc[0].set_rotation(rotation)
    dt.add_header_footer(doc, header=("", "ROTADO", ""))
    page = doc[0]
    hit = page.search_for("ROTADO")
    assert hit, "text must be findable"
    r = hit[0] * page.rotation_matrix
    line = next(l for b in page.get_text("dict")["blocks"] for l in b["lines"] if "ROTADO" in l["spans"][0]["text"])
    d = fitz.Point(line["dir"]) * fitz.Matrix(page.rotation_matrix.a, page.rotation_matrix.b, page.rotation_matrix.c, page.rotation_matrix.d, 0, 0)
    assert d.x == pytest.approx(1, abs=0.01) and d.y == pytest.approx(0, abs=0.01)
    # Visual (rotated) coordinates: the header sits near the visual top.
    assert r.y0 < 60 and r.width > r.height
    assert (r.x0 + r.x1) / 2 == pytest.approx(page.rect.width / 2, abs=3)


def test_header_footer_errors():
    doc = make_doc(1)
    with pytest.raises(ValueError, match="al menos un texto"):
        dt.add_header_footer(doc)
    with pytest.raises(ValueError):
        dt.add_header_footer(doc, header=("a", "b"))
    with pytest.raises(ValueError):
        dt.add_header_footer(doc, header=("a", "", ""), color=(2, 0, 0))
    with pytest.raises(ValueError):
        dt.add_header_footer(doc, header=("a", "", ""), pages=[5])
    with pytest.raises(ValueError):
        dt.add_header_footer(doc, header=("a", "", ""), fontsize=0)
    with pytest.raises(ValueError):
        dt.add_header_footer(doc, header=("a", "", ""), margin_top=400, margin_bottom=400)


# ------------------------------------------------------------- Bates

def test_bates_numbering():
    doc = make_doc(3)
    last = dt.add_bates(doc, prefix="ABC-", suffix="-X", start=41, digits=5)
    assert last == 43
    assert "ABC-00041-X" in doc[0].get_text()
    assert "ABC-00043-X" in doc[2].get_text()
    w = [w for w in doc[0].get_text("words") if w[4].startswith("ABC")][0]
    assert w[2] <= 612 - 35 and w[3] > 700  # bottom right


def test_bates_positions_and_pages():
    doc = make_doc(3)
    assert dt.add_bates(doc, start=10, digits=3, position="top-left", pages=[2]) == 10
    w = [w for w in doc[2].get_text("words") if w[4] == "010"][0]
    assert w[0] == pytest.approx(36, abs=1) and w[3] < 60
    assert "010" not in doc[0].get_text()
    assert dt.bates_label(7, "A", "B", 4) == "A0007B"


def test_bates_errors():
    doc = make_doc(1)
    for kw in ({"position": "medio"}, {"start": -1}, {"digits": 0}, {"digits": 99}, {"pages": []}):
        with pytest.raises(ValueError):
            dt.add_bates(doc, **kw)


# ------------------------------------------------------ search / redact

def found(text, key, **kw):
    doc = make_doc(1, [text])
    return doc, dt.find_matches(doc, [key], **kw)


@pytest.mark.parametrize("key,good,bad", [
    ("email", "Escribe a juan.perez+x@correo.example.es hoy", "usuario@ sin dominio"),
    ("telefono_es", "Llama al 612 345 678 ya", "Llama al 512 345 678 ya"),
    ("telefono_es", "Tel +34 912345678.", "Tel 1234"),
    ("telefono_intl", "Phone +44 20 7946 0958 now", "Phone +1 2 now"),
    ("dni_nie", "DNI 12345678Z fin", "DNI 12345678A fin"),
    ("dni_nie", "NIE X1234567L fin", "NIE X1234567A fin"),
    ("nif_cif", "CIF A58818501 fin", "CIF A58818502 fin"),
    ("nif_cif", "CIF Q2826000H fin", "CIF Q2826000A fin"),
    ("iban", "IBAN ES91 2100 0418 4502 0005 1332 ok", "IBAN ES91 2100 0418 4502 0005 1333 ok"),
    ("tarjeta", "Tarjeta 4539 1488 0343 6467 ok", "Tarjeta 4539 1488 0343 6468 ok"),
    ("tarjeta", "Tarjeta 4539148803436467 ok", "Tarjeta 1234567890123456 ok"),
    ("fecha", "El 25/12/2023 fue", "El 31/02/2023 fue"),
    ("fecha", "El 2023-12-25 fue", "El 2023-13-25 fue"),
    ("fecha", "El 5 de marzo de 2021 fue", "El 5 de marzano de 2021 fue"),
])
def test_builtin_patterns(key, good, bad):
    _, hits = found(good, key)
    assert len(hits) == 1, (key, good, hits)
    assert hits[0]["pattern"] == key and hits[0]["page"] == 0
    assert hits[0]["rect"].width > 10
    _, none = found(bad, key)
    assert none == [], (key, bad, none)


def test_match_text_and_rect_location():
    doc, hits = found("Contacto: ana@correo.es gracias", "email")
    assert hits[0]["text"] == "ana@correo.es"
    r = hits[0]["rect"]
    clip_text = doc[0].get_textbox(r + (-1, -1, 1, 1)).strip()
    assert clip_text == "ana@correo.es"


def test_iban_stops_before_trailing_words():
    _, hits = found("ES91 2100 0418 4502 0005 1332 titular Juan", "iban")
    assert hits[0]["text"] == "ES91 2100 0418 4502 0005 1332"


def test_card_vs_phone_no_overlap():
    doc = make_doc(1, ["Tarjeta 4539 1488 0343 6467 y tel 612 345 678"])
    hits = dt.find_matches(doc, ["tarjeta", "telefono_es"])
    assert sorted(h["pattern"] for h in hits) == ["tarjeta", "telefono_es"]


def test_custom_text_and_case_options():
    doc = make_doc(2, ["Secreto secreto SECRETO", "otro Secreto"])
    assert len(dt.find_matches(doc, custom="secreto")) == 4
    assert len(dt.find_matches(doc, custom="secreto", case_sensitive=True)) == 1
    assert len(dt.find_matches(doc, custom="Secreto", case_sensitive=True)) == 2
    assert [h["page"] for h in dt.find_matches(doc, custom="Secreto", case_sensitive=True)] == [0, 1]
    only = dt.find_matches(doc, custom="otro", pages=[1])
    assert len(only) == 1 and only[0]["pattern"] == "custom"


def test_custom_whole_word_and_regex():
    doc = make_doc(1, ["casa casas casado"])
    assert len(dt.find_matches(doc, custom="casa", whole_word=True)) == 1
    assert len(dt.find_matches(doc, custom="casa")) == 3
    hits = dt.find_matches(doc, custom=r"cas\w+", custom_is_regex=True)
    assert [h["text"] for h in hits] == ["casa", "casas", "casado"]
    # Plain text with regex metacharacters must be literal.
    doc2 = make_doc(1, ["precio (a+b) final"])
    assert len(dt.find_matches(doc2, custom="(a+b)")) == 1


def test_find_matches_errors():
    doc = make_doc(1)
    with pytest.raises(ValueError, match="patrón"):
        dt.find_matches(doc)
    with pytest.raises(ValueError, match="desconocido"):
        dt.find_matches(doc, ["nope"])
    with pytest.raises(ValueError, match="expresión"):
        dt.find_matches(doc, custom="(", custom_is_regex=True)


def test_multi_line_match_has_rect_per_line():
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "frase que se parte", fontsize=12)
    page.insert_text((72, 120), "en dos lineas", fontsize=12)
    hits = dt.find_matches(doc, custom=r"parte\s+en", custom_is_regex=True)
    assert len(hits) == 1 and len(hits[0]["rects"]) == 2


def test_add_redactions_not_applied():
    doc = make_doc(2, ["Mail ana@correo.es", "Mail bob@correo.es"])
    hits = dt.find_matches(doc, ["email"])
    assert dt.add_redactions(doc, hits[:1]) == 1
    annots0 = annots(doc, 0)
    assert len(annots0) == 1 and annots0[0].type[0] == fitz.PDF_ANNOT_REDACT
    assert annots(doc, 1) == []
    assert "ana@correo.es" in doc[0].get_text()  # still present: not applied
    doc[0].apply_redactions()
    assert "ana@correo.es" not in doc[0].get_text()
    with pytest.raises(ValueError):
        dt.add_redactions(doc, [])
    with pytest.raises(ValueError):
        dt.add_redactions(doc, [{"page": 9, "rect": fitz.Rect(0, 0, 5, 5)}])
    with pytest.raises(ValueError):
        dt.add_redactions(doc, hits, fill=(3, 0, 0))


# -------------------------------------------------------------- optimize

def image_doc():
    doc = fitz.open()
    page = doc.new_page()
    page.insert_image(fitz.Rect(50, 50, 250, 250), stream=noisy_jpeg(1600, 1600))
    page.insert_text((72, 400), "Texto conservado", fontsize=14)
    doc.set_metadata({"title": "Titulo", "author": "Yo"})
    return doc


def test_optimize_downsample_reduces_size_and_keeps_text():
    doc = image_doc()
    res = dt.optimize(doc, dpi=96, jpeg_quality=60)
    assert res["after"] < res["before"] * 0.5
    assert res["images_resampled"] == 1
    assert res["saved"] == res["before"] - res["after"] and res["after"] == len(res["data"])
    out = fitz.open(stream=res["data"], filetype="pdf")
    assert len(out) == 1 and "Texto conservado" in out[0].get_text()
    xref = out[0].get_images()[0][0]
    assert out.extract_image(xref)["width"] < 400
    assert out[0].get_pixmap().width > 0
    # Original is untouched.
    assert doc.extract_image(doc[0].get_images()[0][0])["width"] == 1600


def test_optimize_no_images_option_and_metadata_removal():
    doc = image_doc()
    res = dt.optimize(doc)
    assert res["images_resampled"] == 0
    kept = fitz.open(stream=res["data"], filetype="pdf")
    assert kept.metadata["title"] == "Titulo"
    res2 = dt.optimize(doc, remove_metadata=True)
    stripped = fitz.open(stream=res2["data"], filetype="pdf")
    assert not stripped.metadata["title"] and not stripped.metadata["author"]


def test_optimize_garbage_removes_unused_objects():
    doc = make_doc(2)
    for _ in range(30):
        doc.get_new_xref()
        xref = doc.get_new_xref()
        doc.update_object(xref, "<< /Junk (" + "x" * 2000 + ") >>")
    res = dt.optimize(doc, garbage=4)
    assert res["after"] < res["before"]
    out = fitz.open(stream=res["data"], filetype="pdf")
    assert len(out) == 2


def test_optimize_never_returns_bigger():
    doc = make_doc(1)
    res = dt.optimize(doc, dpi=72)
    assert res["after"] <= res["before"]
    assert fitz.open(stream=res["data"], filetype="pdf").page_count == 1


def test_optimize_skips_transparent_images():
    doc = fitz.open()
    page = doc.new_page()
    page.insert_image(fitz.Rect(10, 10, 60, 60), stream=png(size=(800, 800)))
    res = dt.optimize(doc, dpi=72)
    assert res["images_resampled"] == 0
    assert len(fitz.open(stream=res["data"], filetype="pdf")) == 1


def test_optimize_errors():
    doc = make_doc(1)
    for kw in ({"dpi": 5}, {"jpeg_quality": 0}, {"jpeg_quality": 101}, {"garbage": 9}):
        with pytest.raises(ValueError):
            dt.optimize(doc, **kw)


# --------------------------------------------------------------- flatten

def form_doc():
    doc = make_doc(1)
    page = doc[0]
    w = fitz.Widget()
    w.field_name, w.field_type, w.rect, w.field_value = "nombre", fitz.PDF_WIDGET_TYPE_TEXT, fitz.Rect(72, 300, 300, 330), "Valor visible"
    page.add_widget(w)
    page.add_rect_annot(fitz.Rect(72, 400, 200, 450)).update()
    page.add_text_annot((300, 400), "nota").update()
    return doc


def test_flatten_both():
    doc = form_doc()
    count = dt.flatten(doc)
    assert count == 3
    page = doc[0]
    assert not list(page.widgets() or [])
    assert not [a for a in page.annots() if a.type[0] != fitz.PDF_ANNOT_LINK]
    assert "Valor visible" in page.get_text()


def test_flatten_forms_only_and_annots_only():
    doc = form_doc()
    assert dt.flatten(doc, annotations=False, forms=True) == 1
    assert not list(doc[0].widgets() or [])
    assert len(annots(doc, 0)) == 2
    doc2 = form_doc()
    assert dt.flatten(doc2, annotations=True, forms=False) == 2
    assert len(list(doc2[0].widgets() or [])) == 1
    assert dt.flatten(make_doc(1)) == 0
    with pytest.raises(ValueError):
        dt.flatten(doc2, annotations=False, forms=False)


# ------------------------------------------------------------ page labels

def test_page_labels_roman_arabic_prefix():
    doc = make_doc(7)
    n = dt.set_page_labels(doc, [
        {"start": 0, "style": "roman_lower"},
        {"start": 2, "style": "arabic", "first": 1},
        {"start": 5, "style": "letters_upper", "prefix": "Anexo "},
    ])
    assert n == 3
    assert dt.page_label_names(doc) == ["i", "ii", "1", "2", "3", "Anexo A", "Anexo B"]


def test_page_labels_defaults_and_first_number():
    doc = make_doc(4)
    dt.set_page_labels(doc, [{"start": 2, "style": "roman_upper", "first": 4}])
    assert dt.page_label_names(doc) == ["1", "2", "IV", "V"]
    dt.set_page_labels(doc, [{"start": 0, "style": "letters_lower"}, {"start": 1, "style": "none", "prefix": "P-"}])
    assert dt.page_label_names(doc)[0] == "a"
    assert dt.page_label_names(doc)[1].startswith("P-")


def test_page_labels_errors():
    doc = make_doc(3)
    for rules in ([], [{"start": 5}], [{"start": 0, "style": "x"}], [{"start": 0}, {"start": 0}], [{"start": 0, "first": 0}]):
        with pytest.raises(ValueError):
            dt.set_page_labels(doc, rules)


# --------------------------------------------------------------- insert

@pytest.mark.parametrize("name", ["A4", "Carta", "A3", "A5"])
def test_insert_blank_sizes(name):
    doc = make_doc(2)
    idx = dt.insert_blank_page(doc, 0, name)
    assert idx == 1 and len(doc) == 3
    assert doc[1].rect.width == pytest.approx(dt.PAGE_SIZES[name][0], abs=0.1)
    assert doc[2].get_text().strip().endswith("2")


def test_insert_blank_custom_landscape_start_and_errors():
    doc = make_doc(1)
    assert dt.insert_blank_page(doc, -1, "Personalizado", width=300, height=500) == 0
    assert (doc[0].rect.width, doc[0].rect.height) == (300, 500)
    dt.insert_blank_page(doc, 1, "A4", landscape=True)
    assert doc[2].rect.width > doc[2].rect.height
    for kw in ({"after": 9}, {"after": 0, "size": "Folio"}, {"after": 0, "size": "Personalizado"},
               {"after": 0, "size": "Personalizado", "width": 5, "height": 100}):
        with pytest.raises(ValueError):
            dt.insert_blank_page(doc, **kw)


def test_insert_image_page_native_and_fit():
    doc = make_doc(1)
    data = png(size=(200, 100))
    idx = dt.insert_image_page(doc, 0, data)
    assert idx == 1 and len(doc[1].get_images()) == 1
    res = fitz.Pixmap(data).xres or 72
    assert doc[1].rect.width == pytest.approx(200 * 72 / res, abs=1) and doc[1].rect.height == pytest.approx(100 * 72 / res, abs=1)
    idx = dt.insert_image_page(doc, -1, data, size="A4", margin=20)
    assert idx == 0 and doc[0].rect.width == pytest.approx(595.276, abs=0.1)
    r = doc[0].get_image_rects(doc[0].get_images()[0][0])[0]
    assert r.x0 == pytest.approx(20, abs=0.5) and r.width / r.height == pytest.approx(2, abs=0.05)


def test_insert_image_page_from_file_and_errors(tmp_path):
    p = tmp_path / "i.png"
    p.write_bytes(png())
    doc = make_doc(1)
    assert dt.insert_image_page(doc, 0, p) == 1
    with pytest.raises(ValueError, match="imagen"):
        dt.insert_image_page(doc, 0, b"no es una imagen")
    with pytest.raises(ValueError):
        dt.insert_image_page(doc, 0, tmp_path / "nada.png")


def test_duplicate_page():
    doc = make_doc(3)
    assert dt.duplicate_page(doc, 1, copies=2) == [2, 3]
    assert len(doc) == 5
    assert [("pagina 2" in doc[i].get_text()) for i in range(5)] == [False, True, True, True, False]
    with pytest.raises(ValueError):
        dt.duplicate_page(doc, 9)
    with pytest.raises(ValueError):
        dt.duplicate_page(doc, 0, copies=0)


# ---------------------------------------------------------------- stamps

@pytest.mark.parametrize("name", list(dt.STAMPS))
def test_preset_stamp_as_annotation(name):
    doc = make_doc(1)
    xref = dt.add_preset_stamp(doc, 0, fitz.Rect(100, 100, 300, 160), name)
    assert xref > 0
    found_annots = annots(doc, 0)
    assert len(found_annots) == 1 and found_annots[0].type[0] == fitz.PDF_ANNOT_STAMP
    pix = doc[0].get_pixmap(clip=fitz.Rect(100, 100, 300, 160))
    assert any(pix.pixel(x, y) != (255, 255, 255) for x in range(0, pix.width, 5) for y in range(0, pix.height, 5))


def test_preset_stamp_drawn_with_color():
    doc = make_doc(1)
    assert dt.add_preset_stamp(doc, 0, fitz.Rect(100, 100, 300, 160), "copia", color=(0, 0, 1), as_annotation=False) == 0
    assert annots(doc, 0) == []
    pix = doc[0].get_pixmap(clip=fitz.Rect(100, 100, 300, 160))
    px = {pix.pixel(x, y) for x in range(pix.width) for y in range(pix.height)}
    assert any(r < 60 and g < 60 and b > 150 for r, g, b in px)


def test_preset_stamp_errors():
    doc = make_doc(1)
    for args in ((0, fitz.Rect(1, 1, 2, 2), "APROBADO"), (0, fitz.Rect(100, 100, 300, 160), "NOPE"),
                 (3, fitz.Rect(100, 100, 300, 160), "APROBADO"), (0, fitz.Rect(900, 900, 990, 990), "APROBADO")):
        with pytest.raises(ValueError):
            dt.add_preset_stamp(doc, *args)
    with pytest.raises(ValueError):
        dt.add_preset_stamp(doc, 0, fitz.Rect(100, 100, 300, 160), "COPIA", opacity=0)


def test_image_stamp_annotation_and_drawn(tmp_path):
    data = png((10, 10, 200, 255), size=(100, 50))
    doc = make_doc(1)
    assert dt.add_image_stamp(doc, 0, fitz.Rect(100, 500, 300, 700), data) > 0
    annot = annots(doc, 0)[0]
    assert annot.type[0] == fitz.PDF_ANNOT_STAMP
    # Fitted keeping 2:1 proportion, centred in the requested area.
    assert annot.rect.width / annot.rect.height == pytest.approx(2, abs=0.05)
    pix = doc[0].get_pixmap(clip=fitz.Rect(100, 500, 300, 700))
    assert pix.pixel(pix.width // 2, pix.height // 2)[2] > 150
    p = tmp_path / "firma.png"
    p.write_bytes(data)
    doc2 = make_doc(1)
    assert dt.add_image_stamp(doc2, 0, fitz.Rect(100, 500, 300, 700), p, as_annotation=False) == 0
    assert len(doc2[0].get_images()) == 1
    with pytest.raises(ValueError):
        dt.add_image_stamp(doc2, 0, fitz.Rect(100, 500, 300, 700), b"xx")


def test_image_stamp_transparency_preserved():
    buf = io.BytesIO()
    img = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    img.paste((255, 0, 0, 255), (0, 0, 20, 40))
    img.save(buf, "PNG")
    doc = make_doc(1)
    dt.add_image_stamp(doc, 0, fitz.Rect(100, 500, 200, 600), buf.getvalue(), as_annotation=False)
    pix = doc[0].get_pixmap(clip=fitz.Rect(100, 500, 200, 600))
    assert pix.pixel(10, 50) == (255, 0, 0)
    assert pix.pixel(90, 50) == (255, 255, 255)


# ------------------------------------------------------------ check doc

def test_check_document_clean_text_pdf():
    doc = make_doc(2)
    doc.set_metadata({"title": "Mi doc"})
    rep = dt.check_document(doc)
    s = rep["summary"]
    assert s["pages"] == 2 and s["scanned_pages"] == [] and s["images"] == 0
    assert s["title"] == "Mi doc" and s["has_tags"] is False and s["has_javascript"] is False
    ids = {f["id"]: f for f in rep["findings"]}
    assert ids["scanned"]["severity"] == "ok"
    assert ids["tags"]["severity"] == "warning" and ids["language"]["severity"] == "warning"
    assert ids["title"]["severity"] == "ok"
    assert all(p["has_text"] for p in rep["pages"])
    assert {f["severity"] for f in rep["findings"]} <= set(dt.SEVERITIES)
    severities = [dt.SEVERITIES.index(f["severity"]) for f in rep["findings"]]
    assert severities == sorted(severities)


def test_check_document_scanned_page_and_images():
    doc = make_doc(2)
    scan = doc.new_page()
    scan.insert_image(scan.rect, stream=noisy_jpeg(120, 160))
    rep = dt.check_document(doc)
    assert rep["summary"]["scanned_pages"] == [2]
    assert rep["pages"][2]["scanned"] and not rep["pages"][2]["has_text"]
    f = [x for x in rep["findings"] if x["id"] == "scanned"][0]
    assert f["severity"] == "error" and "OCR" in f["message"]
    assert rep["summary"]["errors"] == 1 and rep["summary"]["images"] == 1


def test_check_document_blank_and_fonts():
    doc = make_doc(1)
    doc.new_page()
    rep = dt.check_document(doc)
    assert rep["summary"]["blank_pages"] == [1]
    assert rep["fonts"] and rep["fonts"][0]["embedded"] is False
    f = [x for x in rep["findings"] if x["id"] == "fonts"][0]
    assert f["severity"] == "warning" and "Helvetica" in f["message"]


def test_check_document_embedded_font_tags_lang_js_forms_encryption():
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Hola", fontsize=12)
    cat = doc.pdf_catalog()
    doc.xref_set_key(cat, "Lang", "(es-ES)")
    doc.xref_set_key(cat, "MarkInfo", "<</Marked true>>")
    st = doc.get_new_xref()
    doc.update_object(st, "<</Type/StructTreeRoot>>")
    doc.xref_set_key(cat, "StructTreeRoot", f"{st} 0 R")
    doc.xref_set_key(cat, "OpenAction", "<</S/JavaScript/JS(app.alert\\(1\\))>>")
    w = fitz.Widget()
    w.field_name, w.field_type, w.rect = "c", fitz.PDF_WIDGET_TYPE_TEXT, fitz.Rect(10, 10, 100, 30)
    page.add_widget(w)
    rep = dt.check_document(doc)
    s = rep["summary"]
    assert s["has_tags"] and s["language"] == "es-ES" and s["has_javascript"] and s["form_fields"] == 1
    ids = {f["id"]: f["severity"] for f in rep["findings"]}
    assert ids["tags"] == "ok" and ids["language"] == "ok" and ids["javascript"] == "warning" and ids["forms"] == "info"
    enc = fitz.open(stream=make_doc(1).tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="a", owner_pw="b"), filetype="pdf")
    assert enc.authenticate("a")
    rep2 = dt.check_document(enc)
    assert rep2["summary"]["encrypted"] is True
    assert any(f["id"] == "encryption" for f in rep2["findings"])


def test_check_document_embedded_font_detected():
    src = fitz.open()
    p = src.new_page()
    p.insert_text((72, 100), "Hola", fontsize=12)
    p.insert_font(fontname="emb", fontbuffer=fitz.Font("helv").buffer)
    p.insert_text((72, 140), "Embebida", fontname="emb", fontsize=12)
    rep = dt.check_document(src)
    flags = {f["name"]: f["embedded"] for f in rep["fonts"]}
    assert True in flags.values() and False in flags.values()


# ----------------------------------------------------------- compare text

def test_compare_text_added_removed_per_page():
    a = make_doc(3, ["uno\ndos\ntres", "igual", "solo en A"])
    b = make_doc(3, ["uno\ntres\ncuatro", "igual", "solo en A"])
    for doc, texts in ((a, ["uno", "dos", "tres"]), (b, ["uno", "tres", "cuatro"])):
        doc[0].clean_contents()
    res = dt.compare_text(a, b)
    assert res["total_pages"] == 3 and res["changed_pages"] == [0]
    p0 = res["pages"][0]
    assert "dos" in " ".join(p0["removed"]) and "cuatro" in " ".join(p0["added"])
    assert res["pages"][1]["changed"] is False and res["pages"][2]["added"] == []
    assert res["added"] >= 1 and res["removed"] >= 1


def test_compare_text_different_lengths_and_identical():
    a, b = make_doc(2), make_doc(3)
    res = dt.compare_text(a, b)
    assert res["pages_a"] == 2 and res["pages_b"] == 3 and res["changed_pages"] == [2]
    assert res["pages"][2]["added"] and not res["pages"][2]["removed"]
    res2 = dt.compare_text(b, a)
    assert res2["pages"][2]["removed"] and not res2["pages"][2]["added"]
    same = dt.compare_text(make_doc(2), make_doc(2))
    assert same["changed_pages"] == [] and same["added"] == 0 and same["removed"] == 0


def test_closed_doc_rejected():
    doc = make_doc(1)
    doc.close()
    with pytest.raises(ValueError, match="documento"):
        dt.add_bates(doc)
