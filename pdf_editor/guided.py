"""Acciones guiadas: asistente no modal que encadena herramientas existentes paso a paso."""
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QDockWidget, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget

from . import theme
from .lang import _, N_
from .toast import notify

PENDING, CURRENT, DONE, SKIPPED = "pending", "current", "done", "skipped"
MARKS = {PENDING: "○", CURRENT: "●", DONE: "✓", SKIPPED: "–"}
STATE_NAMES = {PENDING: N_("pendiente"), CURRENT: N_("en curso"), DONE: N_("hecho"), SKIPPED: N_("omitido")}
STATE_ROLE = Qt.ItemDataRole.UserRole + 1


def _token(w):
    engine = w.engine
    history = getattr(engine, "_undo", [])
    return engine, engine.doc, history[-1] if history else None, len(history)


def _changed(before, after):
    return before[0] is not after[0] or before[1] is not after[1] or before[2] is not after[2] or before[3] != after[3]


def _edits(method):
    """Runner for a tool that edits the document: done only if the document really changed."""
    def runner(w):
        before = _token(w)
        getattr(w, method)()
        return _changed(before, _token(w))
    return runner


def _saves(method):
    """Runner for a save tool: done only if it reports that the file was written."""
    def runner(w):
        return getattr(w, method)() is True
    return runner


def _mode(name):
    def runner(w):
        w.set_mode(name)
        return w.view.mode == name
    return runner


def _sign(w):
    """The signing tool returns nothing; done only if the signed copy was written."""
    from datetime import datetime
    from pathlib import Path

    from . import ui_security

    chosen = []
    original = ui_security.QFileDialog.getSaveFileName

    def recording(*args, **kwargs):
        result = original(*args, **kwargs)
        chosen.append(result[0])
        return result

    started = datetime.now().timestamp() - 1
    ui_security.QFileDialog.getSaveFileName = recording
    try:
        w.sign()
    finally:
        ui_security.QFileDialog.getSaveFileName = original
    path = next((item for item in chosen if item), "")
    return bool(path) and Path(path).is_file() and Path(path).stat().st_mtime >= started


_sanitize = _edits("sanitize")
_optimize = _edits("optimize")
_merge = _edits("merge")
_number = _edits("number_pages")
_redact_search = _edits("redact_search")
_redact_apply = _edits("apply_redactions")
_save_copy = _saves("save_copy")
_save = _saves("save")
_redact_review = _mode("redact")
_fill = _mode("fill")


# key, title, summary, [(step title, hint, runner)]
ACTIONS = [
    ("prepare", N_("Preparar para enviar"), N_("Reduce el tamaño y quita los datos ocultos antes de compartir."), [
        (N_("Quitar metadatos y datos ocultos"), N_("Elimina autor, adjuntos, enlaces y scripts."), _sanitize),
        (N_("Comprimir el documento"), N_("Elige la calidad y mira el tamaño resultante."), _optimize),
        (N_("Guardar una copia"), N_("Conserva el original y envía la copia."), _save_copy),
    ]),
    ("combine", N_("Combinar y numerar páginas"), N_("Une archivos en un documento y numera sus páginas."), [
        (N_("Combinar archivos"), N_("Añade otros PDF a este documento o crea uno nuevo."), _merge),
        (N_("Numerar páginas"), N_("Escribe el número en cada página."), _number),
        (N_("Guardar"), N_("Guarda el documento resultante."), _save),
    ]),
    ("redact", N_("Censurar información sensible"), N_("Busca patrones, revisa las marcas y aplícalas."), [
        (N_("Buscar y marcar patrones"), N_("Correos, teléfonos, números u otro texto."), _redact_search),
        (N_("Revisar las marcas"), N_("Activa la herramienta de censura para ajustar zonas."), _redact_review),
        (N_("Aplicar censuras"), N_("Elimina de forma definitiva el contenido marcado."), _redact_apply),
        (N_("Quitar datos ocultos"), N_("Borra metadatos que puedan citar el texto censurado."), _sanitize),
        (N_("Guardar una copia"), N_("Conserva el original intacto."), _save_copy),
    ]),
    ("sign", N_("Rellenar y firmar"), N_("Completa los campos, firma y guarda."), [
        (N_("Rellenar el documento"), N_("Escribe sobre la página o en los campos del formulario."), _fill),
        (N_("Firmar con certificado"), N_("Opcional: añade una firma digital."), _sign),
        (N_("Guardar"), N_("Guarda el documento firmado."), _save),
    ]),
]


