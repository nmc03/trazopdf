"""Genera las capturas de docs/screenshots con un documento de ejemplo.

Uso: python tools/screenshots.py [CARPETA_SALIDA]
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pymupdf as fitz
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from pdf_editor import theme
from pdf_editor.app import EditorWindow, STYLE

LOREM = ("Este documento de ejemplo muestra el visor de TrazoPDF: texto editable, "
         "formularios, anotaciones y herramientas de revisión en una interfaz clara.")


def make_sample(path):
    doc = fitz.open()
    for number in range(1, 4):
        page = doc.new_page(width=595, height=842)
        page.insert_textbox((56, 56, 539, 110), f"Informe trimestral · Página {number}", fontsize=24, fontname="helv")
        page.insert_textbox((56, 130, 539, 330), (LOREM + " ") * 4, fontsize=12, fontname="helv")
        page.draw_rect((56, 360, 539, 520), color=(0.2, 0.4, 0.8), fill=(0.9, 0.94, 1))
        page.insert_textbox((70, 380, 525, 500), "Resumen\n- Ingresos +12 %\n- Costes estables\n- Nuevos clientes: 48", fontsize=14, fontname="helv")
    doc.save(path)


def shot(app, window, mode, target):
    window.set_theme(mode)
    app.processEvents()
    window.grab().save(str(target))
    print("OK", target)


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "screenshots"
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    with tempfile.TemporaryDirectory() as folder:
        sample = Path(folder) / "informe.pdf"
        make_sample(sample)
        window = EditorWindow(QSettings(str(Path(folder) / "s.ini"), QSettings.Format.IniFormat))
        window.resize(1440, 900)
        window.show()
        app.processEvents()
        shot(app, window, "light", out / "welcome-light.png")
        window.open_path(str(sample))
        window.fit_page()
        for _ in range(10):
            app.processEvents()
        shot(app, window, "light", out / "editor-light.png")
        shot(app, window, "dark", out / "editor-dark.png")
        window.set_rail_collapsed(False)
        shot(app, window, "dark", out / "rail-tools-dark.png")
        window.engine.dirty = False
        window.close()


if __name__ == "__main__":
    main()
