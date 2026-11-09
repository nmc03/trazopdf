# Features and limits

TrazoPDF provides a local set of PDF tools. This table describes the scope of the implemented operations; automated checks do not replace reviewing real documents, especially for conversions, forms and signatures.

| Area | Scope | Relevant limits |
| --- | --- | --- |
| Reading | Render pages, zoom, search text and navigate bookmarks. Full-page, fit-width, 100%, two-page and continuous scrolling views. Each document remembers its page, zoom and scroll position. | Search requires a text layer; scans may need OCR. |
| Find and replace | Bar with previous and next, match counter and search options; replace text in the document. | Only finds and replaces text with a text layer. Replacement follows the editing limits in the Text row. |
| Text | Select characters/words/lines; type on the page; edit, move and delete existing PDF blocks; change basic style. | Does not reflow other blocks like a Word document. Original fonts may be substituted. Text slanted within a page cannot yet be edited directly. |
| Images | Insert, select, move, resize, replace and delete individual images, with history. | Editing is limited to supported direct images; nested or inline images, or images with complex graphics states, may not be supported. Replacing keeps the area and may stretch the new image. Does not rebuild the original layout document. |
| Links | Create, edit, delete and list web/email links and links to internal pages; explicit opening from the menu. | Other destination types can be deleted, but not edited or run. |
| Annotations | Highlight, notes, underline, strikeout, shapes, ink, lines, arrows and text boxes. Notes have reply threads and status, and are managed in the comments panel. | Appearance may vary depending on the PDF reader. |
| Redaction | Mark areas to redact and apply the redactions: text, images and graphics under the mark are removed, as well as links, form fields and annotations that touch it, and metadata, XMP and bookmarks that quote the redacted text. | Unapplied marks redact nothing: the text stays in the file, so saving, exporting, extracting, splitting or signing with pending marks asks for confirmation. Review attachments and other areas before sharing sensitive information. |
| Find and redact | Searches for patterns (cards with Luhn check, IBAN, DNI/NIE, NIF/CIF, phone numbers, dates, emails) or your own text/regular expressions, marks the chosen matches and then offers to apply them. | Detects what is written as text: does not read scanned images (use OCR first). There may be false positives and false negatives; review the list. |
| Anonymize document | Wizard that detects personal data (patterns from Find and redact, plus Social Security, license plate, IP and your own terms or expressions), redacts it, removes metadata, XMP, bookmarks, attachments and annotations that quote it, rewrites a full copy without history, and verifies the result. TXT or JSON report that does not repeat the removed data. | Verification does not detect text in fonts with a glyph subset or in images without OCR. Encrypted documents are not supported. The original is not modified. |
| Pages | Organize, delete, duplicate, merge, split with options, extract, crop and rotate. Merge supports dropping several PDFs onto the window. | Cropping changes the visible area; it must not be used to redact sensitive data. |
| Forms | Create and fill AcroForm fields; text and checkboxes can be filled directly on the page. | Does not include XFA forms or all JavaScript form scripts. |
| Automatic fields | Detects lines and checkboxes in forms without fields and proposes creating them, with preview and selection before applying. | Only detects short lines and square checkboxes; review the proposals. |
| Watermarks | Add watermarks and page numbers. | The result becomes part of the PDF. |
| Header and footer | Text on the left, center and right with {page}, {pages}, {date} and {filename}; margins, color and page range. | Single-line text; does not adjust the page content, so it may overlap with it. |
| Bates numbering | Prefix, suffix, starting number, digits and position, on all pages or a range. | Written into the page content; cannot be renumbered from the application except by undoing. |
| Stamps | Predefined stamps or an image, as a removable stamp annotation or drawn on the page; placed with one click (centered) or by dragging to set the size. | How a stamp looks as an annotation depends on the reader. |
| Page labels | Numbering by ranges (Arabic, Roman, letters, prefix) shown in the thumbnails. | Only changes logical labels; does not renumber text printed on the pages. |
| Insert pages | Blank page (A4, Letter, A3, A5 or custom size), image as a page, and duplicates with copies. | Images are inserted as a single page, without OCR. |
| Flatten | Incorporates annotations and form fields into the page content. | Fields stop being editable; can be undone within the session. |
| Optimize size | Reduces resolution and recompresses images, removes unused objects and, if desired, strips metadata. Shows the estimated size before applying and runs in a separate process. | The final size when saving may vary. Lowering ppi loses quality: save a copy if in doubt. If it cannot be reduced, nothing changes. |
| Check document | Report on scanned pages, non-embedded fonts, accessibility tags, title, language and JavaScript; double-click jumps to the page. | A quick review, not PDF/UA or PDF/A validation. |
| Check accessibility | Per-item report (title, language, tags, pages without text, alternative text, bookmarks) with one-click title and language fixes and export to text. | A quick review, not PDF/UA validation. |
| Compare text | Line-by-line text differences per page between the open document and another PDF. | Compares by page number; does not see images or formatting (for that, see Compare PDFs). |
| Information | Edit metadata and manage attachments. | Not a complete audit of all hidden data in a PDF. |
| Cleanup | Remove metadata, attachments, JavaScript, links and other elements using the sanitize operation. | May modify forms and delete useful content; review the resulting copy. |
| Protection | Open and owner passwords with AES-256 encryption. When saving, the original file's method, permissions and passwords are preserved. If the owner password is not known, you are offered the option to enter it, protect with new passwords, or save an unprotected copy. The password dialog lets you show what was typed and shows errors without closing. | Print, edit and copy permissions depend on the reader respecting them. The original owner password cannot be recovered or inferred. Anyone who knows the open password but not the owner password cannot keep the restrictions. |
| OCR | Local OCR with Tesseract included in the application and a text layer; Spanish, English, French, German and Portuguese models; optional deskew and orientation detection; scanned and mixed pages; reusable `ocr_file` function for batches. | When running from source code, requires Tesseract installed. Deskew corrects up to about 10° and takes longer. Match detection avoids duplicating existing text; recognition errors need review. |
| Office → PDF | Conversion via LibreOffice. | Requires LibreOffice; does not guarantee the same layout as Microsoft Office. |
| PDF → DOCX | Export of extracted text. | Does not faithfully preserve the PDF layout. |
| PDF → XLSX | Export of detected tables; text in rows when there are no tables. | Detection depends on the visual structure; it does not turn every page into a correct table. |
| PDF → PPTX | One page image per slide. | Page elements are not converted into editable objects. |
| Comparison | View of both documents and visual differences in magenta; navigation between changes and ZIP report; cancelable processing. | Compares by page number, with rasterization limited to 110 ppi and 1400 px on the longest side. Small changes may fall below the resolution or tolerance. Does not compare metadata, links, signatures or hidden content; does not automatically align inserted pages. |
| History | Undo and redo changes within the session. Log of the last 20 status bar messages. | Undo does not survive closing the document; change recovery is described under Documents. |
| Documents | Tabs for several PDFs open at once, each with its own history, page, zoom and search. Periodic autosave and an offer to recover unsaved changes on startup. Optional `.bak` copy when saving, Save a copy and Revert. Recent files with date and thumbnail, and per-file view memory. | The recovery copy is local and is deleted when saving or closing properly. It does not replace saving the file. Protected documents are not autosaved: you are warned once so that an unencrypted copy is not written. |
| Measure | Distance measurement on the page, with scale. | Accuracy depends on the configured scale. Not a certified measurement. |
| Layers | Shows or hides the optional content layers included in the PDF. | Only toggles existing layers; does not create or edit layers. |
| Guided actions | Step-by-step wizards for frequent tasks, such as merging, compressing, redacting or signing. | Each step uses an existing tool and its limits are those of that tool. |
| Printing | Print preview; pages are generated at the printer's resolution (between 150 and 600 ppi). | Depends on the selected driver and printer. |
| Batches and recipes | Processes folders or groups of PDFs with a recipe: an ordered list of steps (anonymize, OCR, optimize, clean metadata, watermark, numbering, Bates, rotate, crop, sign with certificate, export text). Includes three predefined recipes, a step editor, save/import/export as JSON and progress with cancellation. Also without a window: `--batch` and `--watch` (folder watched every 5 s). | Originals are not modified and, if a file fails, processing continues with the next one. The certificate password is requested at run time and is never saved. Encrypted PDFs are not processed. Each file is processed in the same process, one after another. |

