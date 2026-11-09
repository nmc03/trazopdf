"""Text colour: visible control, colour reaching the PDF, and remembered between texts."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf as fitz
from PySide6.QtCore import Qt, QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from pdf_editor.app import EditorWindow

APP = QApplication.instance() or QApplication([])
LEFT, NOMOD, CTRL = Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.ControlModifier
RED = "#d93025"


def span_color(page, needle):
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", ()):
            for span in line["spans"]:
                if needle in span["text"]:
                    return "#%06x" % span["color"]
    return None


class TextColour(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.folder.name)
        self.ini = str(self.root / "ui.ini")
        self.w = self.make_window()
        self.patch = patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Ok)
        self.warning = self.patch.start()

    def make_window(self):
        w = EditorWindow(QSettings(self.ini, QSettings.Format.IniFormat))
        w.resize(1024, 768)
        w.show()
        w.new_file()
        APP.processEvents()
        return w

    def tearDown(self):
        self.patch.stop()
        self.w.view.cancel_editor()
        self.w.engine.dirty = False
        self.w.close()
        APP.processEvents()
        self.folder.cleanup()

    def click(self, x, y):
        w = self.w
        QTest.mouseClick(w.view.viewport(), LEFT, NOMOD, w.view.mapFromScene(w.view.scene_point(fitz.Point(x, y))))
        APP.processEvents()

    def write(self, text):
        QTest.keyClicks(self.w.view.viewport(), text)
        QTest.keyClick(self.w.view.viewport(), Qt.Key.Key_Return, CTRL)
        APP.processEvents()

    def add(self, x, y, text, page=0):
        if page != self.w.page:
            self.w.go_to_page(page) if hasattr(self.w, "go_to_page") else setattr(self.w, "page", page)
        self.w.set_mode("text")
        self.click(x, y)
        self.write(text)

    # 1. visible control
    def test_bar_shows_colour_control_with_tool_active(self):
        for mode in ("light", "dark"):
            self.w.set_theme(mode)
            self.w.set_mode("text")
            APP.processEvents()
            bar = self.w.view.format_bar
            self.assertTrue(bar.isVisible())
            button = bar.color_button
            self.assertTrue(button.isVisible())
            self.assertGreaterEqual(button.width(), 20)
            self.assertTrue(bar.rect().contains(button.geometry()))
            self.assertTrue(self.w.view.viewport().rect().contains(bar.geometry()))
            self.w.set_mode("select")

    def test_bar_swatch_follows_pick_without_editor(self):
        self.w.set_mode("text")
        self.w.view.format_action("color", RED)
        APP.processEvents()
        self.assertEqual(self.w.view.format_bar.color_button.property("swatch"), RED)

    def test_bar_swatch_shows_colour_on_existing_text_click(self):
        self.w.engine.doc[0].insert_text((50, 100), "Existing", fontsize=12, color=(1, 0, 0))
        self.w.refresh()
        self.w.set_mode("replace")
        self.click(60, 96)
        self.assertIsNotNone(self.w.view.editor)
        self.assertEqual(self.w.view.format_bar.color_button.property("swatch").lower(), "#ff0000")

    # 2. colour reaches the PDF
    def test_colour_before_typing_reaches_pdf(self):
        self.w.set_mode("text")
        self.w.view.format_action("color", RED)
        self.click(100, 100)
        self.write("Red text")
        self.assertEqual(span_color(self.w.engine.doc[0], "Red text"), RED)

    def test_colour_while_editing_reaches_pdf(self):
        self.w.set_mode("text")
        self.click(100, 100)
        QTest.keyClicks(self.w.view.viewport(), "Mid colour")
        self.w.view.format_action("color", RED)
        QTest.keyClick(self.w.view.viewport(), Qt.Key.Key_Return, CTRL)
        APP.processEvents()
        self.assertEqual(span_color(self.w.engine.doc[0], "Mid colour"), RED)

    def second_page(self, layout=None):
        self.w.engine.doc.new_page(width=612, height=792)
        self.w.refresh()
        if layout:
            self.w.set_view_layout(layout)
            APP.processEvents()
        self.w.goto(1)
        APP.processEvents()
        self.assertEqual(self.w.page, 1)

    def check_second_page(self):
        self.w.set_mode("text")
        self.w.view.format_action("color", RED)
        self.click(100, 100)
        self.write("Page two")
        self.assertEqual(span_color(self.w.engine.doc[1], "Page two"), RED)
        self.w.undo()
        self.assertIsNone(span_color(self.w.engine.doc[1], "Page two"))
        self.w.redo()
        self.assertEqual(span_color(self.w.engine.doc[1], "Page two"), RED)

    def test_colour_on_second_page_and_undo_redo(self):
        self.second_page()
        self.check_second_page()

    def test_colour_on_second_page_continuous_layout(self):
        self.second_page("continuous")
        self.check_second_page()

    def test_colour_on_second_page_double_layout(self):
        self.second_page("double")
        self.check_second_page()

    def test_text_box_colour_change_applies_and_is_shown(self):
        xref = self.w.engine.add_freetext(0, fitz.Rect(50, 50, 200, 90), "Box", color=(0, 0, 0))
        self.w.refresh()
        info = next(a for a in self.w.engine.annotations(0) if a["xref"] == xref)
        self.w.view.select_annotation(info)
        self.w.view.format_action("color", RED)
        APP.processEvents()
        self.warning.assert_not_called()
        self.assertEqual(span_color(self.w.engine.doc[0], "Box"), RED)
        shown = next(a for a in self.w.engine.annotations(0) if a["xref"] == xref)
        self.assertEqual(self.w.view.format_values("note")["color"], RED)
        self.assertEqual(tuple(round(v, 2) for v in shown["stroke"]), (0.85, 0.19, 0.15))
        self.w.undo()
        self.assertEqual(span_color(self.w.engine.doc[0], "Box"), "#000000")

    def test_text_box_tool_uses_last_colour(self):
        self.w.set_mode("freetext")
        self.w.view.format_action("color", RED)
        self.w.set_mode("select")
        self.w.set_mode("freetext")
        self.assertEqual(self.w.view.format_bar.shape_color.property("swatch") if False else self.w.view.format_values("note")["color"], RED)

    def test_existing_text_keeps_colour_when_edited(self):
        self.w.engine.doc[0].insert_text((50, 100), "Existing", fontsize=12, color=(0, 0.5, 0))
        self.w.refresh()
        before = span_color(self.w.engine.doc[0], "Existing")
        self.w.set_mode("replace")
        self.click(60, 96)
        QTest.keyClicks(self.w.view.viewport(), " more")
        QTest.keyClick(self.w.view.viewport(), Qt.Key.Key_Return, CTRL)
        APP.processEvents()
        self.assertEqual(span_color(self.w.engine.doc[0], "Existing more"), before)

    def test_saved_file_keeps_colour(self):
        self.w.set_mode("text")
        self.w.view.format_action("color", RED)
        self.click(100, 100)
        self.write("Saved red")
        data = self.w.engine.doc.tobytes()
        with fitz.open("pdf", data) as saved:
            self.assertEqual(span_color(saved[0], "Saved red"), RED)

    # 4. remembered
    def test_colour_remembered_between_texts(self):
        self.w.set_mode("text")
        self.w.view.format_action("color", RED)
        self.click(100, 100)
        self.write("First")
        self.w.set_mode("text")
        self.assertEqual(self.w.ink_color.name(), RED)
        self.click(100, 200)
        self.write("Second")
        self.assertEqual(span_color(self.w.engine.doc[0], "Second"), RED)

    def test_colour_remembered_across_sessions(self):
        self.w.set_mode("text")
        self.w.view.format_action("color", RED)
        self.w.settings.sync()
        self.w.engine.dirty = False
        self.w.close()
        self.w = self.make_window()
        self.w.set_mode("text")
        self.assertEqual(self.w.ink_color.name(), RED)
        self.assertEqual(self.w.view.format_bar.color_button.property("swatch"), RED)


if __name__ == "__main__":
    unittest.main()
