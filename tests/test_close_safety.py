"""Real window.close() dispatch checks: failed saves must never lose a dirty document."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf as fitz
from PySide6.QtCore import QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from pdf_editor.app import EditorWindow, STYLE

APP = QApplication.instance() or QApplication([])
APP.setStyleSheet(STYLE)
SB = QMessageBox.StandardButton
MARK = "Texto sin guardar"


class CloseSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.settings = QSettings(str(self.root / "close.ini"), QSettings.Format.IniFormat)
        self.window = EditorWindow(self.settings)
        self.window.show()
        self.window.new_file()
        self.window.engine.add_text(0, (50, 50, 350, 100), MARK)
        self.window.refresh()
        APP.processEvents()
        self.assertTrue(self.window.engine.dirty)
        self.warning_patch = patch.object(QMessageBox, "warning")
        self.warning = self.warning_patch.start()

    def tearDown(self):
        self.warning_patch.stop()
        self.window.engine.dirty = False
        self.window.close()
        APP.processEvents()
        self.tmp.cleanup()

    def assert_still_open(self):
        w = self.window
        self.assertTrue(w.isVisible())
        self.assertTrue(w.has_doc())
        self.assertTrue(w.engine.dirty)
        self.assertIn(MARK, w.engine.text(0))

    def close_with(self, answer, save_path=None):
        # The discard prompt is a choose() box with Guardar / No guardar / Cancelar.
        label = {SB.Save: "Guardar", SB.Discard: "No guardar", SB.Cancel: None}[answer]
        target = (str(save_path), "PDF") if save_path else ("", "")
        with patch.object(EditorWindow, "choose", return_value=label), \
                patch.object(QFileDialog, "getSaveFileName", return_value=target):
            return self.window.close()

    def test_save_failure_keeps_window_document_and_edits(self):
        output = self.root / "fail.pdf"
        with patch.object(self.window.engine, "save", side_effect=OSError("disco lleno")) as save:
            closed = self.close_with(SB.Save, output)
        APP.processEvents()
        self.assertFalse(closed)
        save.assert_called()
        self.assert_still_open()
        self.assertFalse(output.exists())
        self.warning.assert_called()
        self.assertIn("disco lleno", self.warning.call_args.args[2])
        self.assertEqual(self.warning.call_args.args[1], "No se pudo cerrar")

    def test_unexpected_exception_in_confirm_is_contained(self):
        with patch.object(self.window, "confirm_discard", side_effect=RuntimeError("fallo interno")):
            self.assertFalse(self.window.close())
        APP.processEvents()
        self.assert_still_open()
        self.warning.assert_called()

    def test_user_cancel_keeps_everything(self):
        self.assertFalse(self.close_with(SB.Cancel))
        self.assert_still_open()
        self.warning.assert_not_called()

    def test_save_dialog_cancel_keeps_everything(self):
        self.assertFalse(self.close_with(SB.Save, None))
        self.assert_still_open()
        self.warning.assert_not_called()

    def test_successful_save_closes_and_persists_state(self):
        output = self.root / "saved.pdf"
        self.assertTrue(self.close_with(SB.Save, output))
        APP.processEvents()
        self.assertFalse(self.window.isVisible())
        self.assertFalse(self.window.has_doc())
        self.assertTrue(output.is_file())
        self.assertIsNotNone(self.settings.value("geometry"))
        self.assertIn("pagesCollapsed", self.settings.allKeys())
        self.warning.assert_not_called()

    def test_discard_closes_without_writing(self):
        output = self.root / "never.pdf"
        self.assertTrue(self.close_with(SB.Discard, output))
        self.assertFalse(self.window.isVisible())
        self.assertFalse(self.window.has_doc())
        self.assertFalse(output.exists())

    def test_settings_failure_does_not_block_a_safe_close(self):
        with patch.object(self.settings, "setValue", side_effect=OSError("ajustes")):
            self.assertTrue(self.close_with(SB.Discard))
        self.assertFalse(self.window.isVisible())
        self.assertFalse(self.window.has_doc())


    def test_live_inline_editor_with_failing_save_loses_nothing(self):
        typed = "Editor vivo"
        view = self.window.view
        self.window.set_mode("text")
        view.begin_editor(point=fitz.Point(100, 200))
        APP.processEvents()
        self.assertIsNotNone(view.editor)
        QTest.keyClicks(view.viewport(), typed)
        APP.processEvents()
        self.assertEqual(view.editor.toPlainText(), typed)
        output = self.root / "live.pdf"
        with patch.object(self.window.engine, "save", side_effect=OSError("disco lleno")) as save:
            closed = self.close_with(SB.Save, output)
        APP.processEvents()
        self.assertFalse(closed)
        save.assert_called()
        self.assert_still_open()
        self.assertFalse(output.exists())
        # The typed text must survive either in the engine or in the still-live editor.
        in_engine = typed in self.window.engine.text(0)
        in_editor = view.editor is not None and typed in view.editor.toPlainText()
        self.assertTrue(in_engine or in_editor)
        self.warning.assert_called()
        self.assertEqual(self.warning.call_args.args[1], "No se pudo cerrar")
        self.assertIn("disco lleno", self.warning.call_args.args[2])

    def test_post_write_settings_failure_is_reported_honestly(self):
        output = self.root / "written.pdf"
        with patch.object(self.settings, "setValue", side_effect=OSError("ajustes")):
            closed = self.close_with(SB.Save, output)
        APP.processEvents()
        self.assertFalse(closed)
        self.assertTrue(output.is_file())
        with fitz.open(output) as saved:
            self.assertIn(MARK, saved[0].get_text())
        self.assertTrue(self.window.isVisible())
        self.assertTrue(self.window.has_doc())
        self.assertIn(MARK, self.window.engine.text(0))
        self.warning.assert_called()
        self.assertEqual(self.warning.call_args.args[1], "No se pudo cerrar")
        message = self.warning.call_args.args[2]
        self.assertIn("ajustes", message)
        self.assertIn("permanece abierto", message)
        self.assertNotIn("no se pudieron guardar", message.lower())


if __name__ == "__main__":
    unittest.main()

