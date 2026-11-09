import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf as fitz
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication

from pdf_editor.app import EditorWindow
from pdf_editor.engine import PDFEngine

APP = QApplication.instance() or QApplication([])


class ProcessingWorkflows(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.folder.name)
        self.w = EditorWindow(QSettings(str(self.root / "ui.ini"), QSettings.Format.IniFormat))
        self.w.show()
        self.w.new_file()
        APP.processEvents()

    def tearDown(self):
        self.w.engine.dirty = False
        self.w.close()
        APP.processEvents()
        self.folder.cleanup()

    def make_scan(self):
        image = self.root / "scan.png"
        with fitz.open() as document:
            page = document.new_page(width=500, height=180)
            page.insert_text((30, 100), "HELLO MIXED OCR", fontsize=28)
            page.get_pixmap(matrix=fitz.Matrix(2, 2)).save(image)
        return image

    def test_mixed_page_ocr_keeps_existing_text_without_duplicates(self):
        image = self.make_scan()
        self.w.engine.doc[0].insert_image((20, 20, 520, 200), filename=str(image))
        self.w.engine.add_text(0, (30, 260, 500, 320), "Existing searchable footer", size=16)
        self.w.engine.ocr("eng")
        text = self.w.engine.text(0)
        self.assertIn("HELLO", text)
        self.assertEqual(text.count("Existing searchable footer"), 1)

    def test_ocr_worker_keeps_ui_responsive_and_result_is_undoable(self):
        self.w.engine.from_images([self.make_scan()])
        original_path = self.root / "original.pdf"
        self.w.engine.save(original_path)
        original_bytes = original_path.read_bytes()
        ticks = []
        heartbeat = QTimer()
        heartbeat.timeout.connect(lambda: ticks.append(True))
        heartbeat.start(20)
        result = self.w.external_job("ocr", "OCR test", language="eng")
        heartbeat.stop()
        self.assertGreater(len(ticks), 5)
        self.assertFalse(self.w.engine.text(0).strip())
        self.w.engine.apply_processed(result)
        self.assertIn("HELLO", self.w.engine.text(0))
        self.assertEqual(self.w.engine.path, str(original_path))
        self.assertEqual(original_path.read_bytes(), original_bytes)
        self.w.engine.undo()
        self.assertFalse(self.w.engine.text(0).strip())

    def test_worker_cancel_preserves_current_document(self):
        self.w.engine.from_images([self.make_scan()])
        original = self.root / "cancel-original.pdf"
        self.w.engine.save(original)
        before = original.read_bytes()
        pixels = self.w.engine.render(0).samples
        QTimer.singleShot(80, lambda: self.w.job_progress.cancel())
        result = self.w.external_job("ocr", "Cancellation test", language="eng")
        self.assertTrue(result is None, "Cancelled OCR must not return a processed document")
        self.assertEqual(original.read_bytes(), before)
        self.assertEqual(self.w.engine.render(0).samples, pixels)
        self.assertFalse(self.w.engine.dirty)
        self.assertFalse(self.w.engine.text(0).strip())

    def test_worker_failure_leaves_original_untouched(self):
        self.w.engine.add_text(0, (40, 40, 400, 100), "Keep this")
        with self.assertRaisesRegex(ValueError, "desconocida"):
            self.w.external_job("invalid", "Invalid job")
        self.assertIn("Keep this", self.w.engine.text(0))

    def test_cancel_interrupts_an_external_program_already_running(self):
        started = time.monotonic()
        with self.assertRaises(InterruptedError):
            PDFEngine._external_command([sys.executable, "-c", "import time; time.sleep(10)"],
                                        cancelled=lambda: time.monotonic() - started > .2)
        self.assertLess(time.monotonic() - started, 3)
