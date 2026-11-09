"""Floating format bar: inline text, markup, shapes, notes and fields without dialogs."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf as fitz
from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QColorDialog, QMessageBox

from pdf_editor.app import EditorWindow
from pdf_editor.engine import PDFEngine
from pdf_editor.floating_bar import ColorPopover, format_shortcut, tool_style

APP = QApplication.instance() or QApplication([])
LEFT, NOMOD, CTRL = Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.ControlModifier


def close(actual, expected, tolerance=0.02):
    return all(abs(a - b) <= tolerance for a, b in zip(actual, expected))


class FloatingBarTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.folder.name)
        self.w = EditorWindow(QSettings(str(self.root / "ui.ini"), QSettings.Format.IniFormat))
        self.warning_patch = patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Ok)
        self.warning = self.warning_patch.start()
        self.color_patch = patch.object(QColorDialog, "getColor", side_effect=AssertionError("modal colour dialog used"))
        self.color_patch.start()
        self.w.show()
        self.w.new_file()
        APP.processEvents()

    def tearDown(self):
        self.w.view.cancel_editor()
        self.w.engine.dirty = False
        self.w.close()
        APP.processEvents()
        self.warning_patch.stop()
        self.color_patch.stop()
        self.folder.cleanup()

    def point(self, x, y):
        return self.w.view.mapFromScene(self.w.view.scene_point(fitz.Point(x, y)))

    def drag(self, a, b):
        view = self.w.view.viewport()
        QTest.mousePress(view, LEFT, NOMOD, self.point(*a))
        QTest.mouseMove(view, self.point(*b))
        QTest.mouseRelease(view, LEFT, NOMOD, self.point(*b))
        APP.processEvents()

    def annots(self, kind=None):
        return [a for a in self.w.engine.annotations(0) if kind is None or a["type"] == kind]

    def raw_annots(self):
        page = self.w.engine.doc[0]
        return [(annot.type[1], dict(annot.info)) for annot in page.annots()]

    # Text ---------------------------------------------------------------

    def test_bar_appears_with_inline_editor_and_hides_after_apply(self):
        self.w.set_mode("text")
        self.w.view.begin_editor(point=fitz.Point(100, 100))
        self.assertTrue(self.w.view.format_bar.isVisibleTo(self.w))
        self.assertEqual(self.w.view.format_bar.profile, "text")
        QTest.keyClicks(self.w.view.viewport(), "Bar text")
        QTest.keyClick(self.w.view.viewport(), Qt.Key.Key_Return, CTRL)
        APP.processEvents()
        self.warning.assert_not_called()
        self.assertIsNone(self.w.view.editor)
        # After applying, the new block stays selected and the bar follows it.
        self.assertIsNotNone(self.w.view.selected_run)
        self.assertEqual(self.w.view.format_bar.profile, "text")

    def test_size_and_bold_apply_live_to_the_inline_editor(self):
        self.w.view.begin_editor(point=fitz.Point(100, 100))
        self.w.view.format_bar.size_spin.setValue(20)
        self.assertEqual(self.w.view.editor.size, 20)
        self.w.view.format_bar.bold.click()
        self.assertTrue(self.w.view.editor.font_name.startswith("heb"))

    def test_ctrl_b_is_bold_while_the_editor_has_focus_and_not_the_rail_toggle(self):
        self.w.view.begin_editor(point=fitz.Point(100, 100))
        collapsed = self.w.rail_collapsed
        QTest.keyClick(self.w.view.viewport(), Qt.Key.Key_B, CTRL)
        APP.processEvents()
        self.assertTrue(self.w.view.format_bar.bold.isChecked())
        self.assertEqual(self.w.rail_collapsed, collapsed)

    def test_ctrl_shift_greater_steps_through_the_size_scale(self):
        self.w.view.begin_editor(point=fitz.Point(100, 100))
        before = self.w.view.format_bar.size_spin.value()
        QTest.keyClick(self.w.view.viewport(), Qt.Key.Key_Greater, CTRL | Qt.KeyboardModifier.ShiftModifier)
        self.assertGreater(self.w.view.format_bar.size_spin.value(), before)

    def test_format_shortcut_mapping(self):
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QKeyEvent
        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_E, CTRL)
        self.assertEqual(format_shortcut(event), ("align", 1))
        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_E, CTRL | Qt.KeyboardModifier.ShiftModifier)
        self.assertIsNone(format_shortcut(event))

    def test_alignment_is_passed_to_the_engine_on_apply(self):
        self.w.view.begin_editor(point=fitz.Point(100, 100))
        self.w.view.editor.setPlainText("Centered line")
        self.w.view.format_bar.align_buttons[1].click()
        self.assertEqual(self.w.view.editor.align, 1)
        self.assertTrue(self.w.view.commit_editor())
        self.assertIn("Centered line", self.w.engine.text(0))

    def test_colour_popover_picks_text_colour_without_modal_dialog(self):
        self.w.choose_color(None)
        popover = self.w._color_popover
        self.assertIsInstance(popover, ColorPopover)
        self.w.view.begin_editor(point=fitz.Point(100, 100))
        popover._pick("#d93025")
        self.assertTrue(close(self.w.view.editor.color, (0.851, 0.188, 0.145), 0.01))
        self.w.view.cancel_editor()

    def test_selection_profile_copies_and_marks_up(self):
        self.w.engine.doc[0].insert_text((50, 100), "Hello world", fontsize=12)
        self.w.refresh()
        self.w.set_mode("select")
        chars = [c for c in self.w.view.chars if c[1] is not None]
        first, fifth = chars[0][1], chars[4][1]
        y = (first.y0 + first.y1) / 2
        self.drag((first.x0 + .1, y), (fifth.x1 - .1, y))
        self.assertEqual(self.w.view.format_bar.profile, "selection")
        self.w.view.format_action("copy")
        self.assertEqual(APP.clipboard().text(), "Hello")

    # Markup and shapes --------------------------------------------------

    def test_highlight_uses_the_last_colour_chosen_for_that_tool(self):
        self.w.engine.doc[0].insert_text((50, 100), "Hello world", fontsize=12)
        self.w.refresh()
        self.w.set_mode("highlight")
        self.w.view.format_action("color", "#8fd694")
        chars = [c for c in self.w.view.chars if c[1] is not None]
        first, fifth = chars[0][1], chars[4][1]
        y = (first.y0 + first.y1) / 2
        self.drag((first.x0 + .1, y), (fifth.x1 - .1, y))
        highlights = self.annots("Highlight")
        self.assertEqual(len(highlights), 1)
        self.assertTrue(close(highlights[0]["stroke"], (0.561, 0.839, 0.580), 0.01))
        self.assertEqual(tool_style(self.w.settings, "highlight")["color"], "#8fd694")

    def test_rectangle_takes_width_and_opacity_from_the_bar(self):
        self.w.set_mode("rectangle")
        self.w.view.format_action("width", 4)
        self.w.view.format_action("opacity", 0.7)
        self.w.perform_selection("rectangle", fitz.Rect(100, 100, 200, 160), fitz.Point(100, 100), False, [])
        shapes = self.annots("Square")
        self.assertEqual(len(shapes), 1)
        self.assertEqual(round(shapes[0]["width"]), 4)
        self.assertAlmostEqual(shapes[0]["opacity"], 0.7, places=2)

    def test_ink_uses_the_bar_width_and_colour(self):
        self.w.set_mode("ink")
        self.w.view.format_action("width", 8)
        self.w.view.format_action("color", "#1a73e8")
        self.w.perform_selection("ink", fitz.Rect(), fitz.Point(50, 50), False, [fitz.Point(50, 50), fitz.Point(120, 90)])
        inks = self.annots("Ink")
        self.assertEqual(len(inks), 1)
        self.assertEqual(round(inks[0]["width"]), 8)
        self.assertTrue(close(inks[0]["stroke"], (0.102, 0.455, 0.910), 0.01))

    def test_selected_shape_recolours_with_one_undo_step_for_consecutive_colour_changes(self):
        self.w.perform_selection("rectangle", fitz.Rect(100, 100, 200, 160), fitz.Point(100, 100), False, [])
        self.w.set_mode("edit")
        info = self.annots("Square")[0]
        self.w.view.select_annotation(info)
        self.w.view.format_action("color", "#188038")
        self.w.view.format_action("color", "#9334e6")
        self.assertTrue(close(self.annots("Square")[0]["stroke"], (0.576, 0.204, 0.902), 0.01))
        self.w.undo()
        self.assertEqual(len(self.annots("Square")), 1)
        self.assertTrue(close(self.annots("Square")[0]["stroke"], (0.851, 0.188, 0.145), 0.01))

    def test_drag_moves_a_selected_rectangle(self):
        self.w.perform_selection("rectangle", fitz.Rect(100, 100, 200, 160), fitz.Point(100, 100), False, [])
        self.w.set_mode("edit")
        self.drag((150, 130), (190, 160))
        moved = self.annots("Square")[0]["rect"]
        # el arrastre empieza tras un umbral de unos píxeles y el zoom no es 100 %: se admiten 4 pt
        self.assertAlmostEqual(moved.x0 - 100, 40, delta=4)
        self.assertAlmostEqual(moved.y0 - 100, 30, delta=4)

    def test_delete_key_removes_the_selected_annotation(self):
        self.w.perform_selection("rectangle", fitz.Rect(100, 100, 200, 160), fitz.Point(100, 100), False, [])
        self.w.set_mode("edit")
        self.w.view.select_annotation(self.annots("Square")[0])
        QTest.keyClick(self.w.view.viewport(), Qt.Key.Key_Delete)
        APP.processEvents()
        self.assertEqual(self.annots("Square"), [])

    # Notes and fields ----------------------------------------------------

    def test_note_opens_a_popover_and_keeps_the_typed_text(self):
        self.w.perform_selection("note", fitz.Rect(), fitz.Point(120, 120), True, [])
        popover = self.w.view.note_popover
        self.assertIsNotNone(popover)
        popover.edit.setPlainText("Revisar cifras")
        popover.finish()
        notes = [info for kind, info in self.raw_annots() if kind == "Text"]
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["content"], "Revisar cifras")

    def test_escape_on_an_empty_note_removes_it(self):
        self.w.perform_selection("note", fitz.Rect(), fitz.Point(120, 120), True, [])
        popover = self.w.view.note_popover
        QTest.keyClick(popover.edit, Qt.Key.Key_Escape)
        APP.processEvents()
        self.assertEqual([kind for kind, _ in self.raw_annots() if kind == "Text"], [])

    def test_field_gets_an_automatic_name_and_the_chosen_type(self):
        self.w.set_mode("field")
        self.w.view.format_bar.field_kinds[2].setChecked(True)
        self.w.perform_selection("field", fitz.Rect(100, 100, 250, 130), fitz.Point(100, 100), False, [])
        self.w.perform_selection("field", fitz.Rect(100, 150, 250, 180), fitz.Point(100, 150), False, [])
        names = [f["name"] for f in self.w.engine.forms()]
        self.assertEqual(names, ["Campo_1", "Campo_2"])
        kinds = [w.field_type for w in self.w.engine.doc[0].widgets()]
        self.assertEqual(kinds, [fitz.PDF_WIDGET_TYPE_COMBOBOX, fitz.PDF_WIDGET_TYPE_COMBOBOX])

    def test_duplicate_field_name_is_reported_inline(self):
        self.w.set_mode("field")
        self.w.engine.add_field(0, (100, 100, 250, 130), "Nombre")
        self.w.view.format_bar.set_field_name("Nombre")
        self.w.perform_selection("field", fitz.Rect(100, 150, 250, 180), fitz.Point(100, 150), False, [])
        self.assertEqual(len(self.w.engine.forms()), 1)
        self.assertIn("Nombre", self.w.statusBar().currentMessage())


class EngineStyleTests(unittest.TestCase):
    def setUp(self):
        self.engine = PDFEngine()

    def tearDown(self):
        self.engine.close()

    def test_annotate_accepts_colour_width_and_opacity(self):
        xref = self.engine.annotate(0, (50, 50, 150, 120), "rectangle", "", color=(0, 0, 1), width=4, opacity=0.4)
        self.assertIsInstance(xref, int)
        info = self.engine.annotations(0)[0]
        self.assertEqual(round(info["width"]), 4)
        self.assertAlmostEqual(info["opacity"], 0.4, places=2)
        self.assertTrue(close(info["stroke"], (0, 0, 1)))

    def test_add_ink_accepts_opacity(self):
        self.engine.add_ink(0, [(20, 20), (80, 80)], (1, 0, 0), 2, 0.7)
        info = self.engine.annotations(0)[0]
        self.assertAlmostEqual(info["opacity"], 0.7, places=2)

    def test_style_changes_with_same_key_share_one_undo_step(self):
        self.engine.annotate(0, (50, 50, 150, 120), "rectangle")
        steps = len(self.engine._undo)
        xref = self.engine.annotations(0)[0]["xref"]
        self.engine.set_annotation_style(0, xref, color=(1, 0, 0), coalesce="color:1")
        self.engine.set_annotation_style(0, xref, color=(0, 1, 0), coalesce="color:1")
        self.assertEqual(len(self.engine._undo), steps + 1)
        self.engine.set_annotation_style(0, xref, opacity=0.4, coalesce="opacity:1")
        self.assertEqual(len(self.engine._undo), steps + 2)

    def test_choice_field_is_supported(self):
        self.engine.add_field(0, (50, 50, 150, 80), "Pais", "choice")
        self.assertEqual(self.engine.forms()[0]["name"], "Pais")


if __name__ == "__main__":
    unittest.main()
