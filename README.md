# TrazoPDF

[Español](README.es.md) · **English** · [Français](README.fr.md) · [Deutsch](README.de.md) · [Português](README.pt.md)

Free and open-source PDF editor for Windows. It handles everyday PDF tasks —reading, searching, annotating, filling in forms, merging, splitting, redacting or converting— without sending your documents to any online service.

It is a simple alternative for everyday use of Adobe Acrobat. It does not aim to match all of its features: cloud services, signature-sending workflows and several specialized functions are left out. The specific limitations of each feature are described in [docs/FEATURES.md](docs/FEATURES.md).

![TrazoPDF with the light theme](docs/screenshots/editor-light.png)

![TrazoPDF with the dark theme](docs/screenshots/editor-dark.png)

## Main features

- Reading with zoom, continuous and two-page views, text search and replace, and bookmarks.
- Text selection by character, word and line, with copy.
- Editing existing PDF text and blocks, and typing directly on the page.
- Images: select, move, resize, replace and delete.
- Annotations: highlight, underline, strikethrough, notes with replies and status, shapes, lines, arrows, text boxes and ink.
- Web, email and internal page links.
- Pages: organize, delete, duplicate, merge, split, extract, crop and rotate.
- AcroForm forms: create fields and fill them in on the page.
- Applied redaction, search for sensitive data to redact, metadata, attachments and document cleanup.
- Anonymize document (Security): detects personal data, creates a new copy, verifies it and provides a report.
- Headers and footers, Bates numbering, stamps, page labels, flattening, file size optimization, document check and text comparison.
- Passwords and AES-256 encryption.
- Digital signatures with your own PKCS#12 certificate, invisible or with a visible appearance, with multiple signatures and local validation (no revocation check; not an eIDAS qualified signature).
- OCR for scanned documents included in the program, with nothing to install: Spanish, English, French, German and Portuguese, with straightening and orientation detection.
- Batch processing with recipes, also from the command line.
- Office to PDF conversion with LibreOffice, and PDF export to DOCX, XLSX and PPTX.
- Visual comparison of two PDFs with a ZIP report.
- Undo and redo during the session.
- Several PDFs open in tabs, with autosave and recovery of unsaved changes, an optional `.bak` copy, Save a copy and Revert.
- Distance measurement, optional layers and guided actions for common tasks.
- Keyboard shortcuts you can look up with F1; for example `F` for Fill and sign and `K` for Create field.
- Interface in Spanish, English, French, German and Portuguese (Help > Language, or the system language).

The full user guide is in the [user manual](docs/manual/en.md).

See [docs/FEATURES.md](docs/FEATURES.md) for the scope and limits of each area. Changes in each version are listed in the [CHANGELOG](CHANGELOG.md).

## Batch processing

**Tools > Process multiple PDFs…** applies a recipe (an ordered list of steps) to several files without touching the originals. Available steps: anonymize, OCR, optimize, clean metadata and hidden content, watermark, number pages, Bates numbering, rotate, crop margins, sign with a certificate and export text. Recipes can be saved, imported and exported as `.json` files, and there are three presets: *Anonymize and archive*, *Scan to searchable PDF* and *Reduce and clean*.

It can also run without a window, for example to automate a scanner:

```
"TrazoPDF.exe" --batch receta.json --in C:\Escaneos --out C:\Salida --recursive --on-conflict renombrar
"TrazoPDF.exe" --watch C:\Entrada --recipe receta.json --out C:\Salida
```

