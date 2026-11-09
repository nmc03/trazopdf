"""Detectar campos: finds blanks (short rules, empty squares) in flat PDFs and offers them as form fields."""
import re

import fitz
from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QPen
from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout

from . import theme
from .lang import _, ntext
from .toast import notify

MIN_LINE, MAX_LINE = 36, 420
BOX_MIN, BOX_MAX = 6, 22
FIELD_HEIGHT = 16


def _spans(page):
    spans = []
    for block in page.get_text("dict").get("blocks", ()):
        for line in block.get("lines", ()):
            for span in line.get("spans", ()):
                text = span["text"].strip()
                if text:
                    spans.append((fitz.Rect(span["bbox"]), text))
    return spans


def _rules_and_boxes(page):
    rules, boxes = [], []
    for drawing in page.get_drawings():
        for item in drawing["items"]:
            kind = item[0]
            if kind == "l":
                a, b = item[1], item[2]
                if abs(a.y - b.y) <= 1 and MIN_LINE <= abs(a.x - b.x) <= MAX_LINE:
                    rules.append(fitz.Rect(min(a.x, b.x), a.y, max(a.x, b.x), a.y))
            elif kind == "re":
                r = item[1]
                if r.height <= 1.5 and MIN_LINE <= r.width <= MAX_LINE:
                    rules.append(fitz.Rect(r.x0, (r.y0 + r.y1) / 2, r.x1, (r.y0 + r.y1) / 2))
                elif BOX_MIN <= r.width <= BOX_MAX and BOX_MIN <= r.height <= BOX_MAX and abs(r.width - r.height) <= 3:
                    fill = drawing.get("fill")
                    if fill is None or min(fill) > 0.85:
                        boxes.append(fitz.Rect(r))
            elif kind == "qu":
                q = item[1].rect
                if BOX_MIN <= q.width <= BOX_MAX and BOX_MIN <= q.height <= BOX_MAX and abs(q.width - q.height) <= 3:
                    boxes.append(fitz.Rect(q))
    return rules, boxes


def _unique(items, close):
    kept = []
    for item in items:
        if not any(close(item, other) for other in kept):
            kept.append(item)
    return kept


def _clean_label(text):
    return re.sub(r"\s+", " ", text).strip(" :._-–—•…")


def _line_label(rule, spans):
    """Text to the left on the same row, else the closest text right above the rule."""
    best, best_gap = None, None
    for box, text in spans:
        same_row = box.y0 - 4 <= rule.y0 <= box.y1 + 6 and box.y1 >= rule.y0 - FIELD_HEIGHT
        if same_row and box.x1 <= rule.x0 + 4 and rule.x0 - box.x1 <= 60:
            gap = rule.x0 - box.x1
            if best_gap is None or gap < best_gap:
                best, best_gap = text, gap
    if best:
        return _clean_label(best)
    for box, text in spans:
        above = 0 <= rule.y0 - box.y1 <= 22 and box.x0 < rule.x1 and box.x1 > rule.x0
        if above:
            gap = rule.y0 - box.y1
            if best_gap is None or gap < best_gap:
                best, best_gap = text, gap
    return _clean_label(best) if best else ""


def _is_underline(rule, spans):
    covered = 0.0
    for box, _kind in spans:
        if -1 <= rule.y0 - box.y1 <= 3 and box.y0 < rule.y0:
            covered += max(0.0, min(box.x1, rule.x1) - max(box.x0, rule.x0))
    return covered > (rule.x1 - rule.x0) * 0.5


def _box_label(box, spans):
    best, best_gap = None, None
    for rect, text in spans:
        centered = rect.y0 - 3 <= (box.y0 + box.y1) / 2 <= rect.y1 + 3
        if not centered:
            continue
        for gap in (rect.x0 - box.x1, box.x0 - rect.x1):
            if -2 <= gap <= 30 and (best_gap is None or gap < best_gap):
                best, best_gap = text, gap
    return _clean_label(best) if best else ""


def detect(page, taken_names=()):
    """Candidates on one page: dicts with page, rect (unrotated page coordinates), kind and suggested name."""
    spans = _spans(page)
    rules, boxes = _rules_and_boxes(page)
    rules = _unique(rules, lambda a, b: abs(a.y0 - b.y0) < 2 and abs(a.x0 - b.x0) < 3 and abs(a.x1 - b.x1) < 3)
    boxes = _unique(boxes, lambda a, b: abs(a.x0 - b.x0) < 2 and abs(a.y0 - b.y0) < 2)
    existing = [w.rect for w in page.widgets() or ()]
    words = page.get_text("words")
    found = []
    for box in boxes:
        if any(box.intersects(r) for r in existing) or any(fitz.Rect(w[:4]).intersects(box + (1, 1, -1, -1)) for w in words):
            continue
        found.append({"page": page.number, "rect": tuple(box), "kind": "checkbox", "label": _box_label(box, spans)})
    for rule in rules:
        if _is_underline(rule, spans):
            continue
        rect = fitz.Rect(rule.x0, rule.y0 - FIELD_HEIGHT, rule.x1, rule.y0 - 1)
        if any(rect.intersects(r) for r in existing) or any(rect.intersects(b) for b in boxes):
            continue
        found.append({"page": page.number, "rect": tuple(rect), "kind": "text", "label": _line_label(rule, spans)})
    found.sort(key=lambda c: (round(c["rect"][1] / 4), c["rect"][0]))
    names = set(taken_names)
    counters = {"text": 0, "checkbox": 0}
    for candidate in found:
        counters[candidate["kind"]] += 1
        base = candidate.pop("label") or _("Casilla {n}" if candidate["kind"] == "checkbox" else "Campo {n}", n=counters[candidate["kind"]])
        name, n = base, 2
        while name in names:
            name = _("{base} {n}", base=base, n=n)
            n += 1
        names.add(name)
        candidate["name"] = name
        candidate["accepted"] = True
    return found


