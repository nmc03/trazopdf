"""UI wiring of the security flows and the document tools (offscreen, dialogs scripted)."""
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf as fitz
import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QInputDialog, QLabel, QMenu, QMessageBox

from pdf_editor import __version__, doctools_dialogs as dd
from pdf_editor.app import EditorWindow, STYLE, format_text_comparison, purge_stale_jobs
from pdf_editor.engine import PDFEngine

SECRET = "ZEBRA-4417"
YES = QMessageBox.StandardButton.Yes


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    a.setStyleSheet(STYLE)
    return a


@pytest.fixture
def window(app, tmp_path):
    w = EditorWindow(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
    w.engine.new()
    w.engine.doc[0].insert_text((72, 100), SECRET + " correo ana@example.com", fontsize=12)
    w.engine.doc.new_page().insert_text((72, 100), "Segunda pagina", fontsize=12)
    w.engine.dirty = True
    w.refresh()
    yield w
    w.engine.dirty = False
    w.close()
    app.processEvents()


def pick(monkeypatch, *labels, texts=None):
    """Make QMessageBox.exec click the first button whose label is in labels (in order of appearance)."""
    queue = list(labels)

    def fake_exec(box):
        if texts is not None:
            texts.append(box.text())
        wanted = queue.pop(0) if len(queue) > 1 else queue[0]
        for button in box.buttons():
            if button.text().replace("&", "") == wanted:
                box._picked = button
                return 0
        raise AssertionError(f"{wanted!r} not offered: {[b.text() for b in box.buttons()]}")

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda box: box._picked)


def script_dialog(monkeypatch, cls, **values):
    monkeypatch.setattr(cls, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(cls, "values", lambda self: dict(values))


def mark_redaction(engine):
    engine.annotate(0, (60, 80, 320, 118), "redact")


# ------------------------------------------------------------ pending redactions

def test_save_with_pending_redactions_offers_choices(window, monkeypatch, tmp_path):
    mark_redaction(window.engine)
    target = tmp_path / "out.pdf"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), "PDF"))
    texts = []
    pick(monkeypatch, "Cancelar", texts=texts)
    assert window.save(True) is False
    assert not target.exists()
    assert "1 censura sin aplicar" in texts[0] and "sigue en el archivo" in texts[0]

    pick(monkeypatch, "Guardar de todos modos")
    assert window.save(True) is True
    assert target.exists() and window.engine.pending_redactions()


def test_save_can_apply_redactions_first(window, monkeypatch, tmp_path):
    mark_redaction(window.engine)
    target = tmp_path / "out.pdf"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), "PDF"))
    pick(monkeypatch, "Aplicar censuras ahora")
    assert window.save(True) is True
    assert window.engine.pending_redactions() == []
    with fitz.open(target) as saved:
        assert SECRET not in saved[0].get_text()


def test_extract_and_export_use_the_same_gate(window, monkeypatch, tmp_path):
    mark_redaction(window.engine)
    out = tmp_path / "e.pdf"
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("1", True))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(out), "PDF"))
    pick(monkeypatch, "Cancelar")
    window.extract()
    assert not out.exists()
    pick(monkeypatch, "Continuar de todos modos")
    window.extract()
    assert out.exists()


def test_ocr_job_refuses_pending_redactions(window):
    from pdf_editor.engine import PendingRedactionsError
    mark_redaction(window.engine)
    with pytest.raises(PendingRedactionsError):
        window.external_job("ocr", "x", language="eng")


# ----------------------------------------------------------------- security

def restricted_file(tmp_path):
    e = PDFEngine()
    e.doc[0].insert_text((72, 100), "Protegido", fontsize=12)
    e.protect(tmp_path / "r.pdf", "abrir", "duena", permissions=fitz.PDF_PERM_PRINT | fitz.PDF_PERM_ACCESSIBILITY)
    e.close()
    return str(tmp_path / "r.pdf")


