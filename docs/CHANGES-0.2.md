# TrazoPDF 0.2

This revision changes how users interact with the document, based on usability testing and problems reported by users.

## Editing on the page

- Selection by characters, words and lines. Dragging selects text; double-click selects a word; Ctrl+C copies. Highlight, underline and strikeout apply to the selected text.
- Add text lets you click and type in the document. Ctrl+Enter applies; Esc cancels; saving also applies pending text.
- Edit PDF lets you select blocks with the pointer, drag them to move them and delete them with Del. Double-click or F2 opens direct editing of the block.
- The content of existing PDFs can be edited; after saving and reopening, the changes remain PDF text.
- Controls for size, family, color, bold and italic. The color is kept and an attempt is made to approximate the style of the original block.
- Undo and redo distinguish the text being typed from changes already applied to the document.
- AcroForm text fields can be filled on the page; checkboxes respond to a click.

## Layout

- Tools on the left; thumbnails and bookmarks on the right.
- Collapsible page panel using the arrow in its header; the preference is remembered.
- Labels under the thumbnails and rendering adapted to screen density.
- Multiple page selection is kept during operations.

## Fixes

- Replacing text does not apply other pending redactions or paint a white rectangle over colored backgrounds.
- Unicode: other alphabets no longer silently turn into question marks.
- Extracting pages respects the requested order.
- Closing the document clears search matches.
- Changing zoom safely cancels transient gestures and first applies the text being typed.
- If the text does not fit, the editor keeps what was typed and does not save an incomplete result.
- Changes to several form fields form a single operation that can be undone; a failure reverts all changes in that submission.
- OCR and Office conversion use separate processes with cancellation. A failure or cancellation keeps the document that was open.
- OCR of mixed pages: recognizes image areas and keeps the searchable text that already existed.

## Limits that remain

Editing uses blocks detected by the PDF engine: it does not rebuild the original Word document or automatically reflow other blocks. Original fonts may be replaced with an equivalent family. Blocks that are internally slanted cannot yet be edited directly; pages rotated 90/180/270 degrees are supported. Office exports keep the limits described in FEATURES.md.

Automated tests and visual review cover specific cases; they do not prove compatibility with all PDFs.
