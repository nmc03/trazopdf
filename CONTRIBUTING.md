# How to contribute

Thank you for your interest in TrazoPDF. Contributions are welcome: bug reports, documentation improvements, translations and code changes.

## Before you start

- For a large change, open an issue first to discuss the approach.
- For vulnerabilities, do not open a public issue: follow [SECURITY.md](SECURITY.md).
- Taking part means respecting the [code of conduct](CODE_OF_CONDUCT.md).

## Setting up the environment

You need Windows 10 or 11 and Python 3.13.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pdf_editor
```

Tesseract and LibreOffice are optional; they are only needed to test OCR and Office conversion.

## Tests

The tests use Qt's `offscreen` platform, so they do not open visible windows:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m pytest -q
```

If a change modifies behavior, add or adjust a test in the corresponding module under `tests/`. All tests must pass before you open a pull request.

## Code style

- Python with names and comments in Spanish. Interface strings are written in Spanish and act as translation keys: wrap them in `_()` and add the translations to `assets/locales/*.json` (see `tools/i18n_check.py`).
- Follow the existing style of the module you are changing. Do not reformat entire files in an unrelated change.
- Avoid new dependencies unless they are necessary; if you add one, state its license in the change description and in [THIRD-PARTY.md](THIRD-PARTY.md).
- Long-running operations must run outside the interface thread.

## Commits and pull requests

- Short commit messages, in the imperative or present tense, describing what changes and why.
- One pull request per topic. Describe the problem, the solution and how you tested it.
- State whether the change affects the build, the installers or the public documentation.

## Licensing of contributions

TrazoPDF is published under AGPL-3.0-or-later. By submitting a contribution, you agree to publish it under that same license.
