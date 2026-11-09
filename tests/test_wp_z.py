import pymupdf as fitz
import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication

from pdf_editor.engine import PDFEngine
from pdf_editor.ui_jobs import OperationCancelled


@pytest.fixture
def window(tmp_path):
    from pdf_editor.app import EditorWindow
    QApplication.instance() or QApplication([])
    w = EditorWindow(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
    w.engine.new()
    yield w
    w.engine.dirty = False
    w.close()


def picture(tmp_path, name="p.png", size=(60, 30)):
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, *size), False)
    pix.set_rect(pix.irect, (200, 30, 30))
    path = tmp_path / name
    pix.save(str(path))
    return path


def saved_copy(engine, tmp_path, name="out.pdf"):
    target = tmp_path / name
    engine.save(str(target))
    return fitz.open(str(target))


def make_pdf(path, text):
    doc = fitz.open()
    doc.new_page().insert_text((72, 100), text)
    doc.save(str(path))
    doc.close()


# 1. image opacity -------------------------------------------------------------

def test_image_opacity_is_saved_reversible_and_keeps_image_editable(tmp_path):
    e = PDFEngine()
    e.new()
    e.add_image(0, (100, 100, 220, 160), picture(tmp_path))
    assert e.image_opacity(0, 0) == 1.0
    e.set_image_opacity(0, 0, 0.4)
    assert e.image_opacity(0, 0) == pytest.approx(0.4)
    assert e.images(0)[0]["editable"]
    with saved_copy(e, tmp_path) as doc:
        pix = doc[0].get_pixmap(clip=fitz.Rect(100, 100, 220, 160), alpha=False)
        r, g, b = pix.pixel(60, 30)
        assert r > 200 and g > 120 and b > 120, "40 % rojo sobre blanco debe verse claro"
    e.set_image_opacity(0, 0, 1.0)
    assert e.image_opacity(0, 0) == 1.0
    with saved_copy(e, tmp_path, "full.pdf") as doc:
        assert doc[0].get_pixmap(clip=fitz.Rect(100, 100, 220, 160), alpha=False).pixel(60, 30) == (200, 30, 30)
    with pytest.raises(ValueError):
        e.set_image_opacity(0, 0, 0.0)
    e.close()


def test_selected_image_opacity_through_the_bar(window, tmp_path):
    window.engine.add_image(0, (100, 100, 220, 160), picture(tmp_path))
    window.refresh()
    view = window.view
    view.select_image(window.engine.images(0)[0])
    bar = view.format_bar
    assert bar.object_opacity.isVisibleTo(bar)
    bar.object_opacity.setCurrentIndex(2)
    assert window.engine.image_opacity(0, 0) == pytest.approx(0.4)
    assert view.selected_image is not None
    assert bar.object_opacity.currentIndex() == 2


# 2. stamp turn ----------------------------------------------------------------

@pytest.mark.parametrize("turn", [90, 270])
def test_turned_stamp_is_saved_standing_up(tmp_path, turn):
    e = PDFEngine()
    e.new()
    e.add_stamp(0, (100, 100, 300, 170), kind="preset", name="APROBADO", turn=turn)
    e.add_stamp(0, (100, 300, 300, 370), kind="image", image=str(picture(tmp_path)), turn=turn, as_annotation=False)
    assert e.doc[0].get_images()
    with saved_copy(e, tmp_path) as doc:
        page = doc[0]
        stamps = [a for a in page.annots() if a.type[1] == "Stamp"]
        assert len(stamps) == 1
        assert stamps[0].rect.height > stamps[0].rect.width
        assert stamps[0].info["content"] == "APROBADO"
    e.close()


def test_unturned_stamp_stays_wide_and_bad_turn_is_refused():
    e = PDFEngine()
    e.new()
    xref = e.add_stamp(0, (100, 100, 300, 170), kind="preset", name="APROBADO")
    rect = [a for a in e.annotations(0) if a["xref"] == xref][0]["rect"]
    assert rect.width > rect.height
    with pytest.raises(ValueError):
        e.add_stamp(0, (100, 100, 300, 170), kind="preset", name="APROBADO", turn=45)
    e.close()


