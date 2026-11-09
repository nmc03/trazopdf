# TrazoPDF

**Español** · [English](README.md) · [Français](README.fr.md) · [Deutsch](README.de.md) · [Português](README.pt.md)

Editor de PDF gratuito y de código abierto para Windows. Sirve para las tareas habituales con archivos PDF —leer, buscar, anotar, rellenar formularios, unir, dividir, censurar o convertir— sin enviar los documentos a ningún servicio en línea.

Es una alternativa sencilla para el uso cotidiano de Adobe Acrobat. No pretende igualar todas sus funciones: quedan fuera los servicios en la nube, los flujos de envío de firmas y varias funciones especializadas. Las limitaciones concretas de cada función están descritas en [docs/FEATURES.md](docs/FEATURES.md).

![TrazoPDF con tema claro](docs/screenshots/editor-light.png)

![TrazoPDF con tema oscuro](docs/screenshots/editor-dark.png)

## Características principales

- Lectura con zoom, vista continua y de dos páginas, búsqueda y reemplazo de texto, y marcadores.
- Selección de texto por caracteres, palabras y líneas, con copia.
- Edición de texto y de bloques de PDF existentes, y escritura directa sobre la página.
- Imágenes: seleccionar, mover, redimensionar, sustituir y eliminar.
- Anotaciones: resaltado, subrayado, tachado, notas con respuestas y estado, figuras, líneas, flechas, cuadros de texto y tinta.
- Enlaces web, de correo y a páginas internas.
- Páginas: organizar, eliminar, duplicar, combinar, dividir, extraer, recortar y rotar.
- Formularios AcroForm: crear campos y rellenarlos sobre la página.
- Censura aplicada, búsqueda de datos sensibles para censurar, metadatos, archivos adjuntos y limpieza del documento.
- Anonimizar documento (Seguridad): detecta datos personales, genera una copia nueva, la verifica y entrega un informe.
- Encabezados y pies, numeración Bates, sellos, etiquetas de página, aplanado, optimización de tamaño, comprobación del documento y comparación de texto.
- Contraseñas y cifrado AES-256.
- Firma digital con certificado propio en formato PKCS#12, invisible o con apariencia visible, con varias firmas y validación local (sin comprobar revocación; no es una firma cualificada eIDAS).
- OCR para escaneos incluido en el programa, sin instalar nada: español, inglés, francés, alemán y portugués, con enderezado y detección de orientación.
- Procesamiento por lotes con recetas, también desde la línea de comandos.
- Conversión de Office a PDF con LibreOffice, y exportación de PDF a DOCX, XLSX y PPTX.
- Comparación visual de dos PDF con informe en ZIP.
- Deshacer y rehacer durante la sesión.
- Varios PDF abiertos en pestañas, con autoguardado y recuperación de cambios no guardados, copia `.bak` opcional, Guardar copia y Revertir.
- Medición de distancias, capas opcionales y acciones guiadas para tareas frecuentes.
- Atajos de teclado consultables con F1; por ejemplo `F` para Rellenar y firmar y `K` para Crear campo.
- Interfaz en español, inglés, francés, alemán y portugués (Ayuda > Idioma, o el idioma del sistema).

La guía completa de uso está en el [manual de usuario](docs/manual/es.md).

Consulta [docs/FEATURES.md](docs/FEATURES.md) para el alcance y los límites de cada área. Los cambios de cada versión están en el [CHANGELOG](CHANGELOG.md).

## Procesamiento por lotes

**Herramientas > Procesar varios PDFs…** aplica una receta (lista ordenada de pasos) a varios archivos sin tocar los originales. Pasos disponibles: anonimizar, OCR, optimizar, limpiar metadatos y contenido oculto, marca de agua, numerar páginas, numeración Bates, girar, recortar márgenes, firmar con certificado y exportar texto. Las recetas se pueden guardar, importar y exportar como `.json`, y hay tres predefinidas: *Anonimizar y archivar*, *Escaneo a PDF buscable* y *Reducir y limpiar*.

También se puede usar sin ventana, por ejemplo para automatizar un escáner:

```
"TrazoPDF.exe" --batch receta.json --in C:\Escaneos --out C:\Salida --recursive --on-conflict renombrar
"TrazoPDF.exe" --watch C:\Entrada --recipe receta.json --out C:\Salida
```

