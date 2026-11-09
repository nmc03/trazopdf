# Privacy

TrazoPDF works entirely on your computer.

## What the application does with your data

- PDF documents and the files you open, create or save are read and written only on your disk.
- There are no accounts, sign-in or user registration.
- There is no telemetry, usage statistics, automatic error reporting or update checking.
- The application does not send your documents, their text or their metadata to any server.
- The OCR and Office conversion features run Tesseract and LibreOffice on your computer, if you have them installed. Those programs do not send data outside the computer on TrazoPDF's behalf either.
- Temporary files are created in the Windows temporary folder during the operation and are deleted when it finishes.

## Network connections

TrazoPDF does not open network connections on its own. There are two exceptions, both started by you:

- When you click a link inside a document, or choose to open a link from the menu, your default browser opens that address. That connection is made by the browser, not the application, and is subject to its own privacy policy.
- The optional trusted time stamp on digital signatures. It is off by default. If you turn it on and enter a time-stamp authority address, only the hash of the signature is sent to that address, never the document.

OCR, anonymization, metadata removal, batch recipes, folder automations and digital signing run entirely on your computer and need no connection.

## How to verify it yourself

- **Block it.** In Windows Defender Firewall with Advanced Security, add an outbound rule that blocks `TrazoPDF.exe` (and the `tesseract` folder inside the installation). Every feature keeps working except the optional time stamp.
- **Watch it.** Open Resource Monitor > Network, or run `netstat -b`, while using the application: it has no connections.
- **Read it.** The source is open under AGPL-3.0-or-later. The automated test suite runs with outbound network access blocked (`tests/conftest.py`), so a change that added a network call would fail the build.
- **Check your download.** Each release publishes `SHA256SUMS.txt`.

## Information the application stores

The application stores interface preferences in your user profile, such as the layout of the page panel or the list of recent files. You can delete this data by deleting the application's settings folder. The content of documents is not stored.

## Recommendations before sharing a PDF

A PDF may contain information that is not visible on the page: metadata, author, revision history, hidden text under an image, attachments or links. TrazoPDF includes tools to review and remove some of this data, but does not guarantee a complete audit. Review the final file with an independent reader before sharing it.

## Contact

If you find behavior that contradicts this description, follow the process in [SECURITY.md](SECURITY.md).
