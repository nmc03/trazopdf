"""Packaging verification: invoked explicitly by --self-test DIRECTORY."""
import json
import os
import sys
import traceback
from pathlib import Path


def run_smoke(directory):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    result = {"ok": False, "checks": []}
    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QSettings
        from .app import EditorWindow, STYLE, ROOT
        from .engine import PDFEngine
        import pymupdf as fitz
        from PySide6.QtCore import QTimer
        from pyhanko.sign import signers
        app = QApplication.instance() or QApplication([])
        app.setStyleSheet(STYLE)
        window = EditorWindow(QSettings(str(directory / "settings.ini"), QSettings.Format.IniFormat))
        assert window.stack.currentIndex() == 0
        result["checks"].append("Qt welcome")
        window.engine.new()
        window.engine.add_text(0, (50, 50, 500, 110), "TrazoPDF packaging test", size=20)
        window.engine.add_text(0, (50, 150, 500, 220), "Acción · Ελληνικά · Привет", size=12)
        assert "Привет" in window.engine.text(0)
        result["checks"].append("Unicode text")
        window.refresh()
        window.view.begin_editor(point=fitz.Point(50, 250))
        window.view.editor.setPlainText("Inline packaging")
        assert window.view.commit_editor()
        assert "Inline packaging" in window.engine.text(0)
        result["checks"].append("inline editor")
        with fitz.open() as graphic:
            graphic.new_page(width=100, height=80).draw_rect((0, 0, 100, 80), fill=(0, 0, 1))
            graphic[0].get_pixmap().save(directory / "image.png")
        window.engine.add_image(0, (400, 260, 500, 340), directory / "image.png")
        image = window.engine.images(0)[0]
        assert image["editable"]
        window.engine.transform_image(0, image["index"], (410, 270, 510, 350))
        assert abs(window.engine.images(0)[0]["rect"].x0 - 410) < .1
        window.engine.replace_image(0, image["index"], directory / "image.png")
        result["checks"].append("per-occurrence image editing")
        window.engine.set_link(0, (50, 50, 200, 90), uri="https://example.com")
        assert window.engine.links(0)[0]["uri"] == "https://example.com"
        result["checks"].append("PDF links")
        window.engine.save(directory / "smoke.pdf")
        window.engine.export_docx(directory / "smoke.docx")
        window.engine.export_xlsx(directory / "smoke.xlsx")
        window.engine.export_pptx(directory / "smoke.pptx")
        result["checks"].extend(["MuPDF save/render", "DOCX", "XLSX", "PPTX", "pyHanko import"])
        report = window.external_job("compare", "Comparison packaging test", path=str(directory / "smoke.pdf"), output_folder=str(directory / "comparison"))
        assert report["changed_pages"] == []
        from .comparison_dialog import ComparisonDialog
        comparison = ComparisonDialog(report, directory / "comparison", window)
        comparison.show()
        app.processEvents()
        assert all(not label.pixmap().isNull() for area, label in comparison.panels)
        comparison.close()
        result["checks"].append("visual comparison process and dialog")
        window.engine.render(0, 2).save(directory / "scan.png")
        window.engine.from_images([directory / "scan.png"])
        ticks = []
        timer = QTimer()
        timer.timeout.connect(lambda: ticks.append(True))
        timer.start(20)
        data = window.external_job("ocr", "OCR packaging test", language="spa+eng")
        from .engine import resolve_external_tool
        tesseract, origin = resolve_external_tool("tesseract")
        if getattr(sys, "frozen", False):
            assert origin in ("incluido", "variable de entorno"), f"Tesseract incluido no usado: {origin}"
        timer.stop()
        assert len(ticks) > 2
        window.engine.apply_processed(data)
        assert "packaging" in window.engine.text(0)
        result["checks"].append("Tesseract spa+eng")
        result["checks"].append("responsive worker process")
        assert (ROOT / "assets/pdf-editor.ico").is_file()
        result["checks"].append("bundled icon")
        window.engine.dirty = False
        window.close()
        result["ok"] = True
    except BaseException:
        result["error"] = traceback.format_exc()
    (directory / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    if not result["ok"]:
        raise SystemExit(1)