def answers(monkeypatch, *values, errors=None):
    """Type each value into the password dialog in turn; it is cancelled when the values run out."""
    from pdf_editor.ui_security import PasswordDialog
    queue = list(values)

    def fake_exec(dialog):
        while queue and not dialog.exhausted:
            dialog.edit.setText(queue.pop(0))
            dialog.submit()
            if dialog.password is not None:
                return QDialog.DialogCode.Accepted
            if errors is not None:
                errors.append(dialog.error.text())
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(PasswordDialog, "exec", fake_exec)


def test_open_protected_asks_password_and_offers_owner_unlock(window, monkeypatch, tmp_path):
    path = restricted_file(tmp_path)
    window.engine.dirty = False
    answers(monkeypatch, "mala", "abrir")
    texts = []
    pick(monkeypatch, "Ahora no", texts=texts)
    window.open_path(path)
    assert window.engine.is_protected and not window.engine.has_owner_rights
    assert "contraseña de propietario" in texts[0]

    answers(monkeypatch, "abrir", "duena")
    pick(monkeypatch, "Contraseña de propietario…")
    window.close_document()
    window.open_path(path)
    assert window.engine.has_owner_rights


def test_owner_unlock_wrong_password_warns(window, monkeypatch, tmp_path):
    path = restricted_file(tmp_path)
    window.engine.dirty = False
    errors = []
    answers(monkeypatch, "abrir", "nope", errors=errors)
    pick(monkeypatch, "Contraseña de propietario…", "Ahora no")
    window.open_path(path)
    assert errors and errors[0].startswith("Contraseña incorrecta")
    assert not window.engine.has_owner_rights


def test_save_owner_unknown_enter_owner_password(window, monkeypatch, tmp_path):
    path = restricted_file(tmp_path)
    window.engine.dirty = False
    answers(monkeypatch, "abrir")
    pick(monkeypatch, "Ahora no")
    window.open_path(path)
    window.engine.add_text(0, (50, 200, 300, 240), "cambio")
    window.refresh()
    answers(monkeypatch, "duena")
    pick(monkeypatch, "Introducir contraseña de propietario")
    assert window.save() is True
    with fitz.open(path) as saved:
        assert saved.needs_pass
        assert saved.authenticate("abrir") & 2
        assert not saved.permissions & fitz.PDF_PERM_MODIFY


def test_save_owner_unknown_plain_copy(window, monkeypatch, tmp_path):
    path = restricted_file(tmp_path)
    original = open(path, "rb").read()
    window.engine.dirty = False
    answers(monkeypatch, "abrir")
    pick(monkeypatch, "Ahora no")
    window.open_path(path)
    window.engine.add_text(0, (50, 200, 300, 240), "cambio")
    window.refresh()
    copy = tmp_path / "copia.pdf"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(copy), "PDF"))
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a[2]) or YES)
    pick(monkeypatch, "Guardar copia sin protección")
    assert window.save() is True
    assert "no tendrá contraseña ni restricciones" in warned[0]
    with fitz.open(copy) as saved:
        assert not saved.needs_pass and not saved.is_encrypted
    assert open(path, "rb").read() == original


def test_save_owner_unknown_cancel(window, monkeypatch, tmp_path):
    path = restricted_file(tmp_path)
    window.engine.dirty = False
    answers(monkeypatch, "abrir")
    pick(monkeypatch, "Ahora no")
    window.open_path(path)
    window.engine.add_text(0, (50, 200, 300, 240), "cambio")
    pick(monkeypatch, "Cancelar")
    assert window.save() is False
    assert window.engine.dirty


def test_protect_shows_generated_owner_password_once(window, monkeypatch, tmp_path):
    target = tmp_path / "p.pdf"
    script_dialog(monkeypatch, dd.ProtectDialog, password="clave1", owner="", restrict=False)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), "PDF"))
    texts = []
    pick(monkeypatch, "Copiar", texts=texts)
    assert window.protect() is True
    assert "Contraseña de propietario generada: " in texts[0] and "no se volverá a mostrar" in texts[0]
    generated = texts[0].split("generada: ")[1].splitlines()[0]
    assert QApplication.clipboard().text() == generated
    with fitz.open(target) as saved:
        assert saved.authenticate(generated) & 4