`--on-conflict` accepts `renombrar` (default), `omitir` and `sobrescribir` (these values are literal command-line arguments and must be typed as shown); `--interval` changes the number of seconds between `--watch` checks (5 by default). The exit code is 0 if everything went well, 1 if any file failed and 2 if the usage is incorrect. The report is printed and saved as `batch-report.json` in the output folder. If the recipe signs with a certificate, the password is taken from the `PDFEDITOR_SIGN_PASSWORD` environment variable. Details are in the [manual](docs/manual/en.md#batches-and-recipes).

## Download and install

Published versions are on the [Releases](../../releases) page. There are two ways to install it:

- **Installer** (`TrazoPDF-x.y.z-setup.exe`): installs for your user without administrator rights. You can choose to install it for all users on the computer. It creates a Start menu shortcut and, if you select it, a desktop shortcut. It registers the application in "Open with" for PDFs without changing your default program.
- **Portable folder** (`TrazoPDF-x.y.z-windows.zip`): unzip the file and run `TrazoPDF.exe`. No installation required.

Check the integrity of the downloaded file with the `SHA256SUMS.txt` file from the same version.

Requirements: 64-bit Windows 10 or 11.

> **Not signed.** The installer and the executable are not signed with a code-signing certificate, so Windows SmartScreen may show an "unknown publisher" warning. If you downloaded the file from the official Releases page, choose *More info* and then *Run anyway*, and check the checksum first with `SHA256SUMS.txt`.

## Build from source

You need Python 3.13 for Windows.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pdf_editor
```

To generate the application folder:

```powershell
.\build.ps1
```

The output goes to `dist\TrazoPDF\`, with `TrazoPDF.exe` and a `SHA256SUMS.txt` file next to the folder. To create the installer you need [Inno Setup 6](https://jrsoftware.org/isinfo.php):

```powershell
.\installer\build-installer.ps1
```

The script looks for `ISCC.exe` in the Inno Setup installation and, if it cannot find it, you can give its path in the `INNO_SETUP_ISCC` environment variable. The installer is created in `installer\Output\`.

Tests run without visible windows:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m pytest -q
```

## Optional external dependencies

- **LibreOffice** (not included): converts Office documents to PDF. It is only needed for that feature. Download: https://www.libreoffice.org/
- **Tesseract OCR**: is no longer an external dependency in the installed or portable version, which include it together with the Spanish, English, French, German and Portuguese models. Only when running from source does it need to be installed and findable (additional models are downloaded with `tools/fetch_tessdata.ps1`). Download: https://github.com/UB-Mannheim/tesseract/wiki

## Keyboard shortcuts

| Shortcut | Action |
| --- | --- |
| `Ctrl+O` | Open |
| `Ctrl+S` | Save |
| `Ctrl+Shift+S` | Save as |
| `Ctrl+Z` | Undo |
| `Ctrl+Shift+Z` | Redo |
| `Ctrl+Y` | Redo |
| `Ctrl+A` | Select all (thumbnails or text, depending on focus) |
| `Ctrl+Tab` / `Ctrl+Shift+Tab` | Switch document tab |
| `Alt+1` to `Alt+9` | Go to the indicated tab |
| `Ctrl+W` | Close the current document |
| `F1` | Keyboard shortcuts (Help) |
| `Ctrl+E` | Edit PDF |
| `Ctrl+F` | Find |
| `F3` / `Shift+F3` | Next / previous result |
| `Ctrl+R` | Rotate |
| `Ctrl+P` | Print |
| `Ctrl+C` | Copy selected text |
| `Ctrl+Enter` | Apply the text being typed |
| `Esc` | Cancel the text being typed |
| `F2` | Edit the selected block |
| `Del` | Delete the selected item |
| `Ctrl` + mouse wheel | Change the zoom |

## Privacy

TrazoPDF works on your computer. It has no accounts, telemetry or update checks, and it does not upload your documents anywhere. The only network connection happens when you open a link that you click yourself. Details are in [PRIVACY.md](PRIVACY.md).

## License

TrazoPDF is distributed under the [GNU Affero General Public License v3.0 or later](LICENSE) (AGPL-3.0-or-later). This license is required because PyMuPDF, one of its libraries, is under AGPL-3.0. The licenses of the other libraries are in [THIRD-PARTY.md](THIRD-PARTY.md).

It is an independent implementation. It contains no code, interface or graphic assets from Adobe.

## Contributing

Contributions are welcome. Before you start, read [CONTRIBUTING.md](CONTRIBUTING.md) and the [code of conduct](CODE_OF_CONDUCT.md). To report a vulnerability, follow [SECURITY.md](SECURITY.md).
