# Security

## Supported versions

Only the latest published version receives security fixes.

## How to report a vulnerability

Do not open a public issue for a vulnerability. Use GitHub's private security advisories:

1. Go to the **Security** tab of the repository.
2. Click **Report a vulnerability**.
3. Describe the problem, the steps to reproduce it, the affected version and, if possible, a test PDF.

Private advisories are only visible to the project maintainers. If you cannot use GitHub, open an issue requesting a private channel, without including technical details or files.

## What to expect

- Receipt is confirmed within one week.
- The impact is assessed, and a fix timeline and publication method are agreed with the reporter.
- When the fix is available, a new version is published and the issue is described in the CHANGELOG, crediting the reporter if they wish.

## Scope

Of interest, for example, are flaws that allow code execution or writes outside what is intended when opening or saving a PDF, when processing Office files or when running OCR, as well as errors in encryption or password handling.

TrazoPDF does not offer network services or accounts, so typical server issues do not apply. The limits documented in [docs/FEATURES.md](docs/FEATURES.md), such as the fact that the signature trust chain is not validated, are not vulnerabilities, although they can be reported as improvements.
