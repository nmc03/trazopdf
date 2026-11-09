"""Integration checks for user workflows and rotated page input coordinates."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf as fitz
from PySide6.QtCore import QPointF, Qt, QSettings
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog

from pdf_editor.app import EditorWindow, STYLE

APP = QApplication.instance() or QApplication([])
APP.setStyleSheet(STYLE)


class UIWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.root_context = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.root_context.name)
        self.window = EditorWindow(QSettings(str(self.root / "ui.ini"), QSettings.Format.IniFormat))
        self.window.show()
        APP.processEvents()

    def tearDown(self):
        self.window.engine.dirty = False
        self.window.close()
        APP.processEvents()
        self.root_context.cleanup()

    def test_welcome_create_edit_save_reopen_and_search(self):
        w = self.window
        self.assertEqual(w.stack.currentIndex(), 0)
        w.new_file()
        w.engine.add_text(0, (50, 50, 350, 100), "Workflow original")
        w.refresh()
        w.search.setText("original")
        w.find_text()
        self.assertEqual(len(w.search_results), 1)
        output = self.root / "workflow.pdf"
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(output), "PDF")):
            self.assertTrue(w.save())
        w.engine.add_text(0, (50, 150, 350, 200), "Second change")
        w.refresh()
        w.undo()
        self.assertNotIn("Second change", w.engine.text(0))
        w.redo()
        self.assertIn("Second change", w.engine.text(0))
        w.engine.dirty = False
        w.close_document()
        w.open_path(str(output))
        self.assertEqual(w.engine.page_count, 1)
        self.assertNotIn("Second change", w.engine.text(0))

    def test_selection_add_text_and_rotation_coordinates(self):
        w = self.window
        w.new_file()
        w.perform_selection("text", fitz.Rect(50, 50, 350, 120), fitz.Point(50, 50), False, [])
        w.view.editor.setPlainText("Selection inserted")
        self.assertTrue(w.view.commit_editor())
        self.assertIn("Selection inserted", w.engine.text(0))
        APP.clipboard().setText("previo")
        w.perform_selection("select", fitz.Rect(40, 40, 370, 130), fitz.Point(40, 40), False, [])
        self.assertEqual(APP.clipboard().text(), "previo")
        self.assertIn("caracteres seleccionados", w.statusBar().currentMessage())
        w.rotate()
        point = fitz.Point(120, 200)
        displayed = point * w.engine.doc[0].rotation_matrix
        recovered = w.view.pdf_point(QPointF(displayed.x * w.view.scale_factor, displayed.y * w.view.scale_factor))
        self.assertAlmostEqual(recovered.x, point.x, places=4)
        self.assertAlmostEqual(recovered.y, point.y, places=4)

    def test_new_pdf_after_close_and_image_import_requires_new_save_path(self):
        w = self.window
        w.new_file()
        output = self.root / "original.pdf"
        w.engine.save(output)
        original = output.read_bytes()
        image = self.root / "image.png"
        w.engine.render(0).save(image)
        w.close_document()
        self.assertEqual(w.stack.currentIndex(), 0)
        w.engine.from_images([image])
        w.refresh()
        self.assertIsNone(w.engine.path)
        self.assertEqual(output.read_bytes(), original)
        self.assertEqual(w.stack.currentIndex(), 1)


if __name__ == "__main__":
    unittest.main()
