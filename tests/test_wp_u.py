"""Acciones guiadas: panel no modal, estados de los pasos, Siguiente y Omitir, accesos de menú y bienvenida."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QDialog

from pdf_editor import guided
from pdf_editor.app import EditorWindow
from pdf_editor.guided import CURRENT, DONE, PENDING, SKIPPED, GuidedPanel


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


def test_at_least_four_actions_with_steps():
    assert len(guided.ACTIONS) >= 4
    titles = [entry[1] for entry in guided.ACTIONS]
    for expected in ("Preparar para enviar", "Combinar y numerar páginas", "Censurar información sensible", "Rellenar y firmar"):
        assert expected in titles
    assert all(len(entry[3]) >= 2 for entry in guided.ACTIONS)


def test_menu_entry_and_welcome_card_open_the_panel(window):
    assert "guided" in window.actions
    tools = next(a.menu() for a in window.menuBar().actions() if a.text().replace("&", "") == "Herramientas")
    assert window.actions["guided"] in tools.actions()
    window.actions["guided"].trigger()
    panel = window.guided_panel
    assert panel.isVisibleTo(window)
    assert window.guided_button.text() == "Acciones guiadas"
    panel.hide()
    window.guided_button.click()
    assert panel.isVisibleTo(window)


def test_panel_is_not_a_dialog(window):
    panel = guided.open_guided(window)
    assert not isinstance(panel, QDialog)
    assert panel.parent() is window


def test_steps_run_in_order_and_skip(window, monkeypatch):
    calls = []
    for name in ("sanitize", "optimize"):
        monkeypatch.setattr(window, name, lambda n=name: (calls.append(n), window.change(lambda: window.engine.duplicate_page(0))))
    monkeypatch.setattr(window, "save_copy", lambda: calls.append("save_copy") or True)
    panel = guided.open_guided(window, "prepare")
    assert panel.states == [CURRENT, PENDING, PENDING]
    panel.next_button.click()
    assert panel.states == [DONE, CURRENT, PENDING]
    panel.skip_button.click()
    assert panel.states == [DONE, SKIPPED, CURRENT]
    panel.next_button.click()
    assert calls == ["sanitize", "save_copy"]
    assert panel.finished() and not panel.next_button.isEnabled()
    assert panel.steps.count() == 3
    assert "2 de 3" in panel.hint.text()


def test_redaction_flow_chains_existing_tools(window, monkeypatch):
    calls = []
    def edit(name):
        return lambda: (calls.append(name), window.change(lambda: window.engine.duplicate_page(0)))
    monkeypatch.setattr(window, "redact_search", edit("search"))
    monkeypatch.setattr(window, "apply_redactions", edit("apply"))
    monkeypatch.setattr(window, "sanitize", edit("sanitize"))
    monkeypatch.setattr(window, "save_copy", lambda: calls.append("copy") or True)
    panel = guided.open_guided(window, "redact")
    for _ in range(5):
        panel.next_button.click()
    assert calls == ["search", "apply", "sanitize", "copy"]
    assert window.view.mode == "redact"
    assert panel.states.count(DONE) == 5


def test_failing_step_stays_current(window, monkeypatch):
    def boom():
        raise RuntimeError("fallo")
    monkeypatch.setattr(window, "number_pages", boom)
    monkeypatch.setattr(window, "merge", lambda: window.change(lambda: window.engine.duplicate_page(0)))
    from pdf_editor import ui_jobs
    monkeypatch.setattr(ui_jobs, "notify", lambda *a, **k: None)
    panel = guided.open_guided(window, "combine")
    panel.next_button.click()
    panel.next_button.click()
    assert panel.states == [DONE, CURRENT, PENDING]
    assert panel.message.text()


def test_needs_document(app, tmp_path):
    w = EditorWindow(QSettings(str(tmp_path / "e.ini"), QSettings.Format.IniFormat))
    panel = guided.open_guided(w, "sign")
    panel.next_button.click()
    assert panel.states[0] == CURRENT and "Abre un PDF" in panel.message.text()
    w.close()


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_renders_in_both_themes(window, scheme):
    window.set_theme(scheme)
    panel = guided.open_guided(window, "sign")
    panel.next_button.click()
    assert panel.steps.item(0).data(guided.STATE_ROLE) == DONE
