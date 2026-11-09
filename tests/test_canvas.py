import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf as fitz
from PySide6.QtCore import Qt, QSettings, QPointF
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QFileDialog, QInputDialog

from pdf_editor.app import EditorWindow

APP = QApplication.instance() or QApplication([])


class CanvasWorkflows(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.folder.name)
        self.w = EditorWindow(QSettings(str(self.root / "ui.ini"), QSettings.Format.IniFormat))
        self.warning_patch = patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Ok)
        self.warning = self.warning_patch.start()
        self.dialog_patch = patch.object(QInputDialog, "getMultiLineText", side_effect=AssertionError("PDF text editing must be inline"))
        self.dialog_patch.start()
        self.w.show()
        self.w.new_file()
        APP.processEvents()

    def tearDown(self):
        self.w.view.cancel_editor()
        self.w.engine.dirty = False
        self.w.close()
        APP.processEvents()
        self.warning_patch.stop()
        self.dialog_patch.stop()
        self.folder.cleanup()

    def point(self, x, y):
        return self.w.view.mapFromScene(self.w.view.scene_point(fitz.Point(x, y)))

    def type_and_apply(self, text):
        QTest.keyClicks(self.w.view.viewport(), text)
        QTest.keyClick(self.w.view.viewport(), Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
        APP.processEvents()
        self.warning.assert_not_called()

    def test_click_type_on_page_and_undo(self):
        self.w.set_mode("text")
        QTest.mouseClick(self.w.view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, self.point(70, 80))
        self.assertIsNotNone(self.w.view.editor)
        self.type_and_apply("Written directly")
        self.assertIsNone(self.w.view.editor)
        self.assertIn("Written directly", self.w.engine.text(0))
        self.w.undo()
        self.assertNotIn("Written directly", self.w.engine.text(0))

    def test_escape_cancels_new_text_without_changing_pdf(self):
        self.w.set_mode("text")
        QTest.mouseClick(self.w.view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, self.point(70, 80))
        QTest.keyClicks(self.w.view.viewport(), "Cancel this")
        QTest.keyClick(self.w.view.viewport(), Qt.Key.Key_Escape)
        APP.processEvents()
        self.assertIsNone(self.w.view.editor)
        self.assertFalse(self.w.engine.dirty)
        self.assertFalse(self.w.engine.text(0).strip())

    def test_real_multiline_selection_copy_and_highlight(self):
        page = self.w.engine.doc[0]
        page.insert_text((50, 100), "Hello world", fontsize=12)
        page.insert_text((50, 130), "Second line", fontsize=12)
        self.w.refresh()
        self.w.set_mode("select")
        chars = [c for c in self.w.view.chars if c[1] is not None]
        start, end = chars[0][1], chars[-1][1]
        a = self.point(start.x0 + .1, (start.y0 + start.y1) / 2)
        b = self.point(end.x1 - .1, (end.y0 + end.y1) / 2)
        QTest.mousePress(self.w.view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, a)
        QTest.mouseMove(self.w.view.viewport(), b)
        QTest.mouseRelease(self.w.view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, b)
        self.assertEqual(self.w.view.selected_text, "Hello world\nSecond line")
        self.assertEqual(len(self.w.view.selected_rects), 2)
        QTest.keyClick(self.w.view.viewport(), Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(APP.clipboard().text(), "Hello world\nSecond line")
        self.w.set_mode("highlight")
        self.warning.assert_not_called()
        annotation = next(self.w.engine.doc[0].annots())
        self.assertEqual(annotation.type[0], fitz.PDF_ANNOT_HIGHLIGHT)
        self.assertEqual(len(annotation.vertices), 8)

    def test_edit_existing_pdf_inline_preserves_colour_and_saves(self):
        self.w.engine.doc[0].insert_text((50, 100), "Existing", fontsize=12, color=(1, 0, 0))
        self.w.refresh()
        self.w.set_mode("edit")
        QTest.mouseDClick(self.w.view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, self.point(70, 95))
        self.assertIsNotNone(self.w.view.editor)
        QTest.keyClick(self.w.view.viewport(), Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        self.type_and_apply("Changed existing text")
        self.assertNotIn("Existing", self.w.engine.text(0))
        self.assertIn("Changed existing text", self.w.engine.text(0))
        spans = [s for b in self.w.engine.doc[0].get_text("dict")["blocks"] for l in b.get("lines", []) for s in l["spans"]]
        self.assertEqual(spans[0]["color"], 0xFF0000)
        path = self.root / "edited.pdf"
        self.w.engine.save(path)
        with fitz.open(path) as saved:
            self.assertIn("Changed existing text", saved[0].get_text())

    def test_drag_existing_text_changes_its_position_and_undo_restores(self):
        self.w.engine.doc[0].insert_text((50, 100), "Move me", fontsize=12)
        self.w.refresh()
        before = fitz.Rect(self.w.view.runs[0].rect)
        self.w.set_mode("edit")
        centre = (before.tl + before.br) / 2
        a, b = self.point(centre.x, centre.y), self.point(centre.x + 60, centre.y + 70)
        QTest.mousePress(self.w.view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, a)
        QTest.mouseMove(self.w.view.viewport(), b)
        QTest.mouseRelease(self.w.view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, b)
        self.warning.assert_not_called()
        self.assertEqual(self.w.engine.text(0).strip(), "Move me")
        moved = self.w.view.runs[0].rect
        self.assertAlmostEqual(moved.x0 - before.x0, 60, delta=1)
        self.assertAlmostEqual(moved.y0 - before.y0, 70, delta=1)
        self.w.undo()
        self.assertAlmostEqual(self.w.view.runs[0].rect.x0, before.x0, delta=.1)

    def test_save_commits_active_inline_editor(self):
        self.w.view.begin_editor(point=fitz.Point(50, 60))
        QTest.keyClicks(self.w.view.viewport(), "Save active editor")
        path = self.root / "active.pdf"
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(path), "PDF")):
            self.assertTrue(self.w.save())
        self.warning.assert_not_called()
        with fitz.open(path) as saved:
            self.assertIn("Save active editor", saved[0].get_text())

    def test_sidebar_order_and_collapsing_pages(self):
        self.assertIs(self.w.splitter.widget(1), self.w.stack)
        self.assertIs(self.w.splitter.widget(2), self.w.pages_panel)
        self.w.toggle_pages()
        APP.processEvents()
        self.assertTrue(self.w.pages_collapsed)
        self.assertLessEqual(self.w.pages_panel.width(), 40)
        self.w.toggle_pages()
        APP.processEvents()
        self.assertFalse(self.w.pages_collapsed)
        self.assertGreater(self.w.pages_panel.width(), 100)

    def test_inline_undo_and_redo_do_not_mutate_pdf_until_applied(self):
        self.w.view.begin_editor(point=fitz.Point(50, 60))
        QTest.keyClicks(self.w.view.viewport(), "Typing")
        self.w.actions["undo"].trigger()
        self.assertEqual(self.w.view.editor.toPlainText(), "")
        self.assertFalse(self.w.engine.dirty)
        self.w.actions["redo"].trigger()
        self.assertEqual(self.w.view.editor.toPlainText(), "Typing")
        self.assertTrue(self.w.view.commit_editor())
        self.assertIn("Typing", self.w.engine.text(0))

    def test_font_change_retains_original_colour(self):
        self.w.engine.doc[0].insert_text((50, 100), "Colour", fontsize=12, color=(1, 0, 0))
        self.w.refresh()
        self.w.view.begin_editor(run=self.w.view.runs[0])
        self.w.font_size.setValue(18)
        self.w.bold.click()
        self.assertTrue(self.w.view.commit_editor())
        span = self.w.engine.doc[0].get_text("dict")["blocks"][0]["lines"][0]["spans"][0]
        self.assertEqual(span["color"], 0xFF0000)
        self.assertAlmostEqual(span["size"], 18)
        self.assertTrue(span["flags"] & 16)

    def test_form_text_field_can_be_filled_on_the_page(self):
        self.w.engine.add_field(0, (50, 80, 300, 120), "Name")
        self.w.refresh()
        self.w.set_mode("select")
        QTest.mouseClick(self.w.view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, self.point(70, 100))
        self.assertIsNotNone(self.w.view.editor)
        self.type_and_apply("Nahum")
        self.assertEqual(self.w.engine.forms()[0]["value"], "Nahum")
        self.w.undo()
        self.assertFalse(self.w.engine.forms()[0]["value"])

    def test_editing_on_rotated_page_uses_unrotated_coordinates(self):
        self.w.engine.doc[0].insert_text((200, 420), "Rotated", fontsize=12)
        self.w.engine.rotate([0], 90)
        self.w.refresh()
        self.w.fit_width()
        self.w.set_mode("edit")
        QTest.mouseDClick(self.w.view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, self.point(220, 415))
        self.assertIsNotNone(self.w.view.editor)
        QTest.keyClick(self.w.view.viewport(), Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        self.type_and_apply("Edited rotation")
        self.assertIn("Edited rotation", self.w.engine.text(0))
        self.assertEqual(self.w.engine.doc[0].rotation, 90)

    def test_invalid_inline_content_does_not_close_editor_or_save_pdf(self):
        self.w.view.begin_editor(point=fitz.Point(560, 800))
        self.w.view.editor.setPlainText("Long words " * 200)
        with patch.object(QFileDialog, "getSaveFileName") as dialog:
            self.assertFalse(self.w.save())
            dialog.assert_not_called()
        self.assertIsNotNone(self.w.view.editor)
        self.assertIn("Long words", self.w.view.editor.toPlainText())
        self.assertFalse(self.w.engine.text(0).strip())
