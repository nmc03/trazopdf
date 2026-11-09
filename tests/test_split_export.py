"""Dividir con opciones, Exportar como y exportar imágenes con ppp, rango y formato."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf as fitz
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMenu

from pdf_editor import doctools_dialogs as dd, ui_pages
from pdf_editor.app import EditorWindow, STYLE
from pdf_editor.engine import PDFEngine
from pdf_editor.toast import banner_for


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    a.setStyleSheet(STYLE)
    return a


@pytest.fixture
def window(app, tmp_path):
    w = EditorWindow(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
    w.engine.new()
    for index in range(4):
        page = w.engine.doc[0] if index == 0 else w.engine.doc.new_page()
        page.insert_text((72, 100), f"Pagina {index + 1}", fontsize=12)
    w.refresh()
    yield w
    w.engine.dirty = False
    w.close()
    app.processEvents()


def make_pdf(path, pages, toc=None):
    doc = fitz.open()
    for index in range(pages):
        doc.new_page().insert_text((72, 100), f"Pagina {index + 1}", fontsize=12)
    if toc:
        doc.set_toc(toc)
    doc.save(str(path))
    doc.close()
    return path


def open_engine(tmp_path, pages, toc=None):
    engine = PDFEngine()
    engine.open(str(make_pdf(tmp_path / "origen.pdf", pages, toc)))
    return engine


def page_counts(paths):
    counts = []
    for path in paths:
        with fitz.open(path) as doc:
            counts.append(doc.page_count)
    return counts


def banner_labels(window):
    banner = banner_for(window)
    if banner.isHidden():
        return []
    return [banner.action_layout.itemAt(i).widget().text() for i in range(banner.action_layout.count()) if banner.action_layout.itemAt(i).widget()]


# ------------------------------------------------------------------ split_by

def test_split_each_page_gives_one_file_per_page(tmp_path):
    engine = open_engine(tmp_path, 4)
    paths = engine.split_by(str(tmp_path / "out"), "each")
    assert [os.path.basename(p) for p in paths] == [f"pagina-{n:04d}.pdf" for n in range(1, 5)]
    assert page_counts(paths) == [1, 1, 1, 1]


def test_split_every_n_pages_keeps_the_remainder(tmp_path):
    engine = open_engine(tmp_path, 5)
    paths = engine.split_by(str(tmp_path / "out"), "every", pages_per_file=2)
    assert page_counts(paths) == [2, 2, 1]
    assert os.path.basename(paths[0]) == "pagina-0001-0002.pdf"
    assert os.path.basename(paths[-1]) == "pagina-0005-0005.pdf"


def test_split_ranges_follow_the_example_syntax(tmp_path):
    engine = open_engine(tmp_path, 8)
    paths = engine.split_by(str(tmp_path / "out"), "ranges", ranges="1-3, 4-8")
    assert page_counts(paths) == [3, 5]


def test_split_ranges_reject_pages_outside_the_document(tmp_path):
    engine = open_engine(tmp_path, 3)
    with pytest.raises(ValueError, match="fuera del documento"):
        engine.split_by(str(tmp_path / "out"), "ranges", ranges="2-9")
    with pytest.raises(ValueError, match="al menos un rango"):
        engine.split_by(str(tmp_path / "out"), "ranges", ranges=" , ")


def test_split_by_bookmarks_uses_level_one_only(tmp_path):
    toc = [[1, "Capitulo A", 1], [2, "Apartado", 2], [1, "Capitulo B", 3]]
    engine = open_engine(tmp_path, 5, toc)
    paths = engine.split_by(str(tmp_path / "out"), "bookmarks")
    assert page_counts(paths) == [2, 3]
    assert "Capitulo A" in os.path.basename(paths[0]) and "Capitulo B" in os.path.basename(paths[1])


def test_split_by_bookmarks_keeps_pages_before_the_first_mark(tmp_path):
    toc = [[1, "Desde la 3", 3]]
    engine = open_engine(tmp_path, 4, toc)
    paths = engine.split_by(str(tmp_path / "out"), "bookmarks")
    assert page_counts(paths) == [2, 2]
    assert "inicio" in os.path.basename(paths[0])


def test_split_by_bookmarks_without_marks_explains_it(tmp_path):
    engine = open_engine(tmp_path, 3)
    with pytest.raises(ValueError, match="no tiene marcadores de nivel 1"):
        engine.split_by(str(tmp_path / "out"), "bookmarks")
    assert not (tmp_path / "out").exists() or not list((tmp_path / "out").iterdir())


def test_split_by_sanitizes_prefix_and_refuses_existing_names(tmp_path):
    engine = open_engine(tmp_path, 2)
    paths = engine.split_by(str(tmp_path / "out"), "each", prefix='caso: 1/2?')
    assert os.path.basename(paths[0]) == "caso 12-0001.pdf"
    with pytest.raises(ValueError, match="ya contiene archivos"):
        engine.split_by(str(tmp_path / "out"), "each", prefix='caso: 1/2?')


def test_split_by_unknown_mode_is_refused(tmp_path):
    engine = open_engine(tmp_path, 2)
    with pytest.raises(ValueError, match="no válida"):
        engine.split_by(str(tmp_path / "out"), "otra")


def test_original_split_still_writes_one_file_per_page(tmp_path):
    engine = open_engine(tmp_path, 2)
    assert page_counts(engine.split(str(tmp_path / "viejo"))) == [1, 1]


# ------------------------------------------------------------ export_images

def test_export_images_respects_dpi(tmp_path):
    engine = open_engine(tmp_path, 1)
    low = engine.export_images(str(tmp_path / "bajo"), 72)
    high = engine.export_images(str(tmp_path / "alto"), 300)
    assert fitz.Pixmap(high[0]).width > 3 * fitz.Pixmap(low[0]).width


def test_export_images_writes_only_the_chosen_pages(tmp_path):
    engine = open_engine(tmp_path, 3)
    written = engine.export_images(str(tmp_path / "img"), 72, pages=[0, 2])
    assert [os.path.basename(p) for p in written] == ["pagina-0001.png", "pagina-0003.png"]


def test_export_images_jpeg_with_quality(tmp_path):
    engine = open_engine(tmp_path, 1)
    written = engine.export_images(str(tmp_path / "jpg"), 72, fmt="jpeg", quality=50)
    assert written[0].endswith(".jpg")
    with open(written[0], "rb") as handle:
        assert handle.read(2) == b"\xff\xd8"


def test_export_images_rejects_unknown_format_and_pages(tmp_path):
    engine = open_engine(tmp_path, 2)
    with pytest.raises(ValueError, match="Formato"):
        engine.export_images(str(tmp_path / "x"), 72, fmt="gif")
    with pytest.raises(ValueError):
        engine.export_images(str(tmp_path / "y"), 72, pages=[5])


# ------------------------------------------------------------------ menus

def test_archivo_has_exportar_como_submenu(window):
    menus = {a.text(): a.menu() for a in window.menuBar().actions()}
    export = next(a.menu() for a in menus["Archivo"].actions() if a.text() == "Exportar como")
    labels = [a.text() for a in export.actions()]
    assert labels == ["Texto (.txt)", "Word (.docx)", "Excel (.xlsx)", "PowerPoint (.pptx)", "Imágenes…"]
    assert all(window.actions[key] in export.actions() for key in ("export_text", "export_docx", "export_xlsx", "export_pptx", "export_images"))


def test_rail_export_button_offers_the_same_choices(window):
    menu = window.export_menu()
    assert isinstance(menu, QMenu)
    assert [act.text() for act in menu.actions()] == ["Texto (.txt)", "Word (.docx)", "Excel (.xlsx)", "PowerPoint (.pptx)", "Imágenes…"]


# ------------------------------------------------------------ dialogs and flows

def test_split_dialog_needs_a_folder_and_ranges(app, tmp_path):
    dialog = ui_pages.SplitDialog(5, "", None)
    dialog.buttons["ranges"].setChecked(True)
    dialog.accept()
    assert dialog.result() == 0 and not dialog.error.isHidden()
    dialog.folder.setText(str(tmp_path))
    dialog.accept()
    assert dialog.result() == 0 and "rango" in dialog.error.text()
    dialog.ranges.setText("1-3, 4-5")
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.values() == {"folder": str(tmp_path), "mode": "ranges", "pages_per_file": 2, "ranges": "1-3, 4-5", "prefix": "pagina"}


def test_split_flow_writes_files_and_offers_the_folder(window, monkeypatch, tmp_path):
    out = tmp_path / "partes"
    monkeypatch.setattr(ui_pages.SplitDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(ui_pages.SplitDialog, "values", lambda self: {"folder": str(out), "mode": "every", "pages_per_file": 3, "ranges": "", "prefix": "parte"})
    window.split()
    assert sorted(os.listdir(out)) == ["parte-0001-0003.pdf", "parte-0004-0004.pdf"]
    assert banner_labels(window) == ["Abrir carpeta"]


def test_split_flow_without_bookmarks_shows_the_message(window, monkeypatch, tmp_path):
    monkeypatch.setattr(ui_pages.SplitDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(ui_pages.SplitDialog, "values", lambda self: {"folder": str(tmp_path / "x"), "mode": "bookmarks", "pages_per_file": 1, "ranges": "", "prefix": "pagina"})
    window.run(window.split)
    assert "marcadores de nivel 1" in banner_for(window).label.text()


def test_export_images_dialog_values_and_validation(app):
    dialog = dd.ExportImagesDialog(page_count=5, current=3)
    assert dialog.values() == {"dpi": 150, "pages": None, "fmt": "png", "quality": 90}
    dialog.scope.setCurrentIndex(1)
    assert dialog.values()["pages"] == [2]
    dialog.scope.setCurrentIndex(2)
    assert dialog.validate() == "Escribe el rango de páginas, por ejemplo 1-3, 5."
    dialog.range.setText("9")
    assert "fuera del documento" in dialog.validate()
    dialog.range.setText("2-4, 5")
    assert dialog.validate() is None and dialog.values()["pages"] == [1, 2, 3, 4]
    dialog.dpi.setCurrentIndex(dialog.DPI.index(300))
    dialog.fmt.setCurrentIndex(1)
    assert dialog.quality.isEnabled() and dialog.values()["dpi"] == 300 and dialog.values()["fmt"] == "jpeg"


def test_export_images_flow_writes_chosen_pages_and_offers_folder(window, monkeypatch, tmp_path):
    out = tmp_path / "imagenes"
    monkeypatch.setattr(window, "confirm_unprotected_output", lambda what: True)
    monkeypatch.setattr(dd.ExportImagesDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(dd.ExportImagesDialog, "values", lambda self: {"dpi": 72, "pages": [1, 3], "fmt": "png", "quality": 90})
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(out))
    window.export_images()
    assert sorted(os.listdir(out)) == ["pagina-0002.png", "pagina-0004.png"]
    assert banner_labels(window) == ["Abrir carpeta"]


def test_export_images_flow_cancel_writes_nothing(window, monkeypatch, tmp_path):
    monkeypatch.setattr(window, "confirm_unprotected_output", lambda what: True)
    monkeypatch.setattr(dd.ExportImagesDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: pytest.fail("no debe preguntar carpeta"))
    window.export_images()
