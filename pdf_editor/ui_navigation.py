from __future__ import annotations

import bisect
import hashlib
import json
import math
import re
import time

import pymupdf as fitz
from PySide6.QtCore import QItemSelectionModel, QPoint, QPointF, QRectF, QTimer, Qt
from PySide6.QtGui import QColor, QIcon, QPen, QTransform
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QListWidgetItem, QToolBar, QToolButton, QVBoxLayout
from pathlib import Path

from . import __version__
from .lang import _, N_, ntext
from .pages_panel import COMMENTS_ROLE, LABEL_ROLE, ROTATION_ROLE
from .theme import current_tokens
from .ui_support import PAGE_MARGIN, pixmap_for

PAGE_GAP = 16
SEARCH_SYNC_PAGES = 60
SEARCH_BATCH_PAGES = 15
SEARCH_CACHE_SIZE = 8
RECENT_POSITIONS = 50
FULLSCREEN_BAR_MS = 2500
FIT_LOCK_SECONDS = 0.3
ZOOM_MODES = ("width", "page", "actual", "manual")
VIEW_LAYOUTS = ("single", "double", "continuous", "double_continuous")
CONTINUOUS_LAYOUTS = ("continuous", "double_continuous")


def search_pattern(query, case, whole):
    """Regular expression over the words of a page. Several words match with any spacing between them."""
    body = r"\s+".join(re.escape(part) for part in query.split())
    if whole:
        body = rf"(?<!\w){body}(?!\w)"
    return re.compile(body, 0 if case else re.IGNORECASE)