`--on-conflict` admite `renombrar` (por defecto), `omitir` y `sobrescribir`; `--interval` cambia los segundos entre revisiones de `--watch` (5 por defecto). El código de salida es 0 si todo fue bien, 1 si algún archivo falló y 2 si el uso es incorrecto. El informe se imprime y se guarda como `batch-report.json` en la carpeta de salida. Si la receta firma con certificado, la contraseña se toma de la variable de entorno `PDFEDITOR_SIGN_PASSWORD`. Los detalles están en el [manual](docs/manual/es.md#lotes-y-recetas).

## Descargar e instalar

Las versiones publicadas están en la página de [Releases](../../releases). Hay dos formas de instalarlo:

- **Instalador** (`TrazoPDF-x.y.z-setup.exe`): instala para tu usuario sin permisos de administrador. Puedes elegir instalarlo para todos los usuarios del equipo. Crea el acceso en el menú Inicio y, si lo marcas, en el escritorio. Registra la aplicación en «Abrir con» para los PDF sin cambiar tu programa predeterminado.
- **Carpeta portable** (`TrazoPDF-x.y.z-windows.zip`): descomprime el archivo y ejecuta `TrazoPDF.exe`. No requiere instalación.

Comprueba la integridad del archivo descargado con el fichero `SHA256SUMS.txt` de la misma versión.

Requisitos: Windows 10 u 11 de 64 bits.

> **Sin firmar.** El instalador y el ejecutable no están firmados con certificado de código, así que Windows SmartScreen puede avisar de «editor desconocido». Si descargaste el archivo de la página oficial de Releases, elige *Más información* y luego *Ejecutar de todas formas*, y comprueba antes la suma con `SHA256SUMS.txt`.

## Compilar desde el código fuente

Necesitas Python 3.13 para Windows.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pdf_editor
```

Para generar la carpeta de la aplicación:

```powershell
.\build.ps1
```

La salida queda en `dist\TrazoPDF\`, con `TrazoPDF.exe` y un fichero `SHA256SUMS.txt` junto a la carpeta. Para crear el instalador hace falta [Inno Setup 6](https://jrsoftware.org/isinfo.php):

```powershell
.\installer\build-installer.ps1
```

El script busca `ISCC.exe` en la instalación de Inno Setup y, si no lo encuentra, puedes indicar su ruta con la variable de entorno `INNO_SETUP_ISCC`. El instalador se crea en `installer\Output\`.

Las pruebas se ejecutan sin ventanas visibles:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m pytest -q
```

## Dependencias externas opcionales

- **LibreOffice** (no incluido): conversión de documentos de Office a PDF. Solo es necesario para esa función. Descarga: https://www.libreoffice.org/
- **Tesseract OCR**: ya no es una dependencia externa en la versión instalada ni en la portable, que lo incluyen con los modelos de español, inglés, francés, alemán y portugués. Solo al ejecutar desde el código fuente debe estar instalado y localizable (los modelos adicionales se descargan con `tools/fetch_tessdata.ps1`). Descarga: https://github.com/UB-Mannheim/tesseract/wiki

## Atajos de teclado

| Atajo | Acción |
| --- | --- |
| `Ctrl+O` | Abrir |
| `Ctrl+S` | Guardar |
| `Ctrl+Shift+S` | Guardar como |
| `Ctrl+Z` | Deshacer |
| `Ctrl+Shift+Z` | Rehacer |
| `Ctrl+Y` | Rehacer |
| `Ctrl+A` | Seleccionar todo (miniaturas o texto, según el foco) |
| `Ctrl+Tab` / `Ctrl+Shift+Tab` | Cambiar de pestaña de documento |
| `Alt+1` a `Alt+9` | Ir a la pestaña indicada |
| `Ctrl+W` | Cerrar el documento actual |
| `F1` | Atajos de teclado (Ayuda) |
| `Ctrl+E` | Editar PDF |
| `Ctrl+F` | Buscar |
| `F3` / `Mayús+F3` | Resultado siguiente / anterior |
| `Ctrl+R` | Girar |
| `Ctrl+P` | Imprimir |
| `Ctrl+C` | Copiar texto seleccionado |
| `Ctrl+Enter` | Aplicar el texto que se está escribiendo |
| `Esc` | Cancelar la escritura en curso |
| `F2` | Editar el bloque seleccionado |
| `Supr` | Eliminar el elemento seleccionado |
| `Ctrl` + rueda del ratón | Cambiar el zoom |

## Privacidad

TrazoPDF funciona en tu equipo. No tiene cuentas, telemetría ni comprobación de actualizaciones, y no sube tus documentos a ningún sitio. La única conexión de red ocurre cuando abres un enlace que tú mismo pulsas. Los detalles están en [PRIVACY.md](PRIVACY.md).

## Licencia

TrazoPDF se distribuye bajo la [GNU Affero General Public License v3.0 o posterior](LICENSE) (AGPL-3.0-or-later). Esta licencia es necesaria porque PyMuPDF, una de sus bibliotecas, está bajo AGPL-3.0. Las licencias de las demás bibliotecas están en [THIRD-PARTY.md](THIRD-PARTY.md).

Es una implementación independiente. No contiene código, interfaz ni recursos gráficos de Adobe.

## Contribuir

Las contribuciones son bienvenidas. Antes de empezar, lee [CONTRIBUTING.md](CONTRIBUTING.md) y el [código de conducta](CODE_OF_CONDUCT.md). Para reportar una vulnerabilidad, sigue [SECURITY.md](SECURITY.md).
