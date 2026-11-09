# Changelog

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.5.0] - 2026-11-08

### Added
- **TrazoPDF**: the application is now called TrazoPDF (executable, installer and settings folder; settings from earlier versions are not migrated).
- Interface and documentation in Spanish, English, French, German and Portuguese: the language is chosen in Help > Language (or `PDFEDITOR_LANG`) and applied on restart. README and user manual in all five languages.
- Anonymize document: irreversible removal of text, images, metadata, annotations, attachments and hidden data, with preview, post-verification and report.
- Batches and recipes: chains of steps (11 types, with predefined recipes) applied to folders from the interface or from the command line (`--batch`, `--watch`) with exit codes 0/1/2 and a conflict policy.
- Built-in OCR, 100% local: Tesseract is included in the application with Spanish, English, French, German and Portuguese models, deskew and orientation detection.
- Visible electronic signature with configurable field and appearance, and validation of existing signatures; the key can be passed via `PDFEDITOR_SIGN_PASSWORD` in batches.
- K shortcut for the form field and F to fill.
- Windows installer (unsigned) and automatic deployment of versions when merged into `main`.

- Several PDFs open at once, in tabs above the canvas: each keeps its page, zoom, scroll position, search, undo history and recovery copy. Opening a file that is already open activates its tab; Ctrl+Tab and Ctrl+Shift+Tab switch tabs, Alt+1 to Alt+9 jump to one, and Ctrl+W closes the current one.
- Check accessibility (Tools): per-item report with one-click title and language fixes and export to text.
- Digital signature with optional timestamp: enabled manually, with the address of the authority chosen by the user; without it, nothing is sent over the network.
- Continuous and two-page view: text selection spans pages, form fields can be filled on any visible page, and automatically detected fields are marked on all of them.
- Each tab remembers its side panel and thumbnail selection; tabs can be reordered by dragging.
- Redesigned interface: tool rail with groups and its own icons, top bar with page navigator and zoom in pills, page panel with cards, welcome screen with recent files, and light, dark or system theme.
- Document tools, available in the rail (Tools group) and in the menus, all with undo and redo: header and footer, Bates numbering, find and redact sensitive data, optimize size, flatten annotations and forms, page labels (visible in the thumbnails), insert pages (blank, from image or duplicated), stamps placed with one click or by dragging, check document, and compare text between two PDFs.
- Optimize size and Check document run in a separate process, without blocking the window.
- About dialog with version, license, links to LICENSE and THIRD-PARTY.md, and diagnostics for Tesseract and LibreOffice (which can be set with `PDFEDITOR_TESSERACT` and `PDFEDITOR_SOFFICE`).
- When opening a PDF with restrictions, you are offered the option to enter the owner password so that it can be saved while keeping them.
- When protecting a document you can choose the owner password; if left empty, a secure one is generated and shown only once, with a button to copy it.
- Documents: periodic autosave with recovery of unsaved changes on startup, optional `.bak` copy when saving, Save a copy (without changing the open document) and Revert.
- View: continuous scrolling and two-page view, with page, zoom and scroll position remembered per file. Recent files with date and thumbnail, and an option to remove them from the list.
- Pages: Split with distribution options, and File > Export as to text, Word, Excel, PowerPoint and images. Drop several PDFs onto the window to merge them.
- Find and replace text in the document, with navigation between matches.
- Annotations: Line, Arrow and Text box tools. Comments have author, replies and status, and are managed in a dedicated panel.
- Measure distances with scale, Layers to show or hide optional layers, and guided actions for frequent tasks.
- Password dialog with a Show button and inline errors.
- Help > Keyboard shortcuts (F1), history of the last 20 status bar messages, Ctrl+Y to redo and Ctrl+A to select all depending on focus.

### Changed
- Save keeps the encryption, permissions and passwords of the original file. If the protection cannot be kept, you are offered the option to enter the owner password, protect with new passwords, or save an unprotected copy.
- Applying redactions also removes the links, form fields and annotations that lie under the marks, and the metadata that quotes the redacted text; the warning explains this.
- Exports, extractions, splits and signed copies of a protected document warn that the result will have no password.
- The window shows the application's actual version.

### Fixed
- Save, export, extract, split, sign and OCR or comparison tasks no longer write text that is still under unapplied redactions without warning; you are offered to apply them first.
- Opening encrypted PDFs no longer queries the document already open, which avoids misreads after requesting the password.
- Deleting a comment from the annotations list can be undone and is reverted if it fails.
- Temporary folders from interrupted jobs are removed on startup if they are more than one day old.

## [0.3.0] - 2026-10-18

### Added
- Image manipulation from Edit PDF: selection, dragging, corner handles for resizing, replacement and deletion. Each operation affects one specific occurrence of the image, and other shared copies are preserved when the PDF structure allows it.
- Web, email and internal page links: creation by area, editing, deletion, listing and explicit opening.
- Visual comparison of two PDFs in a separate, cancelable process, with three views, navigation between changes, synchronized zoom and ZIP report export.

### Fixed
- Link coordinates on cropped and rotated pages.
- A new comparison requires an empty output folder, so a previous report is not overwritten.
- Lines are preserved when joining several compatible text segments into one editable block.

## [0.2.0]

### Added
- Text selection by characters, words and lines, with copy and markup (highlight, underline, strikeout).
- Add text by clicking on the page.
- Editing of existing PDF text blocks: move, edit in place and delete, with control of size, family, color, bold and italic.
- Filling of AcroForm form fields directly on the page.
- Collapsible page panel and thumbnails with labels.
- OCR of scanned and mixed pages, and Office to PDF conversion, both cancelable without losing the open document.

### Fixed
- Text replacement without applying pending redactions, and no white rectangles drawn over colored backgrounds.
- Characters from other alphabets that were converted into question marks.
- Page extraction in the requested order.
- Changes to several form fields form a single undoable operation.
