# Licensing analysis

**Status:** TrazoPDF is released under AGPL-3.0-or-later. This note explains why, what changing it would take, and the options. It is an engineering analysis, not legal advice.

## Why AGPL

TrazoPDF's engine is [PyMuPDF](https://github.com/pymupdf/PyMuPDF) (built on MuPDF), published by Artifex under **AGPL-3.0 or a paid commercial license**. A program that incorporates PyMuPDF and is distributed must be offered under AGPL-compatible terms, with source. The installer and ZIP bundle PyMuPDF, so the distributed work as a whole falls under AGPL. Choosing a license that is not AGPL-compatible (MIT included) for those binaries would breach PyMuPDF's license.

The other dependencies are not a constraint: PySide6/Qt (LGPL-3.0, dynamically linked), pyHanko (MIT), pypdf (BSD-3), Pillow, python-docx, openpyxl and python-pptx (permissive licenses) and Tesseract (Apache-2.0). See [THIRD-PARTY.md](../THIRD-PARTY.md).

AGPL section 13 (network use) does not add anything for a desktop program. In practice AGPL here means: anyone may use, study, modify and redistribute TrazoPDF, and distributed derivatives must publish their source under the same terms.

## How deeply PyMuPDF is used

About 70 of the application's modules import it (roughly 230 direct uses across ~18,500 lines): rendering, text blocks and fonts, search, annotations and appearance, forms, true redaction, page operations, metadata, saving with encryption, images. Replacing it is a rewrite of the document layer, not a dependency swap.

## Options

| Option | What it takes | Result | Main drawback |
| --- | --- | --- | --- |
| **A. Keep AGPL** (current) | Nothing | Free software, trust argument for privacy ("you can audit it") | Companies that want to embed it in closed products cannot |
| **B. Commercial license from Artifex** | Contact Artifex Sales; price is quoted per project and is not published | Allows closed or MIT-style distribution of your own code | Paid, recurring, and the license is yours, not your users'; community forks stay AGPL |
| **C. Replace PyMuPDF** with permissive libraries (for example pypdfium2 for rendering, pikepdf/pypdf for structure) | Rewrite of the document layer and its tests (months) | MIT becomes possible | Lose or rebuild true redaction, text-block editing, annotation appearance streams and reliable search quads; each library's current license must be re-verified before committing |
| **D. Dual-license your own code** | Requires option B or C first, plus copyright assignment or a CLA from contributors | Flexibility for you | Adds legal overhead for a small project |

## Recommendation

Keep AGPL (option A) for 0.x. It costs nothing, it is the only option fully compatible with the dependency, and it reinforces the privacy positioning: users and reviewers can verify that no data leaves the machine. Revisit only if there is a concrete need, such as a company wanting a closed-source license (then ask Artifex for a quote) or a decision to fund the rewrite in option C.

## If you contribute

Contributions are accepted under AGPL-3.0-or-later. If a dual-licensing path is ever wanted, a contributor agreement would have to be introduced before accepting outside code.