def test_stamp_turn_reaches_the_placed_stamp(window):
    window.begin_stamp({"kind": "preset", "name": "BORRADOR", "color": None, "image": "", "opacity": 1.0, "as_annotation": True, "turn": 90})
    window.place_stamp(fitz.Point(300, 300), None)
    stamps = [a for a in window.engine.annotations(0) if a["type"] == "Stamp"]
    assert stamps and stamps[0]["rect"].height > stamps[0]["rect"].width


# 3. batch cancel --------------------------------------------------------------

def test_cancelled_batch_leaves_no_outputs_and_reports_progress(window, tmp_path, monkeypatch):
    from pdf_editor import batch
    from pdf_editor.batch_dialog import BatchDialog
    sources = []
    for name in ("a", "b", "c"):
        make_pdf(tmp_path / f"{name}.pdf", name)
        sources.append(str(tmp_path / f"{name}.pdf"))
    out = tmp_path / "out"
    dialog = BatchDialog(window, recipes_folder=tmp_path / "recetas")
    dialog.add_inputs(sources)
    dialog.output.setText(str(out))
    dialog.steps = [batch.new_step("export_text")]
    original = PDFEngine.export_text
    calls = {"n": 0}

    def flaky(self, path, **kw):
        calls["n"] += 1
        if calls["n"] == 2:
            dialog.cancel()
        return original(self, path, **kw)

    monkeypatch.setattr(PDFEngine, "export_text", flaky)
    dialog.start()
    dialog.thread.wait(30000)
    QApplication.processEvents()
    assert calls["n"] == 2, "no debe seguir con el tercer archivo"
    assert sorted(p.name for p in out.iterdir()) == ["a_texto.txt", "batch-report.json"]
    assert dialog.report.cancelled and dialog.report.ok == 1
    assert "Cancelado" in dialog.summary.text() or "cancelando" in dialog.summary.text().lower() or dialog.report.pending == 1
    dialog.close()
    dialog.deleteLater()
    from PySide6.QtCore import QEvent
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


# 4. measure scale per document ------------------------------------------------

def test_measure_scale_is_remembered_per_document(window, tmp_path):
    first, second = tmp_path / "uno.pdf", tmp_path / "dos.pdf"
    make_pdf(first, "uno")
    make_pdf(second, "dos")
    measure = window.view.measure
    window.open_path(str(first))
    measure.set_scale(2.5, "cm")
    window.open_path(str(second))
    assert measure.scale() == (2.5, "cm"), "sin escala propia, usa la última"
    measure.set_scale(4.0, "pulg")
    window.open_path(str(first))
    assert measure.scale() == (2.5, "cm")
    window.open_path(str(second))
    assert measure.scale() == (4.0, "pulg")
    assert window.settings.value("measure/unit") == "pulg"


# 5. unavailable recents -------------------------------------------------------

def test_missing_recents_are_marked_and_removable_in_menu_and_welcome(window, tmp_path):
    alive = tmp_path / "vivo.pdf"
    make_pdf(alive, "x")
    gone = tmp_path / "perdido.pdf"
    window.settings.setValue("recent", [str(alive), str(gone)])
    window.fill_recents()
    window.fill_recent_menu()
    submenus = [a for a in window.recent_submenu.actions() if a.menu() is not None]
    assert len(submenus) == 1 and "No disponible" in submenus[0].text()
    remove = submenus[0].menu().actions()[0]
    assert remove.text() == "Quitar de recientes"
    item = window.recents.item(1)
    assert "No disponible" in item.text() and item.flags() & Qt.ItemFlag.ItemIsEnabled
    remove.trigger()
    assert window.settings.value("recent", [], type=list) == [str(alive)]
    assert window.recents.count() == 1


# 6. replace-mode help ---------------------------------------------------------

def test_replace_mode_help_matches_the_text_tool(window):
    window.view.mode = "replace"
    text = window.mode_help()
    assert "añadir texto" in text and "directamente" not in text
