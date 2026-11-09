# Third-party components

TrazoPDF is distributed under the GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later), which you can read in [LICENSE](LICENSE). That choice is driven by PyMuPDF, which is licensed under AGPL-3.0.

TrazoPDF uses third-party libraries. The exact versions are pinned in [requirements.txt](requirements.txt). The table summarizes the licenses declared by each project; the full texts and the notices included in each distribution prevail.

| Component | Use | License | Source |
| --- | --- | --- | --- |
| PyMuPDF (and MuPDF) | PDF reading, rendering and editing | AGPL-3.0 (or the author's commercial license) | https://github.com/pymupdf/PyMuPDF |
| PySide6 / Qt | Graphical interface | LGPL-3.0 (modules used by PySide6) | https://www.qt.io/ and https://doc.qt.io/qtforpython-6/licenses.html |
| pyHanko | PKCS#12 digital signing | MIT | https://github.com/MatthiasValvekens/pyHanko |
| python-docx | DOCX reading and writing | MIT | https://github.com/python-openxml/python-docx |
| python-pptx | PPTX reading and writing | MIT | https://github.com/scanny/python-pptx |
| openpyxl | XLSX reading and writing | MIT | https://openpyxl.readthedocs.io/ |
| pypdf | Auxiliary PDF operations | BSD-3-Clause | https://github.com/py-pdf/pypdf |
| Pillow | Image processing | MIT-CMU (HPND) | https://github.com/python-pillow/Pillow |
| tessdata_fast models (Spanish) | OCR recognition | Apache-2.0 | https://github.com/tesseract-ocr/tessdata_fast |

The TrazoPDF icon and the interface icon set (`pdf_editor/icons.py`) are original to the project.

The English and Spanish models are included in `assets/tessdata/`. The origin of the English model is the local Tesseract installation; its provenance data is in [assets/tessdata/README.txt](assets/tessdata/README.txt).

## Qt and PySide6 (LGPL-3.0)

Qt is distributed as separate dynamic libraries (DLLs) inside the `TrazoPDF` folder of the build compiled in onedir mode. They are not merged into the executable. This makes it possible to comply with the LGPL-3.0:

- You can replace the Qt and PySide6 DLLs with modified or compatible versions, and the application will use them at startup.
- You can rebuild TrazoPDF from the source code of this repository with your own Qt libraries, following the instructions in [README.md](README.md).
- The source code of Qt and PySide6 is available at https://download.qt.io/ and in the PySide/Shiboken repository of Qt (https://code.qt.io/).

This project does not modify the Qt or PySide6 code.

## Source code

The TrazoPDF code is in this repository and is published under AGPL-3.0-or-later. If you distribute a modified copy of the program, even as a service accessible over a network, you must offer its users the corresponding source code under the terms of the AGPL. The source code of the libraries above is available from the sources indicated in the table, with the versions in [requirements.txt](requirements.txt).

## External programs

These programs are not included in the package. They are used if they are installed on the computer:

- **Tesseract OCR** (Apache-2.0): text recognition on scanned pages. https://github.com/tesseract-ocr/tesseract
- **LibreOffice** (MPL-2.0): conversion of Office documents to PDF. https://www.libreoffice.org/

## Icon

The TrazoPDF icon is original to the project.
