import io
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf as fitz
import pytest
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from pdf_editor import doctools as dt
from pdf_editor import doctools_dialogs as dd
from pdf_editor.theme import STYLE


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    a.setStyleSheet(STYLE)
    return a


def make_doc(texts):
    doc = fitz.open()
    for t in texts:
        doc.new_page().insert_text((72, 200), t, fontsize=12)
    return doc


def test_header_footer_dialog_values_and_apply(app):
    dlg = dd.HeaderFooterDialog(page_count=5, filename="doc.pdf", date="01/01/2024")
    dlg.header[0].setText("{filename}")
    dlg.footer[1].setText("Página {page} de {pages}")
    dlg.fontsize.setValue(11)
    dlg.margin_side.setValue(30)
    dlg.pages.setText("2-3")
    dlg.color.set_rgb((1, 0, 0))
    v = dlg.values()
    assert v["header"] == ("{filename}", "", "") and v["footer"] == ("", "Página {page} de {pages}", "")
    assert v["fontsize"] == 11 and v["margin_side"] == 30 and v["pages"] == [1, 2]
    assert v["color"] == (1.0, 0.0, 0.0) and v["filename"] == "doc.pdf"
    assert set(v) == {"header", "footer", "fontsize", "color", "margin_top", "margin_bottom", "margin_side", "pages", "filename"}
    doc = make_doc(["a"] * 5)
    assert dt.add_header_footer(doc, **v) == 2


def test_header_footer_live_preview(app):
    dlg = dd.HeaderFooterDialog(page_count=9, filename="x.pdf", date="02/02/2024")
    dlg.header[2].setText("{date}")
    dlg.footer[1].setText("{page}/{pages} {filename}")
    text = dlg.preview.text()
    assert "02/02/2024" in text and "1/9 x.pdf" in text
    assert "5/9 x.pdf" in dlg.preview_text(4)
    dlg.footer[1].setText("{page}")
    assert "1/9" not in dlg.preview.text()


def test_header_footer_validation(app):
    dlg = dd.HeaderFooterDialog(page_count=3)
    dlg.accept()
    assert dlg.result() != dlg.DialogCode.Accepted
    assert "al menos un texto" in dlg.error.text()
    dlg.header[0].setText("x")
    dlg.pages.setText("9")
    dlg.accept()
    assert "fuera del documento" in dlg.error.text()
    dlg.pages.setText("")
    dlg.accept()
    assert dlg.result() == dlg.DialogCode.Accepted and dlg.error.text() == ""


def test_bates_dialog(app):
    dlg = dd.BatesDialog(page_count=4)
    dlg.prefix.setText("CASO-")
    dlg.start.setValue(10)
    dlg.digits.setValue(4)
    dlg.position.setCurrentIndex(dlg.position.findData("top-left"))
    assert "CASO-0010" in dlg.preview.text() and "CASO-0013" in dlg.preview.text()
    v = dlg.values()
    assert v["prefix"] == "CASO-" and v["start"] == 10 and v["digits"] == 4 and v["position"] == "top-left"
    assert set(v) == {"prefix", "suffix", "start", "digits", "position", "fontsize", "color", "margin", "pages"}
    doc = make_doc(["a"] * 4)
    assert dt.add_bates(doc, **v) == 13
    dlg.pages.setText("2")
    assert "(1 páginas)" in dlg.preview.text()
    dlg.pages.setText("zz")
    dlg.accept()
    assert "Rango" in dlg.error.text()


def test_redact_dialog_search_and_selection(app):
    doc = make_doc(["Mail ana@correo.es y bob@correo.es", "Tel 612 345 678 y el DNI 12345678Z"])
    dlg = dd.RedactSearchDialog(doc)
    assert not dlg.ok_button.isEnabled()
    dlg.search()
    assert "al menos un patrón" in dlg.error.text()
    dlg.pattern_checks["email"].setChecked(True)
    dlg.pattern_checks["dni_nie"].setChecked(True)
    dlg.search()
    assert dlg.results.count() == 3 and dlg.ok_button.isEnabled()
    assert all(dlg.results.item(i).checkState() == Qt.Checked for i in range(3))
    dlg.results.item(0).setCheckState(Qt.Unchecked)
    assert "2 de 3" in dlg.summary.text()
    v = dlg.values()
    assert len(v["matches"]) == 2 and v["fill"] == (0.0, 0.0, 0.0)
    assert v["patterns"] == ["email", "dni_nie"]
    assert dt.add_redactions(doc, v["matches"], fill=v["fill"]) == 2
    dlg.set_all_checked(False)
    assert not dlg.ok_button.isEnabled()
    dlg.accept()
    assert "al menos una" in dlg.error.text()


def test_redact_dialog_custom(app):
    doc = make_doc(["Secreto y secreto"])
    dlg = dd.RedactSearchDialog(doc)
    dlg.custom.setText("secreto")
    dlg.case.setChecked(True)
    dlg.search()
    assert dlg.results.count() == 1
    dlg.case.setChecked(False)
    dlg.search()
    assert dlg.results.count() == 2
    dlg.custom.setText("(")
    dlg.regex.setChecked(True)
    dlg.search()
    assert dlg.results.count() == 0 and "expresión" in dlg.error.text()
    assert dd.RedactSearchDialog(None).values()["matches"] == []


