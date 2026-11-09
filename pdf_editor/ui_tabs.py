from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import QMenu, QTabBar, QToolButton

from . import icons
from .engine import PDFEngine
from .lang import _

TAB_MAX_WIDTH = 220


class DocumentTab:
    """Everything that belongs to one open document: its engine, view position and recovery state."""

    def __init__(self, engine):
        self.engine = engine
        self.page = 0
        self.zoom = 100
        self.zoom_mode = "width"
        self.scroll = (0, 0)
        self.search_text = ""
        self.side_tab = None
        self.thumb_selection = []
        self.recovery_id = None
        self.autosave_at = None
        self.autosave_warned = False

    def title(self):
        return Path(self.engine.path).name if self.engine.path else _("Sin título")

    def key(self):
        return same_file_key(self.engine.path)


def same_file_key(path):
    return os.path.normcase(str(Path(path).resolve())) if path else None


class UiTabsMixin:
    """Several documents open at once: the tab bar above the canvas and the state that follows each tab."""

    def init_tab_state(self):
        self.documents = []
        self.active_tab = None
        self.idle_engine = PDFEngine()
        self.idle_engine.close()

    # The document-level state of the active tab is exposed under its old names.

    @property
    def engine(self):
        return self.active_tab.engine if self.active_tab is not None else self.idle_engine

    @engine.setter
    def engine(self, value):
        if self.active_tab is not None:
            self.active_tab.engine = value
        else:
            self.idle_engine = value

    def _tab_field(name, default):
        def getter(self):
            return getattr(self.active_tab, name) if self.active_tab is not None else default

        def setter(self, value):
            if self.active_tab is not None:
                setattr(self.active_tab, name, value)

        return property(getter, setter)

    recovery_id = _tab_field("recovery_id", None)
    autosave_at = _tab_field("autosave_at", None)
    autosave_warned = _tab_field("autosave_warned", False)
    del _tab_field

    # Tab bar ---------------------------------------------------------------------

    def build_tab_bar(self):
        bar = QTabBar()
        bar.setObjectName("DocumentTabs")
        bar.setDocumentMode(True)
        bar.setMovable(True)
        bar.setExpanding(False)
        bar.setDrawBase(False)
        bar.setUsesScrollButtons(True)
        bar.setElideMode(Qt.TextElideMode.ElideRight)
        bar.setAccessibleName(_("Documentos abiertos"))
        bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        bar.customContextMenuRequested.connect(self.tab_menu)
        bar.currentChanged.connect(self.tab_bar_changed)
        bar.tabMoved.connect(self.tab_bar_moved)
        bar.setVisible(False)
        self.doc_tabs = bar
        self.build_tab_shortcuts()
        return bar

    def build_tab_shortcuts(self):
        def bind(keys, handler):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(handler)

        bind("Ctrl+Tab", lambda: self.step_tab(1))
        bind("Ctrl+Shift+Tab", lambda: self.step_tab(-1))
        # Ctrl+1 and Ctrl+9 already mean "Tamaño real" and "Ajustar página", so the jump to a tab uses Alt.
        for number in range(1, 10):
            bind(f"Alt+{number}", lambda n=number: self.jump_to_tab(n))

    def step_tab(self, delta):
        if len(self.documents) > 1:
            index = self.documents.index(self.active_tab)
            self.activate_tab((index + delta) % len(self.documents))

    def jump_to_tab(self, number):
        """Alt+1 to Alt+8 pick that tab; Alt+9 always picks the last one."""
        if self.documents:
            self.activate_tab(len(self.documents) - 1 if number == 9 else min(number, len(self.documents)) - 1)

    def tab_index(self, tab):
        return self.documents.index(tab)

    def tab_for_path(self, path):
        key = same_file_key(path)
        return next((tab for tab in self.documents if key and tab.key() == key), None)

    def refresh_tab_bar(self):
        """Labels, tooltips and visibility. Cheap enough to run on every refresh and on the state timer."""
        bar = self.doc_tabs
        bar.setVisible(bool(self.documents))
        for index, tab in enumerate(self.documents):
            if index >= bar.count():
                break
            text = ("● " if tab.engine.dirty else "") + tab.title()
            if bar.tabText(index) != text:
                bar.setTabText(index, text)
            tip = tab.engine.path or _("Documento sin guardar")
            if bar.tabToolTip(index) != tip:
                bar.setTabToolTip(index, tip)

    def refresh_tab_icons(self):
        if not hasattr(self, "doc_tabs"):
            return
        for index in range(self.doc_tabs.count()):
            button = self.doc_tabs.tabButton(index, QTabBar.ButtonPosition.RightSide)
            if button is not None:
                button.setIcon(icons.themed_icon("close", "muted"))

    def make_close_button(self, tab):
        button = QToolButton()
        button.setObjectName("TabClose")
        button.setAutoRaise(True)
        button.setToolTip(_("Cerrar documento"))
        button.setAccessibleName(_("Cerrar documento"))
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setIcon(icons.themed_icon("close", "muted"))
        button.setFixedSize(18, 18)
        button.clicked.connect(lambda _=False: self.close_tab(tab))
        return button

    # Adding, switching, closing --------------------------------------------------

    def capture_tab_state(self):
        """Stores where the active document is: page, zoom, scroll and the search text."""
        tab = self.active_tab
        if tab is None or not self.has_doc():
            return
        if self.is_continuous():
            self.continuous_view_moved()
        tab.page = self.page
        tab.zoom = self.zoom.value()
        tab.zoom_mode = self.zoom_mode
        tab.scroll = (self.view.horizontalScrollBar().value(), self.view.verticalScrollBar().value())
        tab.search_text = self.search.text()
        tab.side_tab = self.side_tab_keys[self.left_tabs.currentIndex()]
        tab.thumb_selection = sorted(self.thumbnails.row(item) for item in self.thumbnails.selectedItems())

    def adopt_idle_engine(self):
        """A document built straight on the idle engine (no tab yet) gets its tab here."""
        idle = self.idle_engine
        if self.active_tab is None and idle.doc is not None and not idle.doc.is_closed:
            page = self.page
            self.idle_engine = PDFEngine()
            self.idle_engine.close()
            self.add_tab(idle)
            self.page = page

    @contextmanager
    def new_tab(self):
        """A tab for a document that is about to be built on self.engine. It goes away again if nothing was built."""
        engine = PDFEngine()
        engine.close()
        previous = self.active_tab
        tab = self.add_tab(engine)
        try:
            yield tab
        except BaseException:
            self.remove_tab(tab, prefer=previous)
            raise
        if tab.engine.doc is None:
            self.remove_tab(tab, prefer=previous)

    def add_tab(self, engine):
        """Makes engine a new tab and the active one. The caller refreshes the window afterwards."""
        self.capture_tab_state()
        tab = DocumentTab(engine)
        tab.zoom_mode = self.zoom_mode
        self.documents.append(tab)
        self.active_tab = tab
        bar = self.doc_tabs
        bar.blockSignals(True)
        index = bar.addTab(tab.title())
        bar.setTabButton(index, QTabBar.ButtonPosition.RightSide, self.make_close_button(tab))
        bar.setCurrentIndex(index)
        bar.blockSignals(False)
        self.page = 0
        self.search_results = []
        self.refresh_tab_bar()
        return tab

    def tab_bar_changed(self, index):
        if 0 <= index < len(self.documents) and self.documents[index] is not self.active_tab:
            self.activate_tab(index)

    def tab_bar_moved(self, source, target):
        self.documents.insert(target, self.documents.pop(source))

    def activate_tab(self, index):
        """Shows the document of tab index, keeping the state of the one being left."""
        if not 0 <= index < len(self.documents):
            return False
        tab = self.documents[index]
        if tab is self.active_tab:
            self.sync_bar_to_active()
            return True
        if not self.view.commit_editor():
            self.sync_bar_to_active()
            return False
        self.remember_view()
        self.capture_tab_state()
        self.active_tab = tab
        self.sync_bar_to_active()
        self.show_tab_state(tab)
        return True

    def sync_bar_to_active(self):
        if self.active_tab is None:
            return
        bar = self.doc_tabs
        index = self.documents.index(self.active_tab)
        if bar.currentIndex() != index:
            bar.blockSignals(True)
            bar.setCurrentIndex(index)
            bar.blockSignals(False)

    def show_tab_state(self, tab):
        """Displays the active tab with the page, zoom, scroll and search it had when it was left."""
        self.page = tab.page
        self.search_results = []
        self.search_index = -1
        self.zoom_mode = tab.zoom_mode
        self.set_zoom_value(tab.zoom)
        self.search.blockSignals(True)
        self.search.setText(tab.search_text)
        self.search.blockSignals(False)
        # The remembered per-file position must not override what this tab had.
        self.view_doc = tab.engine.doc
        self.pending_page_scroll = False
        self.fit_locked_until = time.monotonic() + 0.5
        self.restore_side_tab(tab)
        self.refresh()
        self.restore_thumb_selection(tab)
        self.sync_view_actions()
        self.restore_scroll(tab.scroll)
        QTimer.singleShot(0, lambda t=tab: self.active_tab is t and self.restore_scroll(t.scroll))

    def restore_side_tab(self, tab):
        if tab.side_tab in self.side_tab_keys:
            index = self.side_tab_keys.index(tab.side_tab)
            if index != self.left_tabs.currentIndex():
                self.left_tabs.blockSignals(True)
                self.left_tabs.setCurrentIndex(index)
                self.left_tabs.blockSignals(False)

    def restore_thumb_selection(self, tab):
        thumbnails = self.thumbnails
        wanted = {row for row in tab.thumb_selection if row < thumbnails.count()}
        if not wanted:
            return
        thumbnails.blockSignals(True)
        for row in range(thumbnails.count()):
            item = thumbnails.item(row)
            if item.isSelected() != (row in wanted):
                item.setSelected(row in wanted)
        thumbnails.blockSignals(False)

    def close_tab(self, tab):
        """Closes one document, asking about its unsaved changes only. False when the user cancels."""
        if tab not in self.documents:
            return False
        if tab is not self.active_tab and not self.activate_tab(self.documents.index(tab)):
            return False
        if not self.confirm_discard():
            return False
        self.remember_view()
        self.remove_tab(tab)
        return True

    def remove_tab(self, tab, prefer=None):
        index = self.documents.index(tab)
        was_active = tab is self.active_tab
        self.documents.pop(index)
        self.doc_tabs.blockSignals(True)
        self.doc_tabs.removeTab(index)
        self.doc_tabs.blockSignals(False)
        try:
            tab.engine.close()
        except Exception:
            pass
        if not was_active:
            self.sync_bar_to_active()
            return
        if self.documents:
            self.active_tab = prefer if prefer in self.documents else self.documents[min(index, len(self.documents) - 1)]
            self.sync_bar_to_active()
            self.show_tab_state(self.active_tab)
        else:
            self.active_tab = None
            self.view_doc = None
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
            self.page = 0
            self.refresh()

    def close_other_tabs(self, keep):
        for tab in [t for t in self.documents if t is not keep]:
            if not self.close_tab(tab):
                return False
        return True

    def reveal_tab_file(self, tab):
        if tab.engine.path and Path(tab.engine.path).exists():
            if os.name == "nt":
                import subprocess
                subprocess.Popen(["explorer", "/select,", str(Path(tab.engine.path))])
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(tab.engine.path).parent)))

    def tab_menu(self, point):
        index = self.doc_tabs.tabAt(point)
        if index < 0:
            return
        tab = self.documents[index]
        menu = QMenu(self)
        menu.addAction(_("Cerrar")).triggered.connect(lambda: self.run(lambda: self.close_tab(tab)))
        others = menu.addAction(_("Cerrar otras"))
        others.setEnabled(len(self.documents) > 1)
        others.triggered.connect(lambda: self.run(lambda: self.close_other_tabs(tab)))
        menu.addSeparator()
        reveal = menu.addAction(_("Mostrar en carpeta"))
        reveal.setEnabled(bool(tab.engine.path and Path(tab.engine.path).exists()))
        reveal.triggered.connect(lambda: self.reveal_tab_file(tab))
        self.tab_context_menu = menu
        menu.popup(self.doc_tabs.mapToGlobal(point))
