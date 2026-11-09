import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf as fitz
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QDialog

from pdf_editor.app import EditorWindow
from pdf_editor.comparison_dialog import ComparisonDialog
from pdf_editor.ui_support import JOB_PREFIXES, OWNER_FILE, purge_stale_jobs

APP = QApplication.instance() or QApplication([])


def make_pdf(path, text, rect=None):
    with fitz.open() as document:
        page = document.new_page(width=612, height=792)
        page.insert_text((72, 100), text, fontsize=24)
        if rect:
            page.draw_rect(fitz.Rect(*rect), color=(1, 0, 0), fill=(1, 0, 0))
        document.save(str(path))
    return path


class CompareFlow(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.folder.name)
        self.w = EditorWindow(QSettings(str(self.root / "ui.ini"), QSettings.Format.IniFormat))
        self.w.show()
        self.w.new_file()
        APP.processEvents()
        self.first = make_pdf(self.root / "first.pdf", "Hola")
        self.second = make_pdf(self.root / "second.pdf", "Adios", rect=(100, 200, 300, 400))
        self.w.engine.open(str(self.first))
        APP.processEvents()

    def tearDown(self):
        self.w.engine.dirty = False
        self.w.close()
        APP.processEvents()
        self.folder.cleanup()

    def run_compare(self):
        seen = {}

        def fake_exec(dialog):
            seen["report"] = dialog.report
            seen["folder"] = dialog.folder
            seen["owner_during"] = (dialog.folder.parent / OWNER_FILE).read_text(encoding="ascii")
            seen["files"] = sorted(p.name for p in dialog.folder.iterdir())
            return QDialog.DialogCode.Accepted

        with patch("pdf_editor.ui_tools.QFileDialog.getOpenFileName", return_value=(str(self.second), "PDF (*.pdf)")), \
                patch.object(ComparisonDialog, "exec", fake_exec):
            self.w.compare()
        return seen

    def test_compare_generates_report_without_error(self):
        seen = self.run_compare()
        self.assertIn("report", seen, "The comparison dialog must open with a report")
        report = seen["report"]
        self.assertEqual(report["total_pages"], 1)
        self.assertEqual(report["changed_pages"], [1])
        self.assertIn("comparison.json", seen["files"])
        self.assertIn("page_0001_diff.png", seen["files"])

    def test_report_folder_is_separate_and_claimed(self):
        seen = self.run_compare()
        self.assertEqual(seen["folder"].name, "report")
        self.assertTrue(seen["folder"].parent.name.startswith(JOB_PREFIXES[1]))
        self.assertEqual(seen["owner_during"], str(os.getpid()))
        self.assertNotIn(OWNER_FILE, seen["files"])

    def test_claimed_folder_is_left_alone_by_purge_and_cleaned_after(self):
        claimed = {}

        def fake_exec(dialog):
            claimed["parent"] = dialog.folder.parent
            # Simulate another instance's purge over a root holding this live job and a dead, ownerless one.
            live = self.root / (JOB_PREFIXES[1] + "live")
            live.mkdir()
            (live / OWNER_FILE).write_text(str(os.getpid()), encoding="ascii")
            dead = self.root / (JOB_PREFIXES[1] + "dead")
            dead.mkdir()
            removed = purge_stale_jobs(folder=self.root, max_age=0)
            claimed["live_kept"] = live.exists()
            claimed["dead_removed"] = not dead.exists()
            claimed["removed"] = removed
            claimed["claimed_kept"] = dialog.folder.parent.exists()
            return QDialog.DialogCode.Accepted

        with patch("pdf_editor.ui_tools.QFileDialog.getOpenFileName", return_value=(str(self.second), "PDF (*.pdf)")), \
                patch.object(ComparisonDialog, "exec", fake_exec):
            self.w.compare()
        self.assertTrue(claimed["live_kept"], "A folder owned by this running editor must not be purged")
        self.assertTrue(claimed["dead_removed"], "An ownerless stale folder must still be purged")
        self.assertTrue(claimed["claimed_kept"], "The claimed comparison folder must not be purged while in use")
        self.assertFalse(claimed["parent"].exists(), "The temporary comparison folder must be removed afterwards")


if __name__ == "__main__":
    unittest.main()
