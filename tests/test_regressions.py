"""Regressions found while exercising editing workflows beyond smoke tests."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf as fitz
from PySide6.QtCore import Qt, QSettings, QPoint
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox
from PySide6.QtTest import QTest

from pdf_editor.engine import PDFEngine
from pdf_editor.app import EditorWindow

APP = QApplication.instance() or QApplication([])


class EditingRegressions(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.folder.name)
        self.engine = PDFEngine()

    def tearDown(self):
        self.engine.close()
        self.folder.cleanup()

    def test_replace_does_not_apply_other_pending_redactions(self):
        self.engine.doc[0].insert_text((40, 80), "Original")
        self.engine.doc[0].insert_text((40, 180), "Pending secret")
        self.engine.annotate(0, (35, 155, 180, 190), "redact")
        span = self.engine.doc[0].get_text("dict")["blocks"][0]["lines"][0]["spans"][0]
        self.engine.replace_text(0, span["bbox"], "New", span["size"])
        self.assertIn("Pending secret", self.engine.text(0))
        self.assertEqual(sum(a.type[0] == fitz.PDF_ANNOT_REDACT for a in self.engine.doc[0].annots()), 1)

    def test_unicode_text_is_not_silently_replaced_by_question_marks(self):
        text = "Español: acción · Ελληνικά · Привет"
        self.engine.add_text(0, (40, 40, 550, 150), text)
        self.assertEqual(self.engine.text(0).strip(), text)

    def test_extraction_respects_explicit_page_order(self):
        self.engine.add_text(0, (40, 40, 300, 100), "First")
        self.engine.insert_blank(0)
        self.engine.add_text(1, (40, 40, 300, 100), "Second")
        output = self.root / "reordered.pdf"
        self.engine.extract([1, 0], output)
        with fitz.open(output) as saved:
            self.assertIn("Second", saved[0].get_text())
            self.assertIn("First", saved[1].get_text())

    def test_edit_text_does_not_paint_white_over_coloured_background(self):
        page = self.engine.doc[0]
        page.draw_rect((30, 30, 300, 140), color=None, fill=(.2, .4, .6))
        page.insert_text((50, 80), "Original", fontsize=12)
        span = page.get_text("dict")["blocks"][0]["lines"][0]["spans"][0]
        before = self.engine.render(0).pixel(80, 70)
        self.engine.replace_text(0, span["bbox"], "New", span["size"])
        after = self.engine.render(0).pixel(80, 70)
        self.assertEqual(after, (51, 102, 153))

    def test_form_dialog_update_is_atomic_and_undoes_as_one_action(self):
        self.engine.add_field(0, (50, 50, 250, 90), "A")
        self.engine.add_field(0, (50, 120, 250, 160), "B")
        a, b = self.engine.forms()
        self.engine.fill_forms([(0, a["xref"], "One"), (0, b["xref"], "Two")])
        self.assertEqual([f["value"] for f in self.engine.forms()], ["One", "Two"])
        self.engine.undo()
        self.assertTrue(all(not f["value"] for f in self.engine.forms()))
        with self.assertRaises(Exception):
            self.engine.fill_forms([(0, a["xref"], "Partial"), (0, 999999, "Fail")])
        self.assertTrue(all(not f["value"] for f in self.engine.forms()))


class InteractionRegressions(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.folder.name)
        self.window = EditorWindow(QSettings(str(self.root / "ui.ini"), QSettings.Format.IniFormat))
        self.warning_patch = patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Ok)
        self.warning_mock = self.warning_patch.start()
        self.window.show()
        self.window.new_file()
        APP.processEvents()

    def tearDown(self):
        self.window.engine.dirty = False
        self.window.close()
        APP.processEvents()
        self.folder.cleanup()
        self.warning_patch.stop()

    def test_ctrl_click_keeps_multiple_pages_selected_and_rotates_all(self):
        w = self.window
        w.engine.insert_blank(0)
        w.engine.insert_blank(1)
        w.refresh()
        APP.processEvents()
        a = w.thumbnails.visualItemRect(w.thumbnails.item(0)).center()
        b = w.thumbnails.visualItemRect(w.thumbnails.item(1)).center()
        QTest.mouseClick(w.thumbnails.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, a)
        QTest.mouseClick(w.thumbnails.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, b)
        self.assertEqual(w.selected_pages(), [0, 1])
        w.rotate()
        self.assertEqual([p.rotation for p in w.engine.doc], [90, 90, 0])
        self.assertEqual(w.selected_pages(), [0, 1])

    def test_search_next_after_close_does_not_use_a_closed_document(self):
        w = self.window
        w.engine.add_text(0, (40, 40, 300, 100), "Search me")
        w.search.setText("Search")
        w.find_text()
        w.engine.dirty = False
        w.close_document()
        w.next_result()
        self.assertEqual(w.search_results, [])

    def test_zoom_during_selection_cancels_transient_preview(self):
        w = self.window
        start = w.view.mapFromScene(80, 80)
        QTest.mousePress(w.view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
        self.assertIsNotNone(w.view.origin)
        w.set_zoom(120)
        self.assertIsNone(w.view.origin)
        self.assertIsNone(w.view.preview)
        QTest.mouseRelease(w.view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)

    def test_replacing_coloured_text_preserves_its_colour(self):
        w = self.window
        w.engine.doc[0].insert_text((40, 80), "Red text", color=(1, 0, 0))
        w.refresh()
        w.perform_selection("replace", fitz.Rect(), fitz.Point(60, 75), True, [])
        self.assertIsNotNone(w.view.editor)
        w.view.editor.setPlainText("New")
        self.assertTrue(w.view.commit_editor())
        spans = [s for b in w.engine.doc[0].get_text("dict")["blocks"] for line in b.get("lines", []) for s in line["spans"]]
        self.assertEqual(spans[0]["color"], 0xFF0000)
        self.assertIn("New", w.engine.text(0))