def test_protect_with_explicit_owner_shows_nothing(window, monkeypatch, tmp_path):
    script_dialog(monkeypatch, dd.ProtectDialog, password="clave1", owner="otra", restrict=False)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(tmp_path / "p.pdf"), "PDF"))
    pick(monkeypatch, "no-debe-aparecer")
    assert window.protect() is True


def test_unprotect_confirms_when_restricted(window, monkeypatch, tmp_path):
    path = restricted_file(tmp_path)
    window.engine.dirty = False
    answers(monkeypatch, "abrir", "duena")
    pick(monkeypatch, "Contraseña de propietario…")
    window.open_path(path)
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append(a[2]) or YES)
    out = tmp_path / "libre.pdf"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(out), "PDF"))
    window.unprotect()
    assert "restricciones" in asked[0]
    with fitz.open(out) as saved:
        assert not saved.is_encrypted


def test_protected_output_warns_and_can_cancel(window, monkeypatch, tmp_path):
    path = restricted_file(tmp_path)
    window.engine.dirty = False
    answers(monkeypatch, "abrir")
    pick(monkeypatch, "Ahora no")
    window.open_path(path)
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append(a[2]) or QMessageBox.StandardButton.No)
    saved = []
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: saved.append(1) or ("x", ""))
    window.export_as("export_text")
    assert "no tendrá contraseña" in asked[0] and not saved


def test_comment_removal_is_undoable(window, monkeypatch):
    window.engine.annotate(0, (50, 50, 80, 80), "note", "hola")
    page = window.engine.doc[0]
    annot = next(iter(page.annots()))
    window.engine.delete_annotation(0, annot.xref)
    assert not annot_rects(window)
    window.engine.undo()
    assert len(annot_rects(window)) == 1


def test_apply_redactions_confirmation_mentions_side_effects(window, monkeypatch):
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append(a[2]) or QMessageBox.StandardButton.No)
    window.apply_redactions()
    assert all(word in asked[0] for word in ("enlaces", "campos de formulario", "anotaciones", "metadatos"))


def test_purge_stale_jobs(tmp_path):
    old = tmp_path / "pdf-editor-job-old"
    new = tmp_path / "pdf-editor-job-new"
    other = tmp_path / "unrelated"
    for folder in (old, new, other):
        folder.mkdir()
        (folder / "x").write_text("1")
    stamp = time.time() - 3 * 86400
    os.utime(old, (stamp, stamp))
    os.utime(other, (stamp, stamp))
    assert purge_stale_jobs(tmp_path) == 1
    assert not old.exists() and new.exists() and other.exists()


# --------------------------------------------------------------------- tools

def undo_restores(window, before):
    window.undo()
    assert window.engine.doc.page_count == before[0]
    assert window.engine.text(0) == before[1]


def snapshot(window):
    return window.engine.doc.page_count, window.engine.text(0)


def test_header_footer(window, monkeypatch):
    before = snapshot(window)
    script_dialog(monkeypatch, dd.HeaderFooterDialog, header=("INFORME", "", ""), footer=("", "{page}/{pages}", ""),
                  fontsize=10, color=(0, 0, 0), margin_top=36, margin_bottom=36, margin_side=36, pages=None, filename="")
    window.header_footer()
    assert "INFORME" in window.engine.text(0) and "2/2" in window.engine.text(1)
    undo_restores(window, before)
    assert "INFORME" not in window.engine.text(0)


def test_bates(window, monkeypatch):
    before = snapshot(window)
    script_dialog(monkeypatch, dd.BatesDialog, prefix="CASO-", suffix="", start=7, digits=4, position="bottom-right",
                  fontsize=10, color=(0, 0, 0), margin=36, pages=None)
    window.bates()
    assert "CASO-0007" in window.engine.text(0) and "CASO-0008" in window.engine.text(1)
    undo_restores(window, before)


def test_redact_search_then_apply(window, monkeypatch):
    matches = window.engine.find_sensitive(custom=SECRET)
    assert matches
    script_dialog(monkeypatch, dd.RedactSearchDialog, matches=matches, fill=(0, 0, 0))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: YES)
    window.redact_search()
    assert SECRET not in window.engine.text(0) and window.engine.pending_redactions() == []
    window.undo()
    assert SECRET in window.engine.text(0) and window.engine.pending_redactions()
    window.undo()
    assert SECRET in window.engine.text(0) and not window.engine.pending_redactions()