class GuidedPanel(QDockWidget):
    """Panel acoplable (no modal): acciones, pasos con su estado, Siguiente y Omitir."""

    def __init__(self, window):
        super().__init__(_("Acciones guiadas"), window)
        self.window_ref = window
        self.setObjectName("GuidedPanel")
        self.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.LeftDockWidgetArea)
        self.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable | QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.action = None
        self.states = []
        self.index = 0
        body = QWidget()
        column = QVBoxLayout(body)
        column.setContentsMargins(12, 10, 12, 12)
        column.setSpacing(8)
        self.choices = QListWidget()
        self.choices.setAccessibleName(_("Acciones guiadas disponibles"))
        self.choices.setMaximumHeight(112)
        for key, title, summary, _steps in ACTIONS:
            item = QListWidgetItem(_(title))
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setToolTip(_(summary))
            self.choices.addItem(item)
        self.choices.itemClicked.connect(lambda item: self.start(item.data(Qt.ItemDataRole.UserRole)))
        self.choices.itemActivated.connect(lambda item: self.start(item.data(Qt.ItemDataRole.UserRole)))
        column.addWidget(self.choices)
        self.summary = QLabel(_("Elige una acción para empezar."))
        self.summary.setObjectName("caption")
        self.summary.setWordWrap(True)
        column.addWidget(self.summary)
        self.steps = QListWidget()
        self.steps.setAccessibleName(_("Pasos"))
        self.steps.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.steps.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        column.addWidget(self.steps, 1)
        self.hint = QLabel("")
        self.hint.setWordWrap(True)
        column.addWidget(self.hint)
        self.message = QLabel("")
        self.message.setObjectName("caption")
        self.message.setWordWrap(True)
        column.addWidget(self.message)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.skip_button = QPushButton(_("Omitir"))
        self.skip_button.setProperty("secondary", True)
        self.skip_button.clicked.connect(self.skip)
        self.next_button = QPushButton(_("Siguiente"))
        self.next_button.setProperty("primary", True)
        self.next_button.clicked.connect(self.advance)
        buttons.addWidget(self.skip_button)
        buttons.addStretch(1)
        buttons.addWidget(self.next_button)
        column.addLayout(buttons)
        self.setWidget(body)
        self.setMinimumWidth(250)
        self.refresh()

    def steps_of(self):
        return self.action[3] if self.action else []

    def finished(self):
        return bool(self.action) and self.index >= len(self.states)

    def start(self, key):
        self.action = next((entry for entry in ACTIONS if entry[0] == key), None)
        self.states = [PENDING] * len(self.steps_of())
        self.index = 0
        self.message.setText("")
        if self.states:
            self.states[0] = CURRENT
            if not self.window_ref.has_doc():
                self.message.setText(_("Abre un PDF para usar esta acción."))
        self.refresh()

    def mark(self, state):
        self.states[self.index] = state
        self.index += 1
        if self.index < len(self.states):
            self.states[self.index] = CURRENT
        self.refresh()

    def advance(self):
        if not self.action or self.finished():
            return
        if not self.window_ref.has_doc():
            self.message.setText(_("Abre un PDF para usar esta acción."))
            return
        runner = self.steps_of()[self.index][2]
        outcome = {}

        def attempt():
            outcome["done"] = bool(runner(self.window_ref))
            outcome["ran"] = True

        self.window_ref.run(attempt)
        if outcome.get("done"):
            self.message.setText("")
            self.mark(DONE)
        elif outcome.get("ran"):
            self.message.setText(_("Paso cancelado"))
            notify(self.window_ref, _("Paso cancelado"))
        else:
            self.message.setText(_("El paso no se pudo completar. Puedes reintentarlo u omitirlo."))

    def skip(self):
        if self.action and not self.finished():
            self.message.setText("")
            self.mark(SKIPPED)

    def refresh(self):
        tokens = theme.current_tokens()
        self.steps.clear()
        for number, (step, state) in enumerate(zip(self.steps_of(), self.states), 1):
            item = QListWidgetItem(f"{MARKS[state]}  {number}. {_(step[0])}  ({_(STATE_NAMES[state])})")
            item.setData(STATE_ROLE, state)
            item.setToolTip(_(step[1]))
            item.setForeground(QColor({DONE: tokens["accent"], CURRENT: tokens["ink"]}.get(state, tokens["inkmuted"])))
            if state == CURRENT:
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            self.steps.addItem(item)
        running = bool(self.action) and not self.finished()
        self.next_button.setEnabled(running)
        self.skip_button.setEnabled(running)
        if self.action:
            self.summary.setText(_(self.action[2]))
        if running:
            self.hint.setText(_(self.steps_of()[self.index][1]))
        elif self.finished():
            self.hint.setText(_("Terminado: {done} de {total} paso(s) hechos.", done=self.states.count(DONE), total=len(self.states)))
        else:
            self.hint.setText("")

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.StyleChange) and self.action:
            self.refresh()


def open_guided(window, key=None):
    """Muestra el panel (se crea la primera vez) y, si se indica una acción, la arranca."""
    panel = getattr(window, "guided_panel", None)
    if panel is None:
        panel = window.guided_panel = GuidedPanel(window)
        window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, panel)
    panel.show()
    panel.raise_()
    if key:
        panel.start(key)
    return panel
