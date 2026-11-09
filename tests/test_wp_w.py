"""Acciones guiadas: un paso solo pasa a hecho si su herramienta terminó el trabajo; menú Medir."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from pdf_editor import guided
from pdf_editor.app import EditorWindow
from pdf_editor.guided import CURRENT, DONE, PENDING


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path):
    w = EditorWindow(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
    w.engine.new()
    w.engine.doc.new_page()
    w.engine.dirty = True
    w.refresh()
    yield w
    w.engine.dirty = False
    w.close()
    app.processEvents()


def test_cancelled_step_stays_pending(window, monkeypatch):
    notices = []
    monkeypatch.setattr(guided, "notify", lambda w, text, **k: notices.append(text))
    monkeypatch.setattr(window, "sanitize", lambda: None)
    panel = guided.open_guided(window, "prepare")
    panel.next_button.click()
    assert panel.states == [CURRENT, PENDING, PENDING]
    assert panel.message.text() == "Paso cancelado"
    assert notices == ["Paso cancelado"]


def test_save_cancelled_vs_saved(window, monkeypatch):
    results = iter([False, True])
    monkeypatch.setattr(window, "save_copy", lambda: next(results))
    monkeypatch.setattr(window, "sanitize", lambda: window.change(lambda: window.engine.duplicate_page(0)))
    monkeypatch.setattr(window, "optimize", lambda: window.change(lambda: window.engine.duplicate_page(0)))
    panel = guided.open_guided(window, "prepare")
    panel.next_button.click()
    panel.next_button.click()
    assert panel.states == [DONE, DONE, CURRENT]
    panel.next_button.click()
    assert panel.states[2] == CURRENT and panel.message.text() == "Paso cancelado"
    panel.next_button.click()
    assert panel.states == [DONE, DONE, DONE]


def test_real_sanitize_marks_done(window):
    panel = guided.open_guided(window, "prepare")
    panel.next_button.click()
    assert panel.states[0] == DONE


def test_measure_menu_entry_activates_mode_and_help(window):
    tools = next(a.menu() for a in window.menuBar().actions() if a.text().replace("&", "") == "Herramientas")
    assert window.actions["measure"] in tools.actions()
    shortcut = window.actions["measure"].shortcut().toString()
    assert shortcut
    others = [a for key, a in window.actions.items() if key != "measure" and shortcut in [s.toString() for s in a.shortcuts()]]
    assert not others
    window.actions["measure"].trigger()
    assert window.view.mode == "measure"
    assert "medir" in window.statusBar().currentMessage().lower()
    assert window.mode_buttons["measure"].isChecked()
