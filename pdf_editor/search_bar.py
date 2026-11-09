"""Inline search bar shown under the main toolbar (Ctrl+F). It is not a modal dialog."""
from __future__ import annotations

import pymupdf as fitz
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QSizePolicy, QToolButton, QVBoxLayout, QWidget

from .canvas import pdf_font
from .lang import _

STANDARD_FONTS = ("helvetica", "arial", "times", "courier")


def plan_replacements(page, pattern, replacement, only=None):
    """Edits that replace the matches of the pattern inside single text spans of a page.

    Each edit rewrites one span with the replacement applied. `only` is a rectangle: just the match
    that overlaps it is replaced. The counters explain matches left alone (rotated text, text that
    would not fit before the next text, matches that cross spans or lines).
    """
    plan = {"edits": [], "count": 0, "nofit": 0, "rotated": 0, "across": 0, "font": False, "charset": False}
    words = page.get_text("words")
    total = len(list(pattern.finditer(" ".join(word[4] for word in words)))) if words else 0
    handled = 0
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            spans = line["spans"]
            for position, span in enumerate(spans):
                chars = span["chars"]
                text = "".join(c["c"] for c in chars)
                matches = list(pattern.finditer(text))
                if only is not None:
                    keep = []
                    for match in matches:
                        box = fitz.Rect(chars[match.start()]["bbox"])
                        for c in chars[match.start():match.end()]:
                            box |= fitz.Rect(c["bbox"])
                        shared = box & only
                        if not shared.is_empty and shared.get_area() >= 0.3 * min(box.get_area(), only.get_area()):
                            keep.append(match)
                    matches = keep[:1]
                if not matches:
                    continue
                handled += len(matches)
                if tuple(line["dir"]) != (1, 0):
                    plan["rotated"] += len(matches)
                    continue
                if only is None:
                    new_text = pattern.sub(lambda _: replacement, text)
                else:
                    new_text = text[:matches[0].start()] + replacement + text[matches[0].end():]
                font = pdf_font(span["font"], span["flags"])
                size = span["size"]
                bbox = fitz.Rect(span["bbox"])
                room_end = fitz.Rect(spans[position + 1]["bbox"]).x0 if position + 1 < len(spans) else page.rect.x1
                if all(ord(c) < 256 for c in new_text):
                    width = fitz.get_text_length(new_text, fontname=font, fontsize=size)
                else:
                    width = fitz.Font(font).text_length(new_text, fontsize=size)
                if bbox.x0 + width > room_end + 0.5 and width > bbox.width + 0.5:
                    plan["nofit"] += len(matches)
                    continue
                if not any(name in span["font"].lower() for name in STANDARD_FONTS):
                    plan["font"] = True
                if any(ord(c) > 255 for c in new_text):
                    plan["charset"] = True
                target = fitz.Rect(bbox.x0, bbox.y0, max(bbox.x1, min(room_end, bbox.x0 + width + 1)), bbox.y1)
                plan["edits"].append({"rect": bbox, "target": target, "text": new_text, "size": size, "color": fitz.sRGB_to_pdf(span["color"]), "font": font})
                plan["count"] += len(matches)
    if only is None:
        plan["across"] = max(0, total - handled)
    return plan


class SearchField(QLineEdit):
    """Text box that reports Intro, F3 and Esc. Mayús reverses the direction."""

    navigate = Signal(bool)
    closeRequested = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("SearchField")
        self.setPlaceholderText(_("Buscar texto…"))
        self.setAccessibleName(_("Buscar texto en el documento"))
        self.setToolTip(_("Intro o F3 siguiente · Mayús+Intro o Mayús+F3 anterior · Esc cierra"))
        self.setClearButtonEnabled(True)
        self.setMinimumWidth(200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.navigate.emit(not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier))
            event.accept()
        elif event.key() == Qt.Key.Key_Escape:
            self.closeRequested.emit()
            event.accept()
        else:
            super().keyPressEvent(event)