def test_optimize_dialog(app):
    dlg = dd.OptimizeDialog(current_size=5 * 1024 * 1024)
    assert "5,0 MB" in dlg.current.text()
    assert dlg.values() == {"dpi": 150, "jpeg_quality": 75, "remove_metadata": False, "remove_unused": True}
    dlg.preset.setCurrentIndex(2)
    assert dlg.values()["dpi"] == 96 and dlg.values()["jpeg_quality"] == 55
    dlg.preset.setCurrentIndex(3)
    assert dlg.values()["dpi"] is None and not dlg.dpi.isEnabled()
    dlg.remove_metadata.setChecked(True)
    got = []
    dlg.previewRequested.connect(got.append)
    dlg.calc_button.click()
    assert got and got[0]["remove_metadata"] is True
    dlg.set_result(2048 * 1024, 512 * 1024)
    assert "2,0 MB → 512,0 KB" in dlg.result.text() and "75 %" in dlg.result.text()
    dlg.set_result(100, 100)
    assert "no se puede reducir" in dlg.result.text()
    assert dt.optimize(make_doc(["a"]), **dlg.values())["pages"] == 1


def test_page_labels_dialog(app):
    dlg = dd.PageLabelsDialog(page_count=8)
    assert dlg.values() == {"rules": [{"start": 0, "style": "arabic", "prefix": "", "first": 1}]}
    combo = dlg.table.cellWidget(0, 1)
    combo.setCurrentIndex(combo.findData("roman_lower"))
    dlg.add_rule(4, "arabic")
    dlg.add_rule(7, "letters_upper", prefix="Anexo ")
    rules = dlg.values()["rules"]
    assert [r["start"] for r in rules] == [0, 3, 6] and rules[2]["prefix"] == "Anexo "
    assert dlg.label_names(8) == ["i", "ii", "iii", "1", "2", "3", "Anexo A", "Anexo B"]
    assert "1→i" in dlg.preview.text() and "Anexo A" in dlg.preview.text()
    doc = make_doc(["a"] * 8)
    dt.set_page_labels(doc, rules)
    assert dt.page_label_names(doc)[6] == "Anexo A"
    dlg.table.selectRow(2)
    dlg.remove_selected()
    assert len(dlg.rules()) == 2
    dlg.table.cellWidget(1, 0).setValue(1)
    dlg.accept()
    assert "misma página" in dlg.error.text()


def test_insert_page_dialog_modes(app):
    dlg = dd.InsertPageDialog(page_count=3, current=1)
    v = dlg.values()
    assert v["mode"] == "blank" and v["size"] == "A4" and v["after"] == 1 and v["page"] == 1
    assert not dlg.width.isEnabled()
    dlg.size.setCurrentIndex(dlg.size.findData("Personalizado"))
    assert dlg.width.isEnabled()
    dlg.width.setValue(300)
    dlg.height.setValue(400)
    dlg.landscape.setChecked(True)
    dlg.where.setCurrentIndex(0)
    v = dlg.values()
    assert (v["width"], v["height"], v["landscape"], v["after"]) == (300, 400, True, -1)
    doc = make_doc(["a"] * 3)
    assert dt.insert_blank_page(doc, v["after"], v["size"], v["width"], v["height"], v["landscape"]) == 0

    dlg.image_radio.setChecked(True)
    dlg.accept()
    assert "imagen" in dlg.error.text()
    dlg.image_path.setText("C:/x/y.png")
    assert dlg.values()["mode"] == "image" and dlg.values()["size"] is None
    dlg.fit_page.setChecked(True)
    assert dlg.values()["size"] == "Personalizado"
    dlg.dup_radio.setChecked(True)
    dlg.copies.setValue(3)
    v = dlg.values()
    assert v["mode"] == "duplicate" and v["copies"] == 3 and not dlg.where.isEnabled()
    assert dt.duplicate_page(doc, v["page"], v["copies"]) == [2, 3, 4]


def test_stamp_dialog(app, tmp_path):
    dlg = dd.StampDialog()
    assert dlg.list.count() == len(dt.STAMPS)
    assert dlg.values() == {"kind": "preset", "name": "APROBADO", "color": None, "image": "", "opacity": 1.0,
                            "as_annotation": True}
    dlg.list.setCurrentRow(2)
    dlg.custom_color.setChecked(True)
    dlg.color.set_rgb((0, 0, 1))
    dlg.opacity.setValue(50)
    dlg.as_annotation.setChecked(False)
    v = dlg.values()
    assert v["name"] == "CONFIDENCIAL" and v["color"] == (0.0, 0.0, 1.0) and v["opacity"] == 0.5 and not v["as_annotation"]
    doc = make_doc(["a"])
    dt.add_preset_stamp(doc, 0, fitz.Rect(100, 100, 300, 160), v["name"], color=v["color"],
                        as_annotation=v["as_annotation"], opacity=v["opacity"])
    dlg.use_image.setChecked(True)
    assert not dlg.list.isEnabled()
    dlg.accept()
    assert "imagen" in dlg.error.text()
    dlg.image_path.setText(str(tmp_path / "f.png"))
    v = dlg.values()
    assert v["kind"] == "image" and v["image"].endswith("f.png") and v["color"] is None


def test_document_check_dialog(app):
    doc = make_doc(["texto", "otro"])
    scan = doc.new_page()
    buf = io.BytesIO()
    Image.new("RGB", (50, 50), (120, 20, 20)).save(buf, "JPEG")
    scan.insert_image(scan.rect, stream=buf.getvalue())
    report = dt.check_document(doc)
    dlg = dd.DocumentCheckDialog(report)
    assert dlg.tree.topLevelItemCount() == len(report["findings"])
    first = dlg.tree.topLevelItem(0)
    assert first.text(0) == "Error" and "OCR" in first.text(1)
    assert "3 páginas" in dlg.headline.text() and "1 errores" in dlg.counts.text()
    got = []
    dlg.findingActivated.connect(got.append)
    dlg._activated(first, 0)
    assert got and got[0]["page"] == 2
    assert dlg.fonts.count() >= 1 and dlg.values() == {}
