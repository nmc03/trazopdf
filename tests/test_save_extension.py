"""Save-as extension normalization must not overwrite an existing X.pdf silently."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf as fitz
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from pdf_editor.app import EditorWindow, STYLE

APP = QApplication.instance() or QApplication([])
APP.setStyleSheet(STYLE)
SB = QMessageBox.StandardButton
NEW = "Contenido nuevo"


class SaveExtensionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.window = EditorWindow(QSettings(str(self.root / "s.ini"), QSettings.Format.IniFormat))
        self.window.new_file()
        self.window.engine.add_text(0, (50, 50, 350, 100), NEW)
        self.window.refresh()
        self.existing = self.root / "doc.pdf"
        with fitz.open() as old:
            old.new_page().insert_text((72, 72), "Original")
            old.save(self.existing)
        self.original = self.existing.read_bytes()

    def tearDown(self):
        self.window.engine.dirty = False
        self.window.close()
        APP.processEvents()
        self.tmp.cleanup()

    def save_as(self, chosen, answer=SB.No):
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(chosen), "PDF")), \
                patch.object(QMessageBox, "question", return_value=answer) as question:
            result = self.window.save(True)
        return result, question

    def test_extensionless_existing_target_no_keeps_everything(self):
        w = self.window
        before_path = w.engine.path
        with patch.object(w.engine, "save") as engine_save:
            result, question = self.save_as(self.root / "doc", SB.No)
        self.assertFalse(result)
        question.assert_called_once()
        message = question.call_args.args[2]
        self.assertIn(str(self.root / "doc.pdf"), message)
        self.assertEqual(question.call_args.args[4], SB.No)
        engine_save.assert_not_called()
        self.assertEqual(self.existing.read_bytes(), self.original)
        self.assertTrue(w.engine.dirty)
        self.assertEqual(w.engine.path, before_path)

    def test_extensionless_existing_target_yes_saves_and_reopens(self):
        result, question = self.save_as(self.root / "doc", SB.Yes)
        self.assertTrue(result)
        question.assert_called_once()
        self.assertNotEqual(self.existing.read_bytes(), self.original)
        with fitz.open(self.existing) as saved:
            self.assertIn(NEW, saved[0].get_text())
        self.assertFalse(self.window.engine.dirty)

    def test_extensionless_new_target_has_no_prompt(self):
        result, question = self.save_as(self.root / "fresh", SB.No)
        self.assertTrue(result)
        question.assert_not_called()
        with fitz.open(self.root / "fresh.pdf") as saved:
            self.assertIn(NEW, saved[0].get_text())

    def test_uppercase_pdf_suffix_is_not_renamed_or_reprompted(self):
        target = self.root / "UPPER.PDF"
        result, question = self.save_as(target, SB.No)
        self.assertTrue(result)
        question.assert_not_called()
        self.assertTrue(target.is_file())
        self.assertFalse((self.root / "UPPER.PDF.pdf").exists())

    def test_ctrl_s_on_current_path_has_no_new_prompts(self):
        w = self.window
        result, _ = self.save_as(self.root / "cur.pdf")
        self.assertTrue(result)
        w.engine.add_text(0, (50, 150, 350, 200), "Segundo")
        w.refresh()
        with patch.object(QFileDialog, "getSaveFileName") as dialog, \
                patch.object(QMessageBox, "question") as question:
            self.assertTrue(w.save())
        dialog.assert_not_called()
        question.assert_not_called()
        with fitz.open(self.root / "cur.pdf") as saved:
            self.assertIn("Segundo", saved[0].get_text())


if __name__ == "__main__":
    unittest.main()

