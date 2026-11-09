from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymupdf as fitz
import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QMenu

from pdf_editor.app import EditorWindow
from pdf_editor.theme import STYLE


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    instance.setStyle("Fusion")
    instance.setStyleSheet(STYLE)
    return instance


@pytest.fixture()
def window(app):
    with tempfile.TemporaryDirectory(prefix="menus-welcome-", ignore_cleanup_errors=True) as folder:
        settings = QSettings(str(Path(folder) / "settings.ini"), QSettings.Format.IniFormat)
        win = EditorWindow(settings)
        win.resize(1024, 768)
        win.show()
        app.processEvents()
        yield win
        win.engine.dirty = False
        win.close()
        win.engine.close()
        app.processEvents()


def menu_named(window, title):
    return next(action.menu() for action in window.menuBar().actions() if action.text() == title)


def menu_actions(window):
    """Every action reachable from the menu bar, once each (the Ver menu and the toolbar share actions)."""
    unique = {}
    for menu in window.menuBar().findChildren(QMenu):
        for action in menu.actions():
            if not action.isSeparator() and action.menu() is None:
                unique[id(action)] = action
    return list(unique.values())


def test_every_menu_action_has_text_and_no_shortcut_clash(window):
    actions = menu_actions(window)
    assert len(actions) > 40
    owners = {}
    for action in actions:
        assert action.text().strip(), "a menu entry has no label"
        for sequence in action.shortcuts():
            text = sequence.toString()
            if text:
                assert owners.setdefault(text, action) is action, f"{text} is used twice"


def test_archivo_menu_has_recent_copy_revert_and_quit(window):
    archive = menu_named(window, "Archivo")
    labels = [action.text() for action in archive.actions() if not action.isSeparator()]
    for expected in ("Abrir…", "Abrir reciente", "Guardar", "Guardar como…", "Guardar una copia…", "Revertir", "Propiedades…", "Imprimir…", "Cerrar documento", "Salir"):
        assert expected in labels, expected
    assert window.actions["quit"].shortcut().toString() == "Ctrl+Q"
    create = next(action.menu() for action in archive.actions() if action.text() == "Crear PDF")
    assert [action.text() for action in create.actions()] == ["Crear PDF desde imágenes…", "Crear PDF desde Office…"]


def test_copy_and_revert_are_wired_to_the_document_methods(window):
    assert not window.actions["savecopy"].isEnabled()
    window.new_file()
    assert window.actions["savecopy"].isEnabled()
    assert window.actions["revert"].isEnabled()
    assert window.actions["savecopy"] in window.doc_actions


def test_recent_submenu_lists_existing_files_and_welcome_marks_missing(window, tmp_path):
    existing = tmp_path / "uno.pdf"
    existing.write_bytes(b"%PDF-1.4")
    missing = tmp_path / "perdido.pdf"
    window.settings.setValue("recent", [str(existing), str(missing)])
    window.fill_recents()
    window.fill_recent_menu()
    labels = [action.text() for action in window.recent_submenu.actions() if not action.isSeparator()]
    assert any(l.startswith("uno.pdf") for l in labels)
    assert any(l.startswith("perdido.pdf") and "No disponible" in l for l in labels)
    assert "Borrar lista" in labels
    items = [window.recents.item(index) for index in range(window.recents.count())]
    assert [item.text() for item in items] == ["uno.pdf", "perdido.pdf (No disponible)"]
    assert items[0].flags() & Qt.ItemFlag.ItemIsEnabled
    assert items[1].data(Qt.ItemDataRole.UserRole + 2) is True


def test_forget_and_clear_recent_entries(window, tmp_path):
    first = tmp_path / "a.pdf"
    second = tmp_path / "b.pdf"
    for path in (first, second):
        path.write_bytes(b"%PDF-1.4")
    window.settings.setValue("recent", [str(first), str(second)])
    window.fill_recents()
    window.forget_recent(str(first))
    assert window.settings.value("recent", [], type=list) == [str(second)]
    assert window.recents.count() == 1
    window.clear_recents()
    assert window.settings.value("recent", [], type=list) == []
    assert window.recents.count() == 0 and not window.recents.isVisibleTo(window)


