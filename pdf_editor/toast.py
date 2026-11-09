"""Non-modal banner over the central area: message, optional actions, collapsible details."""
from __future__ import annotations

import os
import subprocess
import sys

from PySide6.QtCore import QEvent, QTimer, QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QTextEdit, QToolButton, QVBoxLayout

from .lang import _
INFO_SECONDS = 8000
MARGIN = 8


def reveal_in_folder(path):
    """Select the file in Explorer; elsewhere, open its folder."""
    path = os.path.normpath(str(path))
    if sys.platform == "win32":
        subprocess.Popen(["explorer", f"/select,{path}"])
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))


def open_path(path):
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


class ToastBanner(QFrame):
    def __init__(self, host):
        super().__init__(host)
        self.setObjectName("ToastBanner")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "QFrame#ToastBanner { background: palette(window); border: 1px solid palette(mid);"
            " border-left: 4px solid #2b6cb0; border-radius: 6px; }"
            " QFrame#ToastBanner[kind=\"error\"] { border-left-color: #b3261e; }"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 8, 8, 8)
        outer.setSpacing(6)
        top = QHBoxLayout()
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        top.addWidget(self.label, 1)
        self.action_layout = QHBoxLayout()
        self.action_layout.setSpacing(6)
        top.addLayout(self.action_layout)
        self.details_button = QPushButton(_("Detalles"))
        self.details_button.setCheckable(True)
        self.details_button.setFlat(True)
        top.addWidget(self.details_button)
        self.close_button = QToolButton()
        self.close_button.setText("×")
        self.close_button.setToolTip(_("Cerrar"))
        self.close_button.setAutoRaise(True)
        top.addWidget(self.close_button)
        outer.addLayout(top)
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(140)
        self.details.hide()
        outer.addWidget(self.details)
        self.details_button.toggled.connect(self.toggle_details)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.dismiss)
        self.close_button.clicked.connect(self.dismiss)
        host.installEventFilter(self)
        self.hide()

    def show_message(self, text, *, kind="info", actions=(), details="", timeout=None):
        self.timer.stop()
        self.label.setText(text)
        self.setProperty("kind", kind)
        self.style().unpolish(self)
        self.style().polish(self)
        while self.action_layout.count():
            item = self.action_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for label, callback in actions:
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, call=callback: self._run_action(call))
            self.action_layout.addWidget(button)
        self.details.setPlainText(details)
        self.details.hide()
        self.details_button.setChecked(False)
        self.details_button.setVisible(bool(details))
        if timeout:
            self.timer.start(timeout)
        self.place()
        self.show()
        self.raise_()

    def dismiss(self):
        self.timer.stop()
        self.hide()

    def place(self):
        host = self.parentWidget()
        width = max(240, min(host.width() - 2 * MARGIN, 760))
        self.setFixedWidth(width)
        self.layout().activate()
        height = self.heightForWidth(width) if self.hasHeightForWidth() else self.sizeHint().height()
        self.setFixedHeight(height)
        self.move((host.width() - width) // 2, MARGIN)

    def toggle_details(self, checked):
        self.details.setVisible(checked)
        self.place()

    def eventFilter(self, watched, event):
        if watched is self.parentWidget() and event.type() == QEvent.Type.Resize and self.isVisible():
            self.place()
        return False

    def _run_action(self, callback):
        self.dismiss()
        callback()


def banner_for(window):
    """Banner floating over the document area. Its host is the page stack, not the splitter, so it takes no column."""
    banner = getattr(window, "toast_banner", None)
    if banner is None:
        host = getattr(window, "stack", None) or window.centralWidget() or window
        banner = ToastBanner(host)
        window.toast_banner = banner
    return banner


def notify(window, text, *, kind="info", actions=(), details="", timeout=None):
    """Show a banner. Info messages hide themselves; errors stay until closed."""
    if timeout is None and kind == "info":
        timeout = INFO_SECONDS
    banner = banner_for(window)
    banner.show_message(text, kind=kind, actions=actions, details=details, timeout=timeout)
    return banner


def notify_file(window, text, path, details=""):
    """Banner for a saved file with "Abrir carpeta" and "Abrir"."""
    return notify(window, text, actions=[(_("Abrir carpeta"), lambda: reveal_in_folder(path)), (_("Abrir"), lambda: open_path(path))], details=details)


def notify_folder(window, text, folder, details=""):
    """Banner for a folder with "Abrir carpeta"."""
    return notify(window, text, actions=[(_("Abrir carpeta"), lambda: open_path(folder))], details=details)
