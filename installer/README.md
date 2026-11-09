# Instalador

`build-installer.ps1` compila la aplicación (`build.ps1`) y después el instalador con Inno Setup 6.

## OCR integrado

El paquete incluye Tesseract para que el OCR funcione sin instalar nada aparte:

- `build.ps1` busca `tesseract.exe` en la variable `PDFEDITOR_TESSERACT` (el ejecutable o su carpeta) o en `Program Files\Tesseract-OCR`, y copia el ejecutable y sus DLL a la carpeta `tesseract` dentro de la aplicación. Si no lo encuentra, la compilación falla con un mensaje claro; con `.\build.ps1 -SkipTesseract` continúa sin él y avisa.
- La aplicación prefiere esa copia incluida (`resolve_external_tool`); la variable `PDFEDITOR_TESSERACT` sigue teniendo prioridad.
- Los modelos viven en `assets\tessdata`: `spa` y `eng` están en git; `fra`, `deu`, `por` y `osd` (orientación) se descargan con `tools\fetch_tessdata.ps1` (suma SHA-256 comprobada). `build.ps1` lo ejecuta si faltan.
- `pdf-editor.iss` copia toda la carpeta compilada, incluida `tesseract`, así que no necesita cambios por idioma.
- Tamaño aproximado añadido: Tesseract con DLL y modelos fra, deu, por y osd, unos 40 MB sin comprimir.
