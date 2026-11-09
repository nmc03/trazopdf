import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf as fitz
from PIL import Image
from PySide6.QtCore import Qt, QSettings, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QFileDialog, QLineEdit, QDialogButtonBox

from pdf_editor.app import EditorWindow
from pdf_editor.comparison import compare_documents
from pdf_editor.comparison_dialog import ComparisonDialog

APP = QApplication.instance() or QApplication([])


class ExtendedWorkflows(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.temporary.name)
        self.window = EditorWindow(QSettings(str(self.root / 'ui.ini'), QSettings.Format.IniFormat))
        self.window.show()
        self.window.new_file()
        APP.processEvents()
        self.warning_patch = patch.object(QMessageBox, 'warning')
        self.warning = self.warning_patch.start()

    def tearDown(self):
        self.window.view.cancel_editor()
        self.window.engine.dirty = False
        self.window.close()
        APP.processEvents()
        self.warning_patch.stop()
        self.temporary.cleanup()

    def point(self, point):
        view = self.window.view
        return view.mapFromScene(view.scene_point(fitz.Point(point)))

    def drag(self, start, end):
        viewport = self.window.view.viewport()
        QTest.mousePress(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, self.point(start))
        QTest.mouseMove(viewport, self.point(end))
        QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, self.point(end))
        APP.processEvents()

    def insert_image(self):
        path = self.root / 'red.png'
        Image.new('RGB', (100, 80), (255, 0, 0)).save(path)
        self.window.engine.add_image(0, (50, 60, 150, 140), path)
        self.window.refresh()
        self.window.set_mode('edit')
        APP.processEvents()
        return path

    def test_image_drag_resize_delete_and_undo(self):
        self.insert_image()
        self.drag((90, 90), (190, 170))
        image = self.window.engine.images(0)[0]
        self.assertAlmostEqual(image['rect'].x0, 150, delta=2)
        self.assertAlmostEqual(image['rect'].y0, 140, delta=2)
        center = (image['rect'].tl + image['rect'].br) / 2
        QTest.mouseClick(self.window.view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, self.point(center))
        rect = self.window.view.selected_image['rect']
        self.drag(rect.br, rect.br + fitz.Point(40, 30))
        image = self.window.engine.images(0)[0]
        self.assertAlmostEqual(image['rect'].width, 140, delta=2)
        self.assertAlmostEqual(image['rect'].height, 110, delta=2)
        center = (image['rect'].tl + image['rect'].br) / 2
        QTest.mouseClick(self.window.view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, self.point(center))
        QTest.keyClick(self.window.view.viewport(), Qt.Key.Key_Delete)
        self.assertEqual(self.window.engine.images(0), [])
        self.window.undo()
        self.assertEqual(len(self.window.engine.images(0)), 1)
        self.warning.assert_not_called()

    def test_image_replacement_with_double_click_and_save(self):
        self.insert_image()
        blue = self.root / 'blue.png'
        Image.new('RGB', (100, 80), (0, 0, 255)).save(blue)
        with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(blue), '')):
            QTest.mouseDClick(self.window.view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, self.point((100, 100)))
        APP.processEvents()
        output = self.root / 'replaced.pdf'
        self.window.engine.save(output)
        with fitz.open(output) as saved:
            self.assertEqual(saved[0].get_pixmap().pixel(100, 100), (0, 0, 255))
        self.warning.assert_not_called()

    def test_link_draw_edit_without_losing_text(self):
        self.window.engine.add_text(0, (40, 40, 400, 90), 'Link label')
        self.window.refresh()
        self.window.set_mode('link')
        def fill_dialog():
            dialog = APP.activeModalWidget()
            self.assertIsNotNone(dialog)
            dialog.findChild(QLineEdit).setText('https://example.com')
            dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok).click()
        QTimer.singleShot(30, fill_dialog)
        self.drag((40, 40), (180, 90))
        self.assertEqual(self.window.engine.links(0)[0]['uri'], 'https://example.com')
        self.assertIn('Link label', self.window.engine.text(0))
        self.warning.assert_not_called()

    def make_comparison_inputs(self):
        engine = self.window.engine
        engine.add_text(0, (40, 40, 400, 90), 'Current source')
        source = self.root / 'source.pdf'
        engine.save(source)
        with fitz.open(source) as other:
            other[0].draw_rect((100, 150, 250, 250), fill=(1, 0, 0))
            other.save(self.root / 'other.pdf')
        return source, self.root / 'other.pdf'

    def test_comparison_worker_responsive_and_current_document_unchanged(self):
        source, other = self.make_comparison_inputs()
        saved = source.read_bytes()
        original_pixels = self.window.engine.render(0).samples
        ticks = []
        timer = QTimer()
        timer.timeout.connect(lambda: ticks.append(1))
        timer.start(20)
        report = self.window.external_job('compare', 'Compare test', path=str(other), output_folder=str(self.root / 'report'))
        timer.stop()
        self.assertGreater(len(ticks), 2)
        self.assertEqual(report['changed_pages'], [1])
        self.assertEqual(source.read_bytes(), saved)
        self.assertEqual(self.window.engine.render(0).samples, original_pixels)
        self.assertFalse(self.window.engine.dirty)
        dialog = ComparisonDialog(report, self.root / 'report', self.window)
        dialog.show()
        APP.processEvents()
        dialog.zoom.setCurrentText('100%')
        APP.processEvents()
        self.assertTrue(all(not label.pixmap().isNull() for area, label in dialog.panels))
        dialog.next_change()
        self.assertEqual(dialog.pages.currentRow(), 0)
        dialog.close()

    def test_comparison_cancellation_preserves_document(self):
        source, other = self.make_comparison_inputs()
        before = source.read_bytes()
        QTimer.singleShot(50, lambda: self.window.job_progress.cancel())
        result = self.window.external_job('compare', 'Cancellation test', path=str(other), output_folder=str(self.root / 'cancelled'))
        self.assertIsNone(result)
        self.assertEqual(source.read_bytes(), before)
        self.assertFalse(self.window.engine.dirty)

    def test_link_external_actions_require_valid_uri(self):
        with patch('pdf_editor.app.QDesktopServices.openUrl') as open_url:
            with self.assertRaises(ValueError):
                self.window.open_link({'kind': fitz.LINK_URI, 'uri': 'file:///C:/private.pdf'})
            open_url.assert_not_called()
            self.window.open_link({'kind': fitz.LINK_URI, 'uri': 'https://example.com'})
            open_url.assert_called_once()