class DetectorPanel(QFrame):
    """Non-modal list over the page: each candidate has a checkbox, and the overlay on the page mirrors it."""

    def __init__(self, window, candidates):
        super().__init__(window.view.viewport())
        self.window_ = window
        self.candidates = candidates
        self.items = []
        self.drawn_page = None
        self.setObjectName("Pill")
        self.setAccessibleName(_("Detectar campos"))
        self.setAttribute(Qt.WidgetAttribute.WA_NoMousePropagation)
        column = QVBoxLayout(self)
        column.setContentsMargins(10, 8, 10, 8)
        column.setSpacing(6)
        self.title = QLabel("")
        self.title.setAccessibleName(_("Resumen de campos detectados"))
        column.addWidget(self.title)
        self.list = QListWidget()
        self.list.setAccessibleName(_("Campos detectados"))
        self.list.setMinimumWidth(240)
        self.list.setMaximumHeight(200)
        column.addWidget(self.list)
        self.all_box = QCheckBox(_("Aceptar todos"))
        self.all_box.setChecked(True)
        self.all_box.clicked.connect(self.set_all)
        column.addWidget(self.all_box)
        row = QHBoxLayout()
        self.create_button = QPushButton("")
        self.create_button.clicked.connect(self.create)
        self.close_button = QPushButton(_("Cerrar"))
        self.close_button.setProperty("secondary", True)
        self.close_button.clicked.connect(self.close_panel)
        row.addWidget(self.create_button)
        row.addWidget(self.close_button)
        column.addLayout(row)
        for candidate in candidates:
            entry = QListWidgetItem(_("{name} · pág. {page}", name=candidate["name"], page=candidate["page"] + 1))
            entry.setFlags(entry.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            entry.setCheckState(Qt.CheckState.Checked)
            self.list.addItem(entry)
        self.list.itemChanged.connect(self.entry_changed)
        self.list.currentRowChanged.connect(lambda _row: self.redraw())
        self.watch = QTimer(self)
        self.watch.setInterval(250)
        self.watch.timeout.connect(self.tick)
        self.watch.start()
        self.sync_texts()
        self.adjustSize()
        self.place()
        self.show()
        self.raise_()
        self.redraw()

    def place(self):
        parent = self.parentWidget()
        self.move(max(8, parent.width() - self.width() - 16), 12)

    def accepted(self):
        return [c for c in self.candidates if c["accepted"]]

    def sync_texts(self):
        count = len(self.accepted())
        self.title.setText(_("{n} campos detectados", n=len(self.candidates)))
        self.create_button.setText(ntext(count, "Crear 1 campo", "Crear {n} campos"))
        self.create_button.setEnabled(count > 0)

    def entry_changed(self, entry):
        row = self.list.row(entry)
        self.candidates[row]["accepted"] = entry.checkState() == Qt.CheckState.Checked
        self.sync_texts()
        self.redraw()

    def set_all(self, checked):
        self.list.blockSignals(True)
        for row, candidate in enumerate(self.candidates):
            candidate["accepted"] = bool(checked)
            self.list.item(row).setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.list.blockSignals(False)
        self.sync_texts()
        self.redraw()

    def tick(self):
        view = self.window_.view
        stale = self.items and not all(view.alive(item) for item in self.items)
        if stale or self.drawn_page != self.window_.page:
            self.redraw()

    def clear_overlay(self):
        view = self.window_.view
        for item in self.items:
            if view.alive(item):
                view.scene().removeItem(item)
        self.items = []

    def redraw(self):
        self.clear_overlay()
        window = self.window_
        view = window.view
        self.drawn_page = window.page
        if not window.has_doc():
            return
        tokens = theme.current_tokens()
        current = self.list.currentRow()
        for row, candidate in enumerate(self.candidates):
            if candidate["page"] not in view.page_origin:
                continue
            rect = view.scene_rect(candidate["rect"], candidate["page"])
            if candidate["accepted"]:
                fill = QColor(tokens["accent"])
                fill.setAlpha(60 if row != current else 120)
                pen = QPen(QColor(tokens["accent"]), 2 if row == current else 1.5)
            else:
                fill = QColor(tokens["inkdisabled"])
                fill.setAlpha(25)
                pen = QPen(QColor(tokens["inkdisabled"]), 1, Qt.PenStyle.DashLine)
            item = view.scene().addRect(QRectF(rect), pen, QBrush(fill))
            item.setZValue(14)
            self.items.append(item)

    def create(self):
        chosen = self.accepted()
        if not chosen:
            return
        window = self.window_
        specs = [(c["page"], c["rect"], c["name"], c["kind"]) for c in chosen]
        self.close_panel()
        count = window.change(lambda: window.engine.add_fields(specs))
        notify(window, _("Se crearon {count} campos. Deshacer los quita todos a la vez.", count=count))

    def close_panel(self):
        self.watch.stop()
        self.clear_overlay()
        if getattr(self.window_, "detector", None) is self:
            self.window_.detector = None
        self.hide()
        self.deleteLater()


def open_detector(window):
    previous = getattr(window, "detector", None)
    if previous is not None:
        previous.close_panel()
    engine = window.engine
    taken = {f["name"] for f in engine.forms()}
    found = []
    for index in range(engine.page_count):
        page = engine.doc[index]
        for candidate in detect(page, taken):
            taken.add(candidate["name"])
            found.append(candidate)
    if not found:
        notify(window, _("No se detectaron campos en este documento."))
        return None
    window.detector = DetectorPanel(window, found)
    return window.detector