def test_rail_has_the_grouped_sections_in_order(window):
    headings = [label.text() for label in window.rail.widget().findChildren(QLabel, "section")]
    assert headings == ["Leer y editar", "Comentar", "Formularios y seguridad"]
    assert "text" not in window.mode_buttons
    assert window.mode_buttons["replace"].text() == "Texto"
    assert window.mode_buttons["replace"].toolTip() == "Texto (T)"
    assert window.mode_buttons["edit"].text() == "Mover objetos"


def test_texto_tool_edits_existing_text_and_adds_on_empty_page(window, monkeypatch):
    window.new_file()
    window.engine.doc[0].insert_text((72, 100), "Texto existente", fontsize=12)
    window.refresh()
    window.render_page()
    window.set_mode("replace")
    calls = []
    monkeypatch.setattr(window.view, "begin_editor", lambda **kwargs: calls.append(kwargs))
    window.perform_selection("replace", fitz.Rect(72, 88, 220, 106), fitz.Point(80, 96), False, [])
    assert calls and "run" in calls[-1] and calls[-1]["run"] is not None
    calls.clear()
    window.perform_selection("replace", fitz.Rect(300, 300, 310, 310), fitz.Point(305, 305), True, [])
    assert calls and calls[-1].get("point") is not None and calls[-1].get("rect") is None


def test_texto_click_on_empty_page_starts_a_new_text_box(window, app):
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest
    window.new_file()
    window.set_mode("replace")
    app.processEvents()
    viewport = window.view.viewport()
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(viewport.width() // 2, viewport.height() // 2))
    app.processEvents()
    assert window.view.editor is not None


def test_text_letter_and_old_text_mode_select_the_unified_tool(window):
    window.new_file()
    window.set_mode("text")
    assert window.view.mode == "replace"
    assert window.mode_buttons["replace"].isChecked()


def test_empty_state_shows_a_hint_and_hides_tools(window, app):
    assert window.rail_empty.isVisibleTo(window)
    assert not window.mode_buttons["select"].isVisibleTo(window)
    assert window.actions["open"] is not None and window.rail_always[0].isVisibleTo(window)
    window.new_file()
    app.processEvents()
    assert not window.rail_empty.isVisibleTo(window)
    assert window.mode_buttons["select"].isVisibleTo(window)


def test_letter_shortcuts_do_not_fire_while_typing(window, app):
    window.new_file()
    window.set_mode("select")
    window.open_search()
    app.processEvents()
    window.search.setFocus()
    app.processEvents()
    QTest.keyClick(window.search, Qt.Key.Key_T)
    app.processEvents()
    assert window.search.text().lower().endswith("t")
    assert window.view.mode == "select"
    window.view.setFocus()
    app.processEvents()
    QTest.keyClick(window.view, Qt.Key.Key_T)
    app.processEvents()
    assert window.view.mode == "replace"


def test_welcome_offers_task_shortcuts(window):
    assert [button.text() for button in window.task_buttons] == ["Combinar PDFs", "Imágenes a PDF", "Convertir desde Office", "Comparar"]
    for button in window.task_buttons:
        assert button.toolTip() and button.accessibleName()


def test_compare_entry_asks_the_mode_and_runs_it(window, monkeypatch):
    calls = []
    monkeypatch.setattr(window, "compare", lambda: calls.append("visual"))
    monkeypatch.setattr(window, "compare_text", lambda: calls.append("text"))
    monkeypatch.setattr(window, "choose", lambda *args, **kwargs: "Texto")
    window.compare_documents()
    monkeypatch.setattr(window, "choose", lambda *args, **kwargs: "Apariencia (visual)")
    window.compare_documents()
    monkeypatch.setattr(window, "choose", lambda *args, **kwargs: None)
    window.compare_documents()
    assert calls == ["text", "visual"]


def test_text_tool_click_on_the_companion_page_goes_to_that_page_first(window, tmp_path):
    import fitz
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtTest import QTest

    path = tmp_path / "two.pdf"
    doc = fitz.open()
    for label in ("uno", "dos"):
        doc.new_page().insert_text((72, 100), label)
    doc.save(path)
    doc.close()
    window.open_path(str(path))
    window.view_actions["double"].trigger()
    window.set_mode("text")
    assert window.view.companion_rects, "la vista de dos páginas debe tener página acompañante"
    index, rect = window.view.companion_rects[0]
    point = window.view.mapFromScene(QPointF(rect.center().x(), rect.top() + 300))
    QTest.mouseClick(window.view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    assert window.page == index
    assert window.view.editor is None
