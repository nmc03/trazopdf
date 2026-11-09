"""Fill and sign on the page: highlights, Tab order, quick marks, saved signatures (offscreen)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf as fitz
import pytest
from PySide6.QtCore import QEvent, QPointF, QSettings, Qt
from PySide6.QtGui import QColor, QImage, QKeyEvent
from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox

from pdf_editor import signing_ui as su
from pdf_editor.app import EditorWindow, STYLE


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    a.setStyleSheet(STYLE)
    return a


@pytest.fixture
def signatures(tmp_path, monkeypatch):
    root = tmp_path / "signatures"
    monkeypatch.setattr(su, "signature_root", lambda: root)
    return root


@pytest.fixture
def window(app, tmp_path, signatures):
    w = EditorWindow(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
    w.engine.new()
    w.engine.doc[0].insert_text((72, 60), "Contrato de prueba", fontsize=12)
    w.engine.add_field(0, (72, 150, 300, 175), "Nombre")
    w.engine.add_field(0, (72, 190, 90, 208), "Acepto", kind="checkbox")
    w.engine.add_field(0, (72, 220, 300, 245), "Pais", kind="choice")
    w.engine.dirty = True
    w.refresh()
    yield w
    w.engine.dirty = False
    w.close()
    app.processEvents()


@pytest.fixture
def blank(app, tmp_path, signatures):
    w = EditorWindow(QSettings(str(tmp_path / "blank.ini"), QSettings.Format.IniFormat))
    w.engine.new()
    w.engine.doc[0].insert_text((72, 60), "Sin campos", fontsize=12)
    w.engine.dirty = True
    w.refresh()
    yield w
    w.engine.dirty = False
    w.close()
    app.processEvents()


def press_key(view, key, text="", modifiers=Qt.KeyboardModifier.NoModifier):
    event = QKeyEvent(QEvent.Type.KeyPress, key, modifiers, text)
    view.keyPressEvent(event)
    return event


def field(window, name):
    return next(f for f in window.engine.forms() if f["name"] == name)


def test_handwriting_families_keeps_installed_names_in_order():
    assert su.handwriting_families(["Arial", "Ink Free", "Segoe Script"]) == ["Segoe Script", "Ink Free"]
    assert su.handwriting_families(["Arial"]) == []
    every = list(su.HANDWRITING_FONTS)
    assert len(su.handwriting_families(every)) == 4


def test_remove_white_background_keeps_ink_and_drops_paper(app):
    image = QImage(4, 2, QImage.Format.Format_ARGB32)
    image.fill(QColor("white"))
    image.setPixelColor(1, 0, QColor("black"))
    out = su.remove_white_background(image)
    assert out is not None
    assert (out.width(), out.height()) == (1, 1)
    assert out.pixelColor(0, 0).alpha() == 255


def test_signature_store_is_isolated_and_deletes_only_inside_its_folder(app, tmp_path, signatures):
    image = QImage(20, 10, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 255))
    path = su.save_signature(image)
    assert path.parent == signatures and path.is_file()
    assert su.list_signatures() == [path]
    outside = tmp_path / "other.png"
    outside.write_bytes(b"x")
    with pytest.raises(ValueError):
        su.delete_signature(outside)
    assert outside.exists()
    su.delete_signature(path)
    assert su.list_signatures() == []


def test_typed_signature_is_saved_from_the_dialog(app, signatures):
    dialog = su.SignatureDialog()
    dialog.tabs.setCurrentIndex(1)
    dialog.type_tab.name.setText("Ana")
    dialog.accept_signature()
    assert dialog.saved_path is not None and dialog.saved_path.parent == signatures
    assert QImage(str(dialog.saved_path)).width() > 0


def test_empty_signature_is_not_saved(app, signatures):
    dialog = su.SignatureDialog()
    dialog.accept_signature()
    assert dialog.saved_path is None
    assert su.list_signatures() == []


def test_fill_mode_highlights_fields_and_tab_walks_them(window):
    window.set_mode("fill")
    view = window.view
    fields = view.fill.fields()
    assert [f["type"] for f in fields] == ["Text", "CheckBox", "ComboBox"]
    assert len(view.fill.items) == 3
    assert "3 campos" in window.toast_banner.label.text()

    press_key(view, Qt.Key.Key_Tab)
    assert view.fill.focus == fields[0]["xref"]
    assert view.editor is not None and view.editor.field == (0, fields[0]["xref"])

    view.editor.setPlainText("Ana Pérez")
    view.editor.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier, "\r"))
    assert field(window, "Nombre")["value"] == "Ana Pérez"
    assert view.editor is None
    assert view.fill.focus == fields[1]["xref"]
    assert window.view.mode == "fill"

    press_key(view, Qt.Key.Key_Space, " ")
    assert field(window, "Acepto")["value"] not in (None, "", "Off")


def test_shift_tab_moves_backwards_and_wraps(window):
    window.set_mode("fill")
    view = window.view
    fields = view.fill.fields()
    press_key(view, Qt.Key.Key_Backtab, modifiers=Qt.KeyboardModifier.ShiftModifier)
    assert view.fill.focus == fields[-1]["xref"]


def test_f_shortcut_opens_the_fill_mode_and_marks_the_rail(window):
    window.fill_shortcut()
    assert window.view.mode == "fill"
    assert window.mode_buttons["fill"].isChecked()


def test_radio_option_toggles_on_and_off(window):
    # PyMuPDF gives every radio kid the same export value, so exclusivity inside a
    # group is only checked through the code path; here one option toggles.
    page = window.engine.doc[0]
    radio = fitz.Widget()
    radio.field_name = "Plan"
    radio.field_type = fitz.PDF_WIDGET_TYPE_RADIOBUTTON
    radio.rect = fitz.Rect(72, 260, 86, 274)
    radio.field_value = "Off"
    page.add_widget(radio)
    xref = next(w.xref for w in window.engine.doc[0].widgets() if w.field_name == "Plan")
    cleared = page.load_widget(xref)
    cleared.field_value = False
    cleared.update()
    window.engine.select_radio(0, xref)
    value = next(w.field_value for w in window.engine.doc[0].widgets() if w.xref == xref)
    assert value not in (None, "", "Off")
    window.engine.select_radio(0, xref)
    value = next(w.field_value for w in window.engine.doc[0].widgets() if w.xref == xref)
    assert value == "Off"


def test_select_radio_rejects_text_fields(window):
    name = field(window, "Nombre")
    with pytest.raises(ValueError):
        window.engine.select_radio(0, name["xref"])


def test_choice_popup_applies_the_chosen_value(window):
    view = window.view
    pais = field(window, "Pais")
    rect = fitz.Rect(pais["rect"])
    combo = su.open_choice(view, 0, pais["xref"], rect, ["Chile", "Perú"], "")
    combo.setCurrentIndex(1)
    combo.activated.emit(1)
    assert field(window, "Pais")["value"] == "Perú"


def test_quick_text_is_committed_and_keeps_the_fill_mode(blank):
    view = blank.view
    blank.set_mode("fill")
    assert not blank.view.fill.palette.isHidden()
    blank.view.fill.choose_tool("text")
    view.fill.press(view.scene_point(fitz.Point(100, 300)))
    assert view.editor is not None and view.editor.field is None
    view.editor.setPlainText("Hola mundo")
    assert view.fill.commit_editor()
    assert "Hola" in blank.engine.doc[0].get_text()
    assert blank.view.mode == "fill"


def test_check_mark_is_placed_on_click_in_a_form_free_pdf(blank):
    view = blank.view
    blank.set_mode("fill")
    # The mark is vector strokes now, so it shows up as drawings rather than glyphs.
    before = len(blank.engine.doc[0].get_drawings())
    view.fill.choose_tool("check")
    view.fill.press(view.scene_point(fitz.Point(120, 300)))
    assert len(blank.engine.doc[0].get_drawings()) == before + 1
    assert view.fill.tool == "check"


def test_signature_is_placed_by_drag_with_an_isolated_store(blank, signatures):
    view = blank.view
    image = QImage(60, 24, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 255))
    path = su.save_signature(image)
    blank.set_mode("fill")
    view.fill.set_signature(path)
    assert blank.engine.doc[0].get_images() == []
    start = view.scene_point(fitz.Point(100, 300))
    end = view.scene_point(fitz.Point(260, 360))
    assert view.fill.press(start)
    view.fill.move(end)
    view.fill.release(end)
    assert len(blank.engine.doc[0].get_images()) == 1
    assert signatures.is_dir() and path.parent == signatures


def test_signature_stays_out_of_the_pdf_until_placed(blank, signatures):
    image = QImage(30, 12, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 255))
    su.save_signature(image)
    blank.set_mode("fill")
    assert len(su.list_signatures()) == 1
    assert blank.engine.doc[0].get_images() == []


def test_selector_lists_saved_signatures_and_chooses_one(blank, signatures):
    image = QImage(30, 12, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 255))
    path = su.save_signature(image)
    blank.set_mode("fill")
    fill = blank.view.fill
    fill.set_remember(True)
    fill.open_selector()
    rows = fill.selector.findChildren(su.SignatureRow)
    assert len(rows) == 1
    fill.selector.choose(path)
    assert fill.signature == str(path) and fill.tool == "signature"
    assert blank.settings.value("signing/remembered", "", type=str) == str(path)


def test_field_list_is_not_modal_and_applies_on_accept(window):
    window.forms_dialog()
    dialog = window.field_list_dialog
    assert not dialog.isModal()
    name_box = dialog.findChildren(QLineEdit)[0]
    name_box.setText("Luis")
    dialog.accept()
    assert field(window, "Nombre")["value"] == "Luis"


def test_forms_dialog_without_fields_shows_a_banner_not_a_message_box(blank, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("no debe abrirse un QMessageBox")

    monkeypatch.setattr(QMessageBox, "information", refuse)
    blank.forms_dialog()
    assert "no tiene campos" in blank.toast_banner.label.text()