def test_redact_search_keep_marks(window, monkeypatch):
    matches = window.engine.find_sensitive(custom=SECRET)
    script_dialog(monkeypatch, dd.RedactSearchDialog, matches=matches, fill=(0, 0, 0))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    window.redact_search()
    assert SECRET in window.engine.text(0) and window.engine.pending_redactions()


def test_optimize_runs_in_worker_and_undoes(window, monkeypatch):
    for i in range(30):
        window.engine.doc[0].insert_text((72, 150 + i * 12), "relleno " * 10, fontsize=8)
    window.engine.doc.set_metadata({"title": "Titulo"})
    before = snapshot(window)
    script_dialog(monkeypatch, dd.OptimizeDialog, dpi=None, jpeg_quality=75, remove_metadata=True, remove_unused=True)
    window.optimize()
    assert not window.engine.doc.metadata.get("title")
    assert window.engine.page_count == before[0] and window.engine.text(0) == before[1]
    window.undo()
    assert window.engine.doc.metadata.get("title") == "Titulo"


def test_flatten(window, monkeypatch):
    window.engine.annotate(0, (50, 200, 150, 230), "rectangle")
    before = snapshot(window)
    assert len(annot_rects(window)) == 1
    script_dialog(monkeypatch, dd.FlattenDialog, annotations=True, forms=True)
    window.flatten()
    assert not annot_rects(window)
    window.undo()
    assert len(annot_rects(window)) == 1
    assert snapshot(window) == before


def test_page_labels_show_in_thumbnails(window, monkeypatch):
    script_dialog(monkeypatch, dd.PageLabelsDialog, rules=[{"start": 0, "style": "roman_lower", "prefix": "", "first": 1}])
    window.page_labels()
    assert window.engine.page_labels() == ["i", "ii"]
    assert window.thumbnails.item(1).data(Qt.ItemDataRole.UserRole) == "ii"
    window.undo()
    assert window.engine.page_labels() == ["1", "2"]


@pytest.mark.parametrize("mode", ["blank", "duplicate"])
def test_insert_page(window, monkeypatch, mode):
    script_dialog(monkeypatch, dd.InsertPageDialog, mode=mode, after=0, size="A4", width=595, height=842,
                  landscape=False, image="", copies=2, page=0)
    window.insert_page()
    assert window.engine.page_count == (3 if mode == "blank" else 4)
    assert window.page == 1
    window.undo()
    assert window.engine.page_count == 2


def test_insert_image_page(window, monkeypatch, tmp_path):
    image = tmp_path / "i.png"
    fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 30), False).save(image)
    script_dialog(monkeypatch, dd.InsertPageDialog, mode="image", after=-1, size=None, width=595, height=842,
                  landscape=False, image=str(image), copies=1, page=0)
    window.insert_page()
    assert window.engine.page_count == 3 and window.page == 0


def annot_rects(window):
    page = window.engine.doc[0]
    return [tuple(a.rect) for a in (page.annots() or [])]


def stamp_values(**extra):
    base = {"kind": "preset", "name": "APROBADO", "color": None, "image": "", "opacity": 1.0, "as_annotation": True}
    return base | extra


def test_stamp_click_places_centred_and_undoes(window, monkeypatch):
    script_dialog(monkeypatch, dd.StampDialog, **stamp_values())
    window.stamp()
    assert window.view.mode == "stamp" and window.pending_stamp
    window.perform_selection("stamp", fitz.Rect(300, 400, 300, 400), fitz.Point(300, 400), True, [])
    annots = annot_rects(window)
    assert len(annots) == 1 and abs((annots[0][0] + annots[0][2]) / 2 - 300) < 1
    assert window.view.mode == "select" and window.pending_stamp is None
    window.undo()
    assert not annot_rects(window)