class FullscreenBar(QFrame):
    """Small bar at the top of the window in full-screen mode. It appears when the pointer reaches the top edge and hides by itself."""

    def __init__(self, window):
        super().__init__(window)
        self.setObjectName("FullscreenBar")
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 6, 8, 6)
        row.setSpacing(10)
        row.addWidget(QLabel(_("Pantalla completa · Esc para salir")))
        exit_button = QToolButton()
        exit_button.setText(_("Salir"))
        exit_button.setToolTip(_("Salir de pantalla completa (Esc)"))
        exit_button.setAccessibleName(_("Salir de pantalla completa"))
        exit_button.setCursor(Qt.CursorShape.PointingHandCursor)
        exit_button.clicked.connect(lambda _=False: window.toggle_fullscreen())
        row.addWidget(exit_button)
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.hide)
        self.hide()

    def show_for_a_while(self):
        self.adjustSize()
        self.move(max(0, (self.parentWidget().width() - self.width()) // 2), 8)
        self.raise_()
        self.show()
        self.hide_timer.start(FULLSCREEN_BAR_MS)


class UiNavigationMixin:
    """Zoom and view modes, page navigation, search, page memory, full screen and thumbnails."""

    def init_navigation_state(self):
        self.search_results = []
        self.search_index = -1
        self.search_key = None
        self.search_state = None
        self.search_cache = {}
        self.search_items = []
        self.search_pending_step = 1
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self.search_tick)
        self.search_debounce = QTimer(self)
        self.search_debounce.setSingleShot(True)
        self.search_debounce.setInterval(220)
        self.search_debounce.timeout.connect(self.find_text)
        self.zoom_mode = self.settings.value("zoomMode", "width", type=str)
        if self.zoom_mode not in ZOOM_MODES:
            self.zoom_mode = "width"
        self.view_layout = self.settings.value("viewLayout", "single", type=str)
        if self.view_layout not in VIEW_LAYOUTS:
            self.view_layout = "single"
        self.view_angle = 0
        self.view_doc = None
        self.pending_page_scroll = False
        self.continuous_visible = ()
        self.fit_locked_until = 0.0
        self.fit_timer = QTimer(self)
        self.fit_timer.setSingleShot(True)
        self.fit_timer.setInterval(60)
        self.fit_timer.timeout.connect(self.apply_current_fit)
        self.fullscreen_bar = FullscreenBar(self)
        self.fullscreen_restore = []
        self.fullscreen_sizes = []

    def fit_tab_width(self):
        bar = self.left_tabs.tabBar()
        self.left_tabs.ensurePolished()
        bar.ensurePolished()
        self.pages_min = max(176, min(300, bar.sizeHint().width() + 2))
        self.left_tabs.setMinimumWidth(self.pages_min)
        if not self.pages_collapsed:
            self.pages_panel.setMinimumWidth(self.pages_min)

    def toggle_pages(self):
        if self.pages_collapsed:
            self.fit_tab_width()
        sizes = self.splitter.sizes()
        rail = sizes[0] if sizes and sizes[0] > 0 else 260
        total = sum(sizes) or self.splitter.width() or self.width()
        if not self.pages_collapsed and len(sizes) > 2 and sizes[2] >= 176:
            self.pages_width = sizes[2]
        self.pages_collapsed = not self.pages_collapsed
        self.left_tabs.setVisible(not self.pages_collapsed)
        self.pages_label.setVisible(not self.pages_collapsed)
        self.pages_panel.setMinimumWidth(38 if self.pages_collapsed else self.pages_min)
        self.pages_panel.setMaximumWidth(38 if self.pages_collapsed else 300)
        self.update_pages_toggle()
        if self.pages_collapsed:
            pages = 38
        else:
            pages = max(self.pages_min, min(getattr(self, "pages_width", 250), 300, total - rail - 240))
        self.splitter.setSizes([rail, max(1, total - rail - pages), pages])

    def refresh(self):
        self.adopt_idle_engine()
        self.restore_view_for_document()
        selected = self.selected_pages() if hasattr(self, "thumbnails") and self.thumbnails.count() else [self.page]
        exists = self.has_doc()
        for action in self.doc_actions:
            action.setEnabled(exists)
        self.update_history_actions()
        self.page_spin.setEnabled(exists)
        for button in self.mode_buttons.values():
            button.setEnabled(exists)
        self.stack.setCurrentIndex(1 if exists else 0)
        self.page_bar.setEnabled(exists)
        self.thumbnails.blockSignals(True)
        self.bookmark_list.clear()
        self.search_cache = {}
        keep_scroll = None
        if exists and not self.pending_page_scroll:
            keep_scroll = (self.page, self.zoom.value(), self.view.horizontalScrollBar().value(), self.view.verticalScrollBar().value())
        if exists:
            self.page = max(0, min(self.page, self.engine.page_count - 1))
            labels = self.engine.page_labels()
            self.sync_thumbnails(labels, selected)
            self.bookmark_list.set_toc(self.engine.bookmarks())
            self.page_spin.blockSignals(True)
            self.page_spin.setRange(1, self.engine.page_count)
            self.page_spin.setValue(self.page + 1)
            self.page_spin.blockSignals(False)
            self.total.setText(f" / {self.engine.page_count}   ")
            self.render_page()
            if keep_scroll and keep_scroll[:2] == (self.page, self.zoom.value()):
                self.view.horizontalScrollBar().setValue(keep_scroll[2])
                self.view.verticalScrollBar().setValue(keep_scroll[3])
            QTimer.singleShot(0, self.load_thumbnails)
        else:
            self.thumbnails.clear()
            self.thumb_prints = []
            self.view.reset_transient()
            self.search_results = []
            self.search_items = []
            self.view.reset_lazy()
            self.view.scene().clear()
            self.total.setText(" / 0   ")
            self.refresh_recent()
        self.thumbnails.blockSignals(False)
        if exists and self.search_toolbar.isVisible() and self.current_search_key() and not self.search_results and self.search_state is None:
            # The document changed while the search bar was open: search again so the highlights follow the edit.
            self.find_text(navigate=False)
        self.update_search_status()
        self.label_tool_letters()
        self.refresh_tab_bar()
        name = Path(self.engine.path).name if self.engine.path else _("Sin título")
        self.setWindowTitle(f"{'● ' if self.engine.dirty else ''}{name + ' — ' if exists else ''}TrazoPDF {__version__}")

    THUMB_BATCH = 12

    def page_fingerprint(self, index):
        """Cheap digest of what a page draws; equal digests mean the thumbnail is still valid."""
        doc = self.engine.doc
        page = doc[index]
        digest = hashlib.md5(usedforsecurity=False)
        digest.update(repr((page.rect, page.rotation, doc.xref_object(page.xref, compressed=True))).encode())
        digest.update(page.read_contents())
        for annot in page.annots() or []:
            digest.update(doc.xref_object(annot.xref, compressed=True).encode())
        for image in page.get_images(full=True):
            digest.update(doc.xref_object(image[0], compressed=True).encode())
        return digest.hexdigest()

    def sync_thumbnails(self, labels, selected):
        """Brings the page list up to date, keeping items and rendered thumbnails of pages that did not change."""
        thumbnails = self.thumbnails
        if thumbnails.settings is None:
            thumbnails.bind_settings(self.settings)
        count = self.engine.page_count
        old_prints = getattr(self, "thumb_prints", [])
        try:
            prints = [self.page_fingerprint(index) for index in range(count)]
        except Exception:
            prints = [None] * count
        icons = {}
        for row, print_ in enumerate(old_prints[:thumbnails.count()]):
            icon = thumbnails.item(row).icon()
            if print_ is not None and not icon.isNull():
                icons.setdefault(print_, icon)
        reuse = thumbnails.count() == count
        if not reuse:
            thumbnails.clear()
        for index in range(count):
            item = thumbnails.item(index) if reuse else QListWidgetItem()
            item.setText(_("Página {n}", n=index + 1))
            item.setData(Qt.ItemDataRole.UserRole, labels[index])
            self.mark_thumbnail(item, index, labels[index])
            item.setSizeHint(thumbnails.item_size())
            icon = icons.get(prints[index])
            if icon is not None:
                item.setIcon(icon)
            elif not item.icon().isNull():
                item.setIcon(QIcon())
            if not reuse:
                thumbnails.addItem(item)
        self.thumb_prints = prints
        if thumbnails.currentRow() != self.page:
            thumbnails.setCurrentRow(self.page, QItemSelectionModel.SelectionFlag.NoUpdate)
        wanted = {index for index in selected if index < count}
        for index in range(count):
            item = thumbnails.item(index)
            if item.isSelected() != (index in wanted):
                item.setSelected(index in wanted)

    def mark_thumbnail(self, item, index, label):
        """Stores what the badges show: annotation count, rotation and custom label."""
        try:
            page = self.engine.doc[index]
            comments = sum(1 for annot in page.annots() or [] if annot.type[0] != 20)
            rotation = page.rotation
        except Exception:
            comments, rotation = 0, 0
        item.setData(COMMENTS_ROLE, comments)
        item.setData(ROTATION_ROLE, rotation)
        item.setData(LABEL_ROLE, "" if str(label) == str(index + 1) else str(label))

    def load_thumbnails(self):
        """Renders the visible thumbnails (plus a margin) in batches, so long documents stay responsive."""
        if not self.has_doc():
            return
        count = self.engine.page_count
        viewport = self.thumbnails.viewport().rect()
        first = self.thumbnails.indexAt(viewport.topLeft()).row()
        last = self.thumbnails.indexAt(viewport.bottomLeft()).row()
        first = max(0, first)
        last = count - 1 if last < 0 else min(count - 1, last)
        width, height = self.thumbnails.thumb_size.width(), self.thumbnails.thumb_size.height()
        ratio = self.view.devicePixelRatioF()
        loaded = 0
        pending = False
        for index in range(max(0, first - 2), min(count, last + 3)):
            item = self.thumbnails.item(index)
            if item is None or not item.icon().isNull():
                continue
            if loaded == self.THUMB_BATCH:
                pending = True
                break
            page = self.engine.doc[index]
            pix = self.engine.render(index, min(8, width / page.rect.width, height / page.rect.height) * ratio)
            thumbnail = pixmap_for(pix)
            thumbnail.setDevicePixelRatio(ratio)
            item.setIcon(QIcon(thumbnail))
            loaded += 1
        if pending:
            QTimer.singleShot(0, self.load_thumbnails)

    # Zoom and view modes ---------------------------------------------------------

    def is_continuous(self):
        return self.view_layout in CONTINUOUS_LAYOUTS

    def row_pages(self):
        """The current page and, in a two-page layout, the page beside it."""
        count = self.engine.page_count
        if self.view_layout in ("double", "double_continuous") and count >= 2:
            left = self.page - self.page % 2
            return [left, left + 1] if left + 1 < count else [left]
        return [self.page]

    def visible_pages(self):
        """Pages drawn in the view. In a continuous layout these are the pages on screen."""
        if self.is_continuous() and self.has_doc() and hasattr(self, "view"):
            on_screen = self.view.onscreen_pages()
            if on_screen:
                return on_screen
        return self.row_pages()

    def fit_zoom(self, mode):
        """Zoom percentage that fits the visible pages to the width (or to the page). Scrollbars do not change the result."""
        if mode == "actual":
            return 100
        view = self.view
        vbar, hbar = view.verticalScrollBar(), view.horizontalScrollBar()
        width = view.viewport().width() + (vbar.width() if vbar.isVisible() else 0)
        height = view.viewport().height() + (hbar.height() if hbar.isVisible() else 0)
        rects = [self.engine.doc[index].rect for index in self.row_pages()]
        total = sum(rect.width for rect in rects)
        gap = PAGE_GAP * (len(rects) - 1)
        scale = (width - 2 * PAGE_MARGIN - 8 - gap) / total
        if mode == "page":
            scale = min(scale, (height - 2 * PAGE_MARGIN - 8) / max(rect.height for rect in rects))
        return math.floor(max(0.01, scale) / 1.25 * 100)

    def set_zoom_value(self, value):
        self.zoom.blockSignals(True)
        self.zoom.setValue(max(self.zoom.minimum(), min(self.zoom.maximum(), round(value))))
        self.zoom.blockSignals(False)

    def apply_fit(self, mode):
        if not self.has_doc() or not self.view.commit_editor():
            return
        self.zoom_mode = mode
        self.set_zoom_value(self.fit_zoom(mode))
        self.render_page()
        self.after_zoom_change()

    def apply_current_fit(self):
        # A text box being edited is not re-rendered by a deferred resize fit; the fit is recalculated on the next resize.
        if not self.has_doc() or self.zoom_mode not in ("width", "page") or self.view.editor is not None:
            return
        if round(self.fit_zoom(self.zoom_mode)) != self.zoom.value():
            self.apply_fit(self.zoom_mode)

    def view_resized(self):
        """The fit modes follow the window size; the timer waits until a drag of the splitter or the window settles."""
        if self.has_doc() and self.zoom_mode in ("width", "page"):
            self.fit_timer.start()

    def fit_locked(self):
        return time.monotonic() < self.fit_locked_until

    def fit_width(self):
        if self.has_doc() and not self.fit_locked():
            self.apply_fit("width")

    def fit_page(self):
        if self.has_doc() and not self.fit_locked():
            self.apply_fit("page")

    def actual_size(self):
        if self.has_doc() and self.view.commit_editor():
            self.zoom_mode = "actual"
            self.set_zoom_value(100)
            self.render_page()
            self.after_zoom_change()

    def set_zoom(self, value):
        if self.view.commit_editor():
            self.zoom_mode = "manual"
            self.zoom.setValue(int(value))
            self.after_zoom_change()

    def zoom_changed(self, value):
        if not self.view.commit_editor():
            self.zoom.blockSignals(True)
            self.zoom.setValue(round(self.view.scale_factor / 1.25 * 100))
            self.zoom.blockSignals(False)
            return
        if self.has_doc():
            self.zoom_mode = "manual"
            self.render_page()
            self.after_zoom_change()

    def after_zoom_change(self):
        self.settings.setValue("zoomMode", self.zoom_mode)
        if self.zoom_mode == "manual":
            self.settings.setValue("zoomPercent", self.zoom.value())
        self.sync_view_actions()

    def set_view_layout(self, layout):
        if layout == self.view_layout:
            self.sync_view_actions()
            return
        self.view_layout = layout
        self.settings.setValue("viewLayout", layout)
        if self.has_doc() and self.view.commit_editor():
            if self.zoom_mode in ("width", "page"):
                self.set_zoom_value(self.fit_zoom(self.zoom_mode))
            # The page in view stays in view when the layout changes.
            self.pending_page_scroll = True
            self.render_page()
        self.sync_view_actions()

    def sync_view_actions(self):
        if not hasattr(self, "view_actions"):
            return
        actions = self.view_actions
        for mode, key in (("width", "fit_width"), ("page", "fit_page"), ("actual", "actual")):
            actions[key].setChecked(self.zoom_mode == mode)
        for layout in VIEW_LAYOUTS:
            actions[layout].setChecked(self.view_layout == layout)
        actions["fullscreen"].setChecked(self.isFullScreen())

    def restore_view_for_document(self):
        """Applies the remembered page and zoom when a different document is shown."""
        doc = self.engine.doc if self.has_doc() else None
        if doc is self.view_doc:
            return
        self.view_doc = doc
        if doc is None:
            return
        self.pending_page_scroll = True
        saved = self.saved_position(self.engine.path)
        if saved is not None and 0 <= saved < self.engine.page_count:
            self.page = saved
        if not self.isVisible() or self.zoom_mode == "width":
            # Width is what open_path and new_file already ask for right after loading, so nothing changes here.
            return
        # The remembered page fit, percentage or real size wins over the fit-to-width those callers ask for.
        self.fit_locked_until = time.monotonic() + FIT_LOCK_SECONDS
        if self.zoom_mode == "manual":
            self.set_zoom_value(self.settings.value("zoomPercent", 100, type=int))
        elif self.zoom_mode == "actual":
            self.set_zoom_value(100)
        else:
            self.set_zoom_value(self.fit_zoom(self.zoom_mode))

    def rotate_view(self):
        """Turns the view only; the document is not changed."""
        self.view_angle = (self.view_angle + 90) % 360
        self.view.setTransform(QTransform().rotate(self.view_angle))
        self.statusBar().showMessage(_("Vista girada {angle} °. El documento no cambia.", angle=self.view_angle))

    # Page memory -----------------------------------------------------------------

    def saved_positions(self):
        try:
            data = json.loads(self.settings.value("lastPages", "{}", type=str) or "{}")
        except (TypeError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def saved_position(self, path):
        if not path:
            return None
        value = self.saved_positions().get(str(Path(path)))
        return value if isinstance(value, int) else None

    def remember_position(self):
        if not self.has_doc() or not self.engine.path:
            return
        data = self.saved_positions()
        key = str(Path(self.engine.path))
        data.pop(key, None)
        data[key] = self.page
        while len(data) > RECENT_POSITIONS:
            data.pop(next(iter(data)))
        self.settings.setValue("lastPages", json.dumps(data))

    # Pages -----------------------------------------------------------------------

    MODE_NAMES = {"select": N_("Seleccionar texto"), "edit": N_("Editar PDF"), "text": N_("Texto"), "hand": N_("Mano"), "replace": N_("Editar texto"), "link": N_("Enlace"), "redact": N_("Censurar"), "ink": N_("Dibujar"), "stamp": N_("Sello"), "highlight": N_("Resaltar"), "underline": N_("Subrayar"), "strikeout": N_("Tachar"), "rectangle": N_("Rectángulo"), "ellipse": N_("Elipse"), "note": N_("Nota"), "field": N_("Campo"), "fill": N_("Rellenar y firmar")}

    def update_page_status(self):
        """Permanent part of the status bar: page, size and tool. Temporary messages are not touched."""
        label = getattr(self, "page_status", None)
        if label is None:
            return
        if not self.has_doc():
            label.setText("")
            return
        page = self.engine.doc[self.page]
        label.setText(_("Página {n} de {total}  ·  {width} × {height} pt  ·  {mode}", n=self.page + 1, total=self.engine.page_count, width=f"{page.rect.width:.0f}", height=f"{page.rect.height:.0f}", mode=_(self.MODE_NAMES.get(self.view.mode, N_('Área')))))
        label.setToolTip(self.mode_help())

    def show_message_history(self):
        """Light popup (not modal) with the last status messages, newest first."""
        old = getattr(self, "history_popup", None)
        if old is not None:
            old.close()
        popup = QFrame(self, Qt.WindowType.Popup)
        popup.setObjectName("MessageHistory")
        popup.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        layout = QVBoxLayout(popup)
        layout.setContentsMargins(10, 8, 10, 8)
        title = QLabel(_("Últimos mensajes"))
        title.setObjectName("WelcomeHeading")
        layout.addWidget(title)
        entries = list(reversed(self.statusBar().history))
        if not entries:
            layout.addWidget(QLabel(_("Aún no hay mensajes.")))
        for stamp, text in entries:
            row = QLabel(f"{time.strftime('%H:%M:%S', time.localtime(stamp))}  ·  {text}")
            row.setWordWrap(True)
            row.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(row)
        popup.setFixedWidth(min(560, max(320, self.width() - 40)))
        popup.adjustSize()
        bar = self.statusBar()
        popup.move(bar.mapToGlobal(bar.rect().topLeft()) + QPoint(8, -popup.height()))
        self.history_popup = popup
        popup.show()
        return popup

    def render_page(self):
        if not self.has_doc() or not hasattr(self, "view"):
            return
        if self.is_continuous():
            return self.render_continuous()
        doc = self.engine.doc
        scale = self.zoom.value() / 100 * 1.25
        view = self.view
        view.scale_factor = scale
        scene = view.scene()
        view.reset_transient()
        self.search_items = []
        self.pending_page_scroll = False
        view.reset_lazy()
        scene.clear()
        ratio = view.devicePixelRatioF()
        positions = {}
        x = 0.0
        for index in self.row_pages():
            page = doc[index]
            raster = min(scale * ratio, 16, math.sqrt(16_000_000 / max(1, page.rect.width * page.rect.height)))
            rendered = pixmap_for(self.engine.render(index, raster))
            rendered.setDevicePixelRatio(raster / scale)
            item = scene.addPixmap(rendered)
            item.setPos(x, 0)
            rect = QRectF(x, 0, page.rect.width * scale, page.rect.height * scale)
            positions[index] = (x, rect)
            x += rect.width() + PAGE_GAP
        current_x, current_rect = positions[self.page]
        view.page_offset = QPointF(current_x, 0)
        view.page_rect = current_rect
        view.page_rects = [rect for _, rect in positions.values()]
        view.companion_rects = [(index, rect) for index, (_, rect) in positions.items() if index != self.page]
        view.page_origin = {index: QPointF(origin, 0) for index, (origin, _) in positions.items()}
        bounds = QRectF(current_rect)
        for _pos, rect in positions.values():
            bounds = bounds.united(rect)
        scene.setSceneRect(bounds.adjusted(-PAGE_MARGIN, -PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN))
        view.populate_text()
        self.refresh_search_highlights()
        self.update_page_status()

    # Continuous layouts ----------------------------------------------------------

    def continuous_rows(self):
        """Pages per row: one page each in Desplazamiento continuo, pairs in Dos páginas continuo."""
        count = self.engine.page_count
        step = 2 if self.view_layout == "double_continuous" else 1
        return [list(range(start, min(start + step, count))) for start in range(0, count, step)]

    def continuous_geometry(self, scale):
        """Top-left corner and rectangle of every page in scene units. Rows are centered on the widest row."""
        doc = self.engine.doc
        rows = []
        for row in self.continuous_rows():
            sizes = [(index, doc[index].rect.width * scale, doc[index].rect.height * scale) for index in row]
            width = sum(w for _, w, _ in sizes) + PAGE_GAP * (len(sizes) - 1)
            rows.append((sizes, width, max(h for _, _, h in sizes)))
        widest = max(width for _, width, _ in rows)
        origins, rects = {}, {}
        y = 0.0
        for sizes, width, height in rows:
            x = (widest - width) / 2
            for index, w, h in sizes:
                origins[index] = QPointF(x, y)
                rects[index] = QRectF(x, y, w, h)
                x += w + PAGE_GAP
            y += height + PAGE_GAP
        return origins, rects

    def render_continuous(self):
        """Lays out every page in one scene. Only the pages near the view are drawn, the others stay gray placeholders."""
        view = self.view
        scale = self.zoom.value() / 100 * 1.25
        old_scale = view.scale_factor
        center = view.mapToScene(view.viewport().rect().center()) if view.page_geometry else None
        view.scale_factor = scale
        view.reset_transient()
        self.search_items = []
        origins, rects = self.continuous_geometry(scale)
        view.build_continuous(origins, rects, current_tokens()["border"])
        bounds = QRectF()
        for rect in rects.values():
            bounds = bounds.united(rect)
        view.scene().setSceneRect(bounds.adjusted(-PAGE_MARGIN, -PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN))
        view.page_offset = origins[self.page]
        view.page_rect = rects[self.page]
        view.populate_text()
        if center is not None and old_scale and abs(scale - old_scale) > 1e-9:
            # A zoom keeps the middle of the view where it was.
            ratio = scale / old_scale
            view.centerOn(QPointF(center.x() * ratio, center.y() * ratio))
        if self.pending_page_scroll:
            self.pending_page_scroll = False
            self.scroll_to_page(self.page)
        self.continuous_view_moved()
        self.refresh_search_highlights()
        self.update_page_status()

    def render_continuous_pixmap(self, index):
        scale = self.view.scale_factor
        page = self.engine.doc[index]
        raster = min(scale * self.view.devicePixelRatioF(), 16, math.sqrt(16_000_000 / max(1, page.rect.width * page.rect.height)))
        rendered = pixmap_for(self.engine.render(index, raster))
        rendered.setDevicePixelRatio(raster / scale)
        return rendered

    def continuous_view_moved(self):
        """Runs after the view scrolls (throttled by a timer). Picks the current page, draws the pages near the view and drops the rest."""
        view = self.view
        if not self.has_doc() or not self.is_continuous() or not view.page_geometry:
            return
        on_screen = view.onscreen_pages()
        if not on_screen:
            return
        if view.editor is None:
            # A page opened from the page box or search stays current while the view is where it was put.
            pinned = view.pin_page is not None and view.pin_page in on_screen and abs(view.verticalScrollBar().value() - view.pin_value) <= 1
            target = view.pin_page if pinned else None
            if target is None:
                view.pin_page = None
                target = view.most_visible_page(on_screen)
            if target is not None and target != self.page:
                self.set_current_page(target)
        count = self.engine.page_count
        wanted = list(range(max(0, min(on_screen) - 1), min(count, max(on_screen) + 2)))
        if self.page not in wanted:
            wanted.append(self.page)
        if view.sync_lazy_pages(wanted, self.render_continuous_pixmap):
            view.schedule_lazy()
        visible = tuple(on_screen)
        if visible != self.continuous_visible:
            self.continuous_visible = visible
            self.refresh_search_highlights()

    def set_current_page(self, index):
        """Makes another page current without redrawing the scene (continuous layouts)."""
        changed = index != self.page
        self.page = index
        self.page_spin.blockSignals(True)
        self.page_spin.setValue(index + 1)
        self.page_spin.blockSignals(False)
        self.thumbnails.blockSignals(True)
        self.thumbnails.setCurrentRow(index, QItemSelectionModel.SelectionFlag.NoUpdate)
        self.thumbnails.blockSignals(False)
        self.view.set_current_page(index)
        self.update_page_status()
        if changed:
            self.remember_position()

    def scroll_to_page(self, index):
        """Puts the top of a page near the top of the view and keeps that page current while the view settles."""
        rect = self.view.page_geometry.get(index)
        if rect is None:
            return
        self.view.centerOn(QPointF(rect.center().x(), rect.top() - PAGE_MARGIN + self.view.viewport().height() / 2))
        self.view.pin_page = index
        self.view.pin_value = self.view.verticalScrollBar().value()

    def show_continuous_page(self, page):
        self.set_current_page(page)
        self.scroll_to_page(page)
        self.continuous_view_moved()

    def goto(self, page):
        if not self.has_doc() or page < 0 or page >= self.engine.page_count:
            return
        if page != self.page and not self.view.commit_editor():
            return
        if self.is_continuous():
            if len(self.view.page_geometry) != self.engine.page_count:
                self.page = page
                self.pending_page_scroll = True
                self.render_page()
                return
            self.show_continuous_page(page)
            return
        changed = page != self.page
        self.page = page
        self.page_spin.blockSignals(True)
        self.page_spin.setValue(page + 1)
        self.page_spin.blockSignals(False)
        self.thumbnails.blockSignals(True)
        self.thumbnails.setCurrentRow(page, QItemSelectionModel.SelectionFlag.NoUpdate)
        self.thumbnails.blockSignals(False)
        self.render_page()
        if changed:
            self.remember_position()

    def turn_page(self, delta):
        """Moves to the previous (-1) or next (1) page; in two-page view it moves by one spread. Returns True when the page changed."""
        if not self.has_doc():
            return False
        if self.view_layout in ("double", "double_continuous"):
            base = self.page - self.page % 2
            target = base + 2 if delta > 0 else base - 2
        else:
            target = self.page + delta
        if target < 0 or target >= self.engine.page_count:
            return False
        self.goto(target)
        if self.page != target:
            return False
        if self.is_continuous():
            return True
        bar = self.view.verticalScrollBar()
        bar.setValue(bar.minimum() if delta > 0 else bar.maximum())
        return True

    # Full screen -----------------------------------------------------------------

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.exit_fullscreen()
        else:
            self.enter_fullscreen()

    def enter_fullscreen(self):
        self.fullscreen_sizes = self.splitter.sizes()
        self.fullscreen_restore = [widget for widget in [self.menuBar(), self.statusBar(), self.splitter.widget(0), self.pages_panel, *self.findChildren(QToolBar)]
                                   if widget.isVisible()]
        for widget in self.fullscreen_restore:
            widget.hide()
        self.showFullScreen()
        self.sync_view_actions()
        self.show_fullscreen_bar()

    def exit_fullscreen(self):
        self.fullscreen_bar.hide()
        self.showNormal()
        for widget in self.fullscreen_restore:
            widget.show()
        self.fullscreen_restore = []
        if self.fullscreen_sizes and sum(self.fullscreen_sizes) > 0:
            self.splitter.setSizes(self.fullscreen_sizes)
        self.sync_view_actions()

    def show_fullscreen_bar(self):
        if self.isFullScreen():
            self.fullscreen_bar.show_for_a_while()

    # Search ----------------------------------------------------------------------

    def current_search_key(self):
        query = self.search.text().strip()
        if not query:
            return None
        return (query, self.search_bar.case_button.isChecked(), self.search_bar.word_button.isChecked())

    def open_search(self):
        self.search_toolbar.show()
        self.search_bar.focus_field()

    def close_search(self):
        self.search_timer.stop()
        self.search_debounce.stop()
        self.search_state = None
        self.search_results = []
        self.search_index = -1
        self.search_key = None
        self.search_toolbar.hide()
        self.refresh_search_highlights()
        self.update_search_status()
        if hasattr(self, "view"):
            self.view.setFocus()

    def search_text_changed(self, text):
        if not text.strip():
            self.search_debounce.stop()
            self.find_text()
        else:
            self.search_debounce.start()

    def search_options_changed(self):
        self.find_text()

    def find_text(self, navigate=True):
        """Looks for the text in the field. Short documents are searched at once; long ones in batches on a timer."""
        self.search_timer.stop()
        self.search_debounce.stop()
        self.search_state = None
        self.search_results = []
        self.search_index = -1
        self.search_key = self.current_search_key()
        if not self.has_doc() or self.search_key is None:
            self.search_key = None
            self.refresh_search_highlights()
            self.update_search_status()
            return
        if self.search_key in self.search_cache:
            self.search_results = list(self.search_cache[self.search_key])
            self.finish_search(navigate)
            return
        query, case, whole = self.search_key
        self.search_state = {"next": 0, "pattern": search_pattern(query, case, whole), "navigate": navigate}
        if self.engine.page_count <= SEARCH_SYNC_PAGES:
            self.search_tick(self.engine.page_count)
        else:
            self.search_timer.start(0)
            self.update_search_status()

    def search_tick(self, limit=SEARCH_BATCH_PAGES):
        state = self.search_state
        if state is None or not self.has_doc():
            self.search_state = None
            return
        count = self.engine.page_count
        stop = min(count, state["next"] + limit)
        for index in range(state["next"], stop):
            self.search_results.extend(self.page_hits(index, state["pattern"]))
        state["next"] = stop
        if stop < count:
            self.refresh_search_highlights()
            self.update_search_status()
            self.search_timer.start(0)
            return
        self.search_state = None
        self.cache_search(self.search_key, list(self.search_results))
        self.finish_search(state["navigate"])

    def page_hits(self, index, pattern):
        """Matches of the pattern on one page, as one rectangle per line of text."""
        words = self.engine.doc[index].get_text("words")
        if not words:
            return []
        starts = []
        position = 0
        for word in words:
            starts.append(position)
            position += len(word[4]) + 1
        text = " ".join(word[4] for word in words)
        hits = []
        for match in pattern.finditer(text):
            first = bisect.bisect_right(starts, match.start()) - 1
            last = bisect.bisect_right(starts, match.end() - 1) - 1
            lines = {}
            for word in words[first:last + 1]:
                rect = fitz.Rect(word[:4])
                key = (word[5], word[6])
                lines[key] = lines[key] | rect if key in lines else rect
            hits.extend((index, rect) for rect in lines.values())
        return hits

    def cache_search(self, key, results):
        self.search_cache[key] = results
        while len(self.search_cache) > SEARCH_CACHE_SIZE:
            self.search_cache.pop(next(iter(self.search_cache)))

    def finish_search(self, navigate=True):
        self.refresh_search_highlights()
        if navigate and self.search_results and self.search_index < 0:
            step, self.search_pending_step = self.search_pending_step, 1
            self.search_step(step)
        self.update_search_status()

    def search_navigate(self, forward=True):
        """Next (True) or previous (False) match. Opens the bar and searches again when the text changed."""
        if not self.has_doc():
            return
        if not self.search_toolbar.isVisible():
            self.open_search()
        delta = 1 if forward else -1
        if self.current_search_key() != self.search_key:
            self.search_pending_step = delta
            self.find_text(navigate=True)
            return
        self.search_step(delta)

    def search_step(self, delta):
        if not self.has_doc() or not self.search_results:
            self.update_search_status()
            return
        count = len(self.search_results)
        if self.search_index < 0:
            self.search_index = 0 if delta > 0 else count - 1
        else:
            self.search_index = (self.search_index + delta) % count
        page, rect = self.search_results[self.search_index]
        if page != self.page:
            self.goto(page)
        self.refresh_search_highlights()
        target = self.page_scene_rect(page, rect)
        if target is not None:
            self.view.centerOn(target.center())
        self.update_search_status()

    def page_scene_rect(self, index, rect):
        origin = self.view.page_origin.get(index)
        if origin is None:
            return None
        scale = self.view.scale_factor
        r = fitz.Rect(rect) * self.engine.doc[index].rotation_matrix
        return QRectF(origin.x() + r.x0 * scale, origin.y() + r.y0 * scale, r.width * scale, r.height * scale)

    def refresh_search_highlights(self):
        """Draws every match of the visible pages; the current match is stronger."""
        if not hasattr(self, "view"):
            return
        scene = self.view.scene()
        for item in self.search_items:
            if item.scene() is scene:
                scene.removeItem(item)
        self.search_items = []
        if not self.has_doc() or not self.search_results:
            return
        visible = set(self.visible_pages())
        for position, (index, rect) in enumerate(self.search_results):
            if index not in visible:
                continue
            target = self.page_scene_rect(index, rect)
            if target is None:
                continue
            current = position == self.search_index
            pen = QPen(QColor("#d49a1b"), 1.2) if current else QPen(Qt.PenStyle.NoPen)
            fill = QColor(255, 150, 0, 150) if current else QColor(255, 226, 80, 110)
            item = scene.addRect(target, pen, fill)
            item.setZValue(4 if current else 3)
            self.search_items.append(item)

    def update_search_status(self):
        if not hasattr(self, "search_bar"):
            return
        count = len(self.search_results)
        if self.search_key is None:
            text, missing = "", False
        elif self.search_state is not None:
            done = round(100 * self.search_state["next"] / max(1, self.engine.page_count))
            text, missing = _("Buscando… {done} %", done=done), False
        elif count == 0:
            text, missing = _("Sin resultados"), True
        elif self.search_index < 0:
            text, missing = _("{count} coincidencias", count=count), False
        else:
            text, missing = _("{n} de {count}", n=self.search_index + 1, count=count), False
        moves = count > 0
        self.search_bar.set_status(text, moves, missing)
        self.toolbar_prev.setEnabled(moves)
        self.toolbar_next.setEnabled(moves)

    # Replace ---------------------------------------------------------------------

    def open_replace(self):
        self.open_search()
        self.search_bar.set_replace_mode(True)

    def replace_blocked(self):
        """Reason why the text cannot be replaced in this document, or None."""
        engine = self.engine
        if engine.has_restrictions and not engine.has_owner_rights:
            return _("Este documento tiene restricciones de edición. Introduce la contraseña de propietario para poder reemplazar texto.")
        try:
            flags = engine.doc.get_sigflags()
            signed = flags > 0 and bool(flags & 1)
        except Exception:
            signed = False
        if signed:
            return _("Este documento está firmado digitalmente. Reemplazar texto invalidaría la firma; trabaja sobre una copia sin firmar.")
        return None

    def replace_message(self, plan_totals, done):
        notes = []
        if plan_totals["nofit"]:
            notes.append(_("{n} no caben en su línea y se dejaron sin cambiar", n=plan_totals['nofit']))
        if plan_totals["rotated"]:
            notes.append(_("{n} están en texto girado y no se cambiaron", n=plan_totals['rotated']))
        if plan_totals["across"]:
            notes.append(_("{n} abarcan estilos o líneas distintos y no se cambiaron", n=plan_totals['across']))
        if plan_totals["font"]:
            notes.append(_("se usó una fuente estándar parecida porque la original no está disponible"))
        if plan_totals["charset"]:
            notes.append(_("algunos caracteres no existen en la fuente estándar y se dibujaron con otra"))
        text = ntext(done, "{n} reemplazo", "{n} reemplazos")
        return text + (" · " + "; ".join(notes) if notes else "")

    def apply_replacements(self, pages, only=None):
        """Replaces on the given pages as one undo step. Returns (done, totals) or None when nothing could be done."""
        from .search_bar import plan_replacements
        from .toast import notify
        reason = self.replace_blocked()
        if reason:
            notify(self, reason, kind="error")
            return None
        query, case, whole = self.search_key
        pattern = search_pattern(query, case, whole)
        replacement = self.search_bar.replace_field.text()
        engine = self.engine
        totals = {"nofit": 0, "rotated": 0, "across": 0, "font": False, "charset": False}
        done = 0
        start = len(engine._undo)
        for index in pages:
            plan = plan_replacements(engine.doc[index], pattern, replacement, only)
            for key in ("nofit", "rotated", "across"):
                totals[key] += plan[key]
            for edit in plan["edits"]:
                engine.replace_text(index, edit["rect"], edit["text"], edit["size"], edit["color"], target_rect=edit["target"], fontname=edit["font"])
            if plan["edits"]:
                totals["font"] = totals["font"] or plan["font"]
                totals["charset"] = totals["charset"] or plan["charset"]
            done += plan["count"] if plan["edits"] else 0
        # Every edit pushed its own snapshot; keep the first one so a single Deshacer restores the document.
        if len(engine._undo) > start + 1:
            del engine._undo[start + 1:]
        return done, totals

    def replace_all(self):
        if not self.has_doc() or self.search_key is None or not self.view.commit_editor():
            return
        if self.search_state is not None:
            return
        result = self.run(lambda: self.apply_replacements(range(self.engine.page_count)))
        self.finish_replace(result)

    def replace_current(self):
        if not self.has_doc() or not self.view.commit_editor():
            return
        if self.current_search_key() != self.search_key:
            self.find_text()
        if self.search_key is None or self.search_state is not None or not self.search_results:
            return
        if self.search_index < 0:
            self.search_index = 0
        page, rect = self.search_results[self.search_index]
        position = self.search_index
        result = self.run(lambda: self.apply_replacements([page], fitz.Rect(rect)))
        self.finish_replace(result, position)

    def finish_replace(self, result, position=None):
        from .toast import notify
        if result is None:
            return
        done, totals = result
        label = ntext(done, "{n} reemplazo", "{n} reemplazos")
        if done:
            self.change(lambda: None)
            self.search_bar.replace_count.setText(label)
            notify(self, self.replace_message(totals, done), actions=[(_("Deshacer"), self.undo)])
            if position is not None and self.search_results and self.search_state is None:
                self.search_index = min(position, len(self.search_results)) - 1
                self.search_step(1)
        else:
            self.search_bar.replace_count.setText(_("0 reemplazos"))
            notify(self, self.replace_message(totals, 0) if any(totals[k] for k in ("nofit", "rotated", "across")) else _("No se reemplazó ninguna coincidencia"))

    def next_result(self):
        self.search_navigate(True)

    def prev_result(self):
        self.search_navigate(False)

    def label_tool_letters(self):
        """Adds the single-letter shortcut to each rail tool tooltip (once)."""
        if getattr(self, "_tool_letters_done", False) or not hasattr(self, "mode_buttons"):
            return
        from .canvas import TOOL_LETTERS
        letters = {mode: letter for letter, mode in TOOL_LETTERS.items()}
        for mode, button in self.mode_buttons.items():
            if mode in letters:
                button.setToolTip(f"{button.accessibleName()} ({letters[mode]})")
        self._tool_letters_done = True
