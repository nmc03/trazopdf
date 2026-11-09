"""User text journeys driven through the real widget (offscreen QTest)."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import pymupdf as fitz
from PySide6.QtCore import Qt, QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QInputDialog, QFileDialog

from pdf_editor.app import EditorWindow

APP = QApplication.instance() or QApplication([])
LEFT, NOMOD, CTRL = Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.ControlModifier


class TextJourneys(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.folder.name)
        self.w = EditorWindow(QSettings(str(self.root / "ui.ini"), QSettings.Format.IniFormat))
        self.patches = [
            patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Ok),
            patch.object(QInputDialog, "getMultiLineText", side_effect=AssertionError("modal text entry used")),
        ]
        self.warning = self.patches[0].start()
        self.patches[1].start()
        self.w.show()
        self.w.new_file()
        APP.processEvents()

    def tearDown(self):
        self.w.view.cancel_editor()
        self.w.engine.dirty = False
        self.w.close()
        APP.processEvents()
        for p in self.patches:
            p.stop()
        self.folder.cleanup()

    def pt(self, x, y):
        return self.w.view.mapFromScene(self.w.view.scene_point(fitz.Point(x, y)))

    def mouse(self, kind, x, y):
        getattr(QTest, kind)(self.w.view.viewport(), LEFT, NOMOD, self.pt(x, y))

    def drag(self, a, b):
        self.mouse("mousePress", *a)
        QTest.mouseMove(self.w.view.viewport(), self.pt(*b))
        self.mouse("mouseRelease", *b)
        APP.processEvents()

    def type_apply(self, text):
        QTest.keyClicks(self.w.view.viewport(), text)
        QTest.keyClick(self.w.view.viewport(), Qt.Key.Key_Return, CTRL)
        APP.processEvents()
        self.warning.assert_not_called()
        self.assertIsNone(self.w.view.editor)

    def save_reopen(self, name):
        path = self.root / name
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(path), "PDF")):
            self.assertTrue(self.w.save(True))
        return fitz.open(path)

    def test_add_text_type_inline_save_and_reopen(self):
        self.w.set_mode("text")
        self.mouse("mouseClick", 100, 100)
        self.assertIsNotNone(self.w.view.editor)
        self.type_apply("Typed on page")
        with self.save_reopen("added.pdf") as saved:
            self.assertIn("Typed on page", saved[0].get_text())
            self.assertFalse(self.w.engine.dirty)

    def test_move_added_text_persists_with_undo_redo(self):
        self.w.set_mode("text")
        self.mouse("mouseClick", 100, 100)
        self.type_apply("Moved text")
        before = self.w.engine.doc[0].search_for("Moved text")[0]
        self.assertEqual(self.w.view.mode, "edit")
        c = (before.tl + before.br) / 2
        self.drag((c.x, c.y), (c.x + 60, c.y + 70))
        self.warning.assert_not_called()
        after = self.w.engine.doc[0].search_for("Moved text")
        self.assertEqual(len(after), 1)
        self.assertAlmostEqual(after[0].x0 - before.x0, 60, delta=2)
        self.assertAlmostEqual(after[0].y0 - before.y0, 70, delta=2)
        self.w.undo()
        self.assertAlmostEqual(self.w.engine.doc[0].search_for("Moved text")[0].x0, before.x0, delta=1)
        self.w.redo()
        with self.save_reopen("moved.pdf") as saved:
            rect = saved[0].search_for("Moved text")[0]
            self.assertAlmostEqual(rect.x0 - before.x0, 60, delta=2)
            self.assertAlmostEqual(rect.y0 - before.y0, 70, delta=2)

    def test_text_selection_yields_characters_not_rectangle_only(self):
        self.w.engine.doc[0].insert_text((50, 100), "Hello world", fontsize=12)
        self.w.refresh()
        self.w.set_mode("select")
        chars = [c for c in self.w.view.chars if c[1] is not None]
        first, fifth = chars[0][1], chars[4][1]
        y = (first.y0 + first.y1) / 2
        self.drag((first.x0 + .1, y), (fifth.x1 - .1, y))
        self.assertEqual(self.w.view.selected_text, "Hello")
        self.assertTrue(self.w.view.selected_rects)
        fake = MagicMock()
        with patch("pdf_editor.canvas.QApplication.clipboard", return_value=fake):
            QTest.keyClick(self.w.view.viewport(), Qt.Key.Key_C, CTRL)
        fake.setText.assert_called_once_with("Hello")
        self.assertFalse(list(self.w.engine.doc[0].annots()))
        self.assertFalse(self.w.engine.dirty)

    def test_edit_original_digital_text_inline_and_save(self):
        source = self.root / "source.pdf"
        with fitz.open() as doc:
            page = doc.new_page()
            page.insert_text((60, 100), "Original heading", fontsize=14)
            page.insert_text((60, 300), "Untouched footer", fontsize=12)
            doc.save(source)
        self.w.open_path(str(source))
        APP.processEvents()
        self.w.set_mode("edit")
        self.mouse("mouseDClick", 90, 95)
        self.assertIsNotNone(self.w.view.editor)
        self.assertEqual(self.w.view.editor.toPlainText(), "Original heading")
        QTest.keyClick(self.w.view.viewport(), Qt.Key.Key_A, CTRL)
        self.type_apply("Revised heading")
        with self.save_reopen("edited.pdf") as saved:
            text = saved[0].get_text()
            self.assertIn("Revised heading", text)
            self.assertNotIn("Original heading", text)
            self.assertIn("Untouched footer", text)


if __name__ == "__main__":
    unittest.main()
