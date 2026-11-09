# Componentes de terceros

TrazoPDF se distribuye bajo la licencia GNU Affero General Public License v3.0 o posterior (AGPL-3.0-or-later), que puedes leer en [LICENSE](LICENSE). Esa elección viene dada por PyMuPDF, que está bajo AGPL-3.0.

TrazoPDF usa bibliotecas de terceros. Las versiones exactas están fijadas en [requirements.txt](requirements.txt). La tabla resume las licencias declaradas por cada proyecto; los textos completos y los avisos incluidos en cada distribución prevalecen.

| Componente | Uso | Licencia | Fuente |
| --- | --- | --- | --- |
| PyMuPDF (y MuPDF) | Lectura, render y edición de PDF | AGPL-3.0 (o licencia comercial del autor) | https://github.com/pymupdf/PyMuPDF |
| PySide6 / Qt | Interfaz gráfica | LGPL-3.0 (módulos usados por PySide6) | https://www.qt.io/ y https://doc.qt.io/qtforpython-6/licenses.html |
| pyHanko | Firma digital PKCS#12 | MIT | https://github.com/MatthiasValvekens/pyHanko |
| python-docx | Lectura y escritura de DOCX | MIT | https://github.com/python-openxml/python-docx |
| python-pptx | Lectura y escritura de PPTX | MIT | https://github.com/scanny/python-pptx |
| openpyxl | Lectura y escritura de XLSX | MIT | https://openpyxl.readthedocs.io/ |
| pypdf | Operaciones auxiliares sobre PDF | BSD-3-Clause | https://github.com/py-pdf/pypdf |
| Pillow | Tratamiento de imágenes | MIT-CMU (HPND) | https://github.com/python-pillow/Pillow |
| Modelos tessdata_fast (español) | Reconocimiento OCR | Apache-2.0 | https://github.com/tesseract-ocr/tessdata_fast |

El icono de TrazoPDF y el conjunto de iconos de la interfaz (`pdf_editor/icons.py`) son originales del proyecto.

Los modelos de inglés y español se incluyen en `assets/tessdata/`. El origen del modelo de inglés es la instalación local de Tesseract; sus datos de procedencia están en [assets/tessdata/README.txt](assets/tessdata/README.txt).

## Qt y PySide6 (LGPL-3.0)

Qt se distribuye como bibliotecas dinámicas (DLL) separadas dentro de la carpeta `TrazoPDF` de la versión compilada en modo carpeta (onedir). No están fundidas con el ejecutable. Esto permite cumplir la LGPL-3.0:

- Puedes sustituir las DLL de Qt y PySide6 por versiones modificadas o compatibles, y la aplicación las usará al arrancar.
- Puedes reconstruir TrazoPDF a partir del código fuente de este repositorio con tus propias bibliotecas Qt siguiendo las instrucciones de [README.md](README.md).
- El código fuente de Qt y de PySide6 está disponible en https://download.qt.io/ y en el repositorio de PySide/Shiboken de Qt (https://code.qt.io/).

No se modifica el código de Qt ni de PySide6 en este proyecto.

## Código fuente

El código de TrazoPDF está en este repositorio y se publica bajo AGPL-3.0-or-later. Si distribuyes una copia modificada del programa, incluso como servicio accesible por red, debes ofrecer a sus usuarios el código fuente correspondiente en los términos de la AGPL. Los códigos fuente de las bibliotecas anteriores están en las fuentes indicadas en la tabla, con las versiones de [requirements.txt](requirements.txt).

## Programas externos

Estos programas no se incluyen en el paquete. Se usan si están instalados en el equipo:

- **Tesseract OCR** (Apache-2.0): reconocimiento de texto en páginas escaneadas. https://github.com/tesseract-ocr/tesseract
- **LibreOffice** (MPL-2.0): conversión de documentos de Office a PDF. https://www.libreoffice.org/

## Icono

El icono de TrazoPDF es original del proyecto.

## Uso

TrazoPDF es un programa libre y no tiene relación con Adobe ni con los productos de Adobe. Los nombres de Acrobat y de otros productos se mencionan solo como referencia de funciones.