def test_stamp_drag_sets_size_and_edge_click_stays_inside(window, monkeypatch):
    script_dialog(monkeypatch, dd.StampDialog, **stamp_values(name="BORRADOR"))
    window.stamp()
    window.perform_selection("stamp", fitz.Rect(100, 100, 260, 160), fitz.Point(100, 100), False, [])
    x0, y0, x1, y1 = annot_rects(window)[0]
    assert 99 <= x0 and x1 <= 261 and 99 <= y0 and y1 <= 161 and x1 - x0 > 100
    window.stamp()
    window.perform_selection("stamp", fitz.Rect(2, 2, 2, 2), fitz.Point(2, 2), True, [])
    assert all(r[0] >= 0 and r[1] >= 0 for r in annot_rects(window))


def test_stamp_mode_cancelled_by_other_tool(window, monkeypatch):
    script_dialog(monkeypatch, dd.StampDialog, **stamp_values())
    window.stamp()
    window.set_mode("select")
    assert window.pending_stamp is None


def test_check_document_shows_report_and_goes_to_page(window, monkeypatch):
    shown = []

    def fake_exec(dialog):
        shown.append(dialog.report)
        dialog.findingActivated.emit({"page": 1})
        return 0

    monkeypatch.setattr(dd.DocumentCheckDialog, "exec", fake_exec)
    window.check_document()
    assert shown and shown[0]["summary"]["pages"] == 2
    assert window.page == 1


def test_compare_text_reports_differences(window, monkeypatch, tmp_path):
    other = PDFEngine()
    other.doc[0].insert_text((72, 100), "Texto distinto", fontsize=12)
    other.save(tmp_path / "otro.pdf")
    other.close()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(tmp_path / "otro.pdf"), "PDF"))
    reports = []
    monkeypatch.setattr(window, "text_report", lambda title, text: reports.append((title, text)))
    window.compare_text()
    title, text = reports[0]
    assert title == "Comparación de texto" and "+ Texto distinto" in text and "− " + SECRET in text
    assert "No hay diferencias" in format_text_comparison(
        {"pages_a": 1, "pages_b": 1, "changed_pages": [], "total_pages": 1, "pages": [], "added": 0, "removed": 0}, "a", "b")


def test_every_tool_has_menu_rail_button_and_icon(window):
    from pdf_editor import icons
    in_menus = [a for menu in window.menuBar().findChildren(QMenu) for a in menu.actions()]
    for key in ("headerfooter", "bates", "redactsearch", "optimize", "flatten", "pagelabels", "insertpage", "stamp", "check", "comparetext"):
        assert key in window.doc_buttons and window.doc_buttons[key].isEnabled()
        assert not window.doc_buttons[key].icon().isNull()
        assert window.actions[key] in in_menus
    # Bates lives under Herramientas > Avanzado, not under Páginas.
    menus = {a.text(): a.menu() for a in window.menuBar().actions()}
    advanced = next(a.menu() for a in menus["Herramientas"].actions() if a.text() == "Avanzado")
    assert window.actions["bates"] in advanced.actions()
    assert window.actions["bates"] not in menus["Páginas"].actions()
    assert {"header-footer", "bates", "redact-search", "optimize", "flatten", "page-labels", "insert-page", "stamp",
            "check", "compare-text"} <= set(icons.names())


# --------------------------------------------------------------------- about

def test_about_lists_version_license_and_tools(window, monkeypatch):
    monkeypatch.setenv("PDFEDITOR_TESSERACT", os.path.abspath(__file__))
    monkeypatch.setenv("PDFEDITOR_SOFFICE", "no-absoluta")
    seen = []
    monkeypatch.setattr(QDialog, "exec", lambda dialog: seen.append(" ".join(l.text() for l in dialog.findChildren(QLabel))) or 0)
    window.about()
    text = seen[0]
    assert __version__ in text and "AGPL-3.0-or-later" in text
    assert "Tesseract: " in text and "LibreOffice: " in text and "no encontrado" not in text.split("Tesseract: ")[1].split("LibreOffice")[0]
    assert "PDFEDITOR_TESSERACT" in text and "PDFEDITOR_SOFFICE" in text