class SearchBar(QFrame):
    """Field, result counter, previous and next buttons, and the case and whole-word switches. A second row replaces text."""

    def __init__(self, window):
        super().__init__()
        self.setObjectName("SearchBar")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        top = QWidget()
        row = QHBoxLayout(top)
        outer.addWidget(top)
        row.setContentsMargins(8, 4, 8, 4)
        row.setSpacing(6)
        self.field = SearchField()
        self.field.textChanged.connect(window.search_text_changed)
        self.field.navigate.connect(window.search_navigate)
        self.field.closeRequested.connect(window.close_search)
        row.addWidget(self.field, 1)
        self.count = QLabel()
        self.count.setObjectName("SearchCount")
        self.count.setAccessibleName(_("Resultados de búsqueda"))
        self.count.setMinimumWidth(96)
        row.addWidget(self.count)
        self.prev_button = window.pill_button("arrow-up", _("Coincidencia anterior (Mayús+Intro)"), lambda: window.search_navigate(False), pill=False)
        self.next_button = window.pill_button("arrow-down", _("Coincidencia siguiente (Intro)"), lambda: window.search_navigate(True), pill=False)
        row.addWidget(self.prev_button)
        row.addWidget(self.next_button)
        self.case_button = self.option_button("Aa", _("Distinguir mayúsculas y minúsculas"), window.search_options_changed)
        self.word_button = self.option_button(_("Palabra completa"), _("Solo palabras completas"), window.search_options_changed)
        row.addWidget(self.case_button)
        row.addWidget(self.word_button)
        self.replace_toggle = self.option_button(_("Reemplazar"), _("Mostrar u ocultar el reemplazo de texto"), lambda: self.set_replace_mode(self.replace_toggle.isChecked()))
        row.addWidget(self.replace_toggle)
        row.addWidget(window.pill_button("close", _("Cerrar búsqueda (Esc)"), window.close_search, pill=False))
        self.replace_row = QWidget()
        second = QHBoxLayout(self.replace_row)
        second.setContentsMargins(8, 0, 8, 4)
        second.setSpacing(6)
        self.replace_field = SearchField()
        self.replace_field.setPlaceholderText(_("Reemplazar con…"))
        self.replace_field.setAccessibleName(_("Texto de reemplazo"))
        self.replace_field.setToolTip(_("Intro reemplaza la coincidencia actual · Esc cierra"))
        self.replace_field.navigate.connect(lambda _=True: window.replace_current())
        self.replace_field.closeRequested.connect(window.close_search)
        second.addWidget(self.replace_field, 1)
        self.replace_count = QLabel()
        self.replace_count.setObjectName("SearchCount")
        self.replace_count.setAccessibleName(_("Reemplazos hechos"))
        self.replace_count.setMinimumWidth(96)
        second.addWidget(self.replace_count)
        self.replace_button = self.action_button(_("Reemplazar"), _("Reemplazar la coincidencia actual (Intro)"), window.replace_current)
        self.replace_all_button = self.action_button(_("Reemplazar todo"), _("Reemplazar todas las coincidencias"), window.replace_all)
        second.addWidget(self.replace_button)
        second.addWidget(self.replace_all_button)
        outer.addWidget(self.replace_row)
        self.replace_row.hide()

    def action_button(self, text, tooltip, handler):
        button = QToolButton()
        button.setText(text)
        button.setAutoRaise(True)
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda _=False: handler())
        return button

    def option_button(self, text, tooltip, handler):
        button = QToolButton()
        button.setText(text)
        button.setCheckable(True)
        button.setAutoRaise(True)
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.toggled.connect(lambda _=False: handler())
        return button

    def set_replace_mode(self, on):
        self.replace_toggle.blockSignals(True)
        self.replace_toggle.setChecked(on)
        self.replace_toggle.blockSignals(False)
        self.replace_row.setVisible(on)
        self.replace_count.setText("")
        if on:
            self.replace_field.setFocus()

    def focus_field(self):
        self.field.setFocus()
        self.field.selectAll()

    def set_status(self, text, enabled_moves, missing=False):
        """Shows the counter text; missing marks the field when a finished search found nothing."""
        self.count.setText(text)
        self.count.setStyleSheet("color: #d64545;" if missing else "")
        self.prev_button.setEnabled(enabled_moves)
        self.next_button.setEnabled(enabled_moves)
        self.replace_button.setEnabled(enabled_moves)
        self.replace_all_button.setEnabled(enabled_moves)
        self.field.setProperty("noresults", missing)
        self.field.style().unpolish(self.field)
        self.field.style().polish(self.field)