## Security of output files

- A PDF opened with a password is saved with the same protection. The owner password generated when protecting is shown only once; it is not stored anywhere.
- Exporting (TXT, DOCX, XLSX, PPTX, PNG), extracting pages, splitting and signing from a protected document produces files **with no password or restrictions**; the application warns before each operation.
- Saving, exporting, extracting, splitting, signing and OCR or comparison tasks stop if there are unapplied redactions, and offer to apply them.
- Background jobs use temporary folders `pdf-editor-job-*` that are deleted when they finish; on startup, any left over from interrupted runs older than one day are removed.

## Digital signatures

PKCS#12 signing uses pyHanko and produces a signed copy. You can choose between an **invisible** signature (a record is kept only in the file) and a **visible** signature: you choose the page, draw the rectangle by dragging, and decide what it shows (the certificate signer's name, date, reason, location and, optionally, one of your saved signature images).

Signing a document that already has signatures adds an incremental revision: the earlier signatures remain valid, and the application warns you before signing. Modifying or re-saving a signed PDF may invalidate its existing signatures.

"Inspect signatures…" validates each signature locally and shows: integrity (whether the document was modified after signing), cryptographic validity, the status of the trust chain against the system root certificates or certifi (if it cannot be verified: "not verified: self-signed certificate or unknown root", not treated as a failure) and the timestamp, if any. **Revocation is not checked**, because no network is queried.

Limits: no third-party services are used, there is no remote signing or sending to signers, and the result is not equivalent to a qualified eIDAS electronic signature. Review important documents with an independent reader. The headless API is in `pdf_editor/signing.py`: `sign_file(path_in, path_out, p12, password, field_spec, appearance) -> Report` and `validate_file(path) -> list[SignatureInfo]`.

To sign an encrypted document you must explicitly save an unencrypted copy. The application does not silently remove the protection in order to sign. Long-running tasks (OCR, Office conversion, export, split, sign, images, batches, optimize and check document) show their progress and can be canceled; canceling deletes partial outputs.

## Features not covered

Direct editing targets digital text. For scans, OCR creates a searchable layer and does not rebuild the original image as an editable Office document. Editing that layer does not amount to replacing the graphic content of the scan.

Full feature parity with commercial PDF editors is not offered. The following are out of scope:

- **Timestamps**: optional and disabled by default; you must specify the timestamp authority, and they require a network connection.
- **PDF/A and PDF/X**: conformance is not converted or certified. "Check document" is a quick review, not a validation.
- **Form JavaScript and XFA**: form scripts are not executed and XFA forms are not edited.
- **PDF 3D and multimedia content**.
- **Cloud sharing**: there are no cloud services, online review, or sending of documents or signatures to third parties.
- **Other**: mobile apps, PDF portfolios, and automatic tagging or editing of accessibility tags.

Compatibility with all complex documents, dynamic forms, fonts or color profiles is not guaranteed either.
