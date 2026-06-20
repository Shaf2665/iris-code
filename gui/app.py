"""Iris Code desktop application (PySide6).

A VS Code-style IDE shell over the forge Agent: an activity bar, a left file
Explorer, a center editor with editable tabs, a chat panel docked right, and a
toggleable bottom terminal. All network/CPU work runs in worker threads so the UI
stays responsive; the panel layout is remembered between launches.
"""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt, QTimer, QSettings
from PySide6.QtGui import QIcon, QTextOption, QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFrame,
    QLabel, QPushButton, QPlainTextEdit, QComboBox, QFileDialog, QInputDialog,
    QDockWidget, QToolBar, QSizePolicy,
)

from forge.config import Config
from forge.agent import Agent, detect_stack
from forge.memory.conversations import ConversationStore

from .style import STYLESHEET, OK, ERR, TEXT_DIM, ACCENT, BORDER


def _vsep() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.VLine)
    f.setStyleSheet(f"color:{BORDER}; max-width:1px;")
    return f


from .chat_view import ChatView
from .file_tree import FileTree
from .editor import EditorArea
from .terminal import TerminalPanel
from .worker import ChatWorker, IndexWorker, HealthWorker
from .settings import SettingsDialog

_DEFAULT_SESSION = "gui_dev"


def resource_path(rel: str) -> str:
    """Resolve a bundled data file both when frozen (PyInstaller _MEIPASS) and
    when running from source (repo root)."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, rel)
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), rel)


def _app_icon() -> QIcon:
    path = resource_path(os.path.join("packaging", "icon.png"))
    return QIcon(path) if os.path.exists(path) else QIcon()


def _conv_id(name: str | None) -> str:
    return f"session:{name}" if name else _DEFAULT_SESSION


def _label_of(conv_id: str) -> str:
    if conv_id == _DEFAULT_SESSION:
        return "default"
    return conv_id[8:] if conv_id.startswith("session:") else conv_id


class MainWindow(QMainWindow):
    def __init__(self, config: Config):
        super().__init__()
        self._config = config
        self._agent = Agent(config)
        self._store = ConversationStore(config.db_path)
        self._conv_id = _DEFAULT_SESSION
        # Start each launch with a clean, empty conversation. Prior named sessions
        # stay in the store (and the dropdown) so they can be resumed on demand;
        # the default view is fresh and only persisted once the user sends.
        self._history: list[dict] = []
        self._chat_worker: ChatWorker | None = None
        self._index_worker: IndexWorker | None = None
        self._health_worker: HealthWorker | None = None
        self._router_ok = False          # last health result; gates auto-indexing
        self._auto_indexed = False       # auto-index runs at most once per project open

        self.setWindowTitle("Iris Code — Forge")
        self.setWindowIcon(_app_icon())
        self.resize(1180, 760)
        self.setMinimumSize(820, 560)
        self.setDockOptions(QMainWindow.AnimatedDocks | QMainWindow.AllowNestedDocks)
        self._build_ui()
        self._restore_layout()

        self._refresh_sessions()
        self._chat.reset(self._history)
        self._update_project_label()
        self._check_health()

        # Periodic, lightweight health poll.
        self._health_timer = QTimer(self)
        self._health_timer.timeout.connect(self._check_health)
        self._health_timer.start(20000)

        # First-run: offer to set up hermes-router if it isn't set up yet.
        QTimer.singleShot(600, self._maybe_first_run)

    # ── UI construction ────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self.setMenuWidget(self._build_topbar())

        # Center: the editor area (tabbed, editable).
        self._editor = EditorArea()
        self.setCentralWidget(self._editor)

        # Explorer (left dock).
        self._file_tree = FileTree()
        self._file_tree.file_activated.connect(self._editor.open_file)
        self._file_tree.send_to_forge.connect(self._on_send_file_to_forge)
        self._file_tree.index_folder.connect(lambda _p: self._start_index(force=True))
        self._explorer_dock = self._make_dock("Explorer", self._file_tree,
                                               Qt.LeftDockWidgetArea, "ExplorerDock")

        # Chat (right dock).
        self._chat = ChatView()
        self._chat_dock = self._make_dock("Chat", self._build_chat_panel(),
                                          Qt.RightDockWidgetArea, "ChatDock")
        self.resizeDocks([self._chat_dock], [380], Qt.Horizontal)

        # Terminal (bottom dock, hidden until toggled).
        self._terminal = TerminalPanel(self._config.project_dir)
        self._terminal_dock = self._make_dock("Terminal", self._terminal,
                                              Qt.BottomDockWidgetArea, "TerminalDock",
                                              visible=False)

        self._build_activity_bar()
        self._wire_shortcuts()

    def _make_dock(self, title, widget, area, object_name, visible=True) -> QDockWidget:
        d = QDockWidget(title, self)
        d.setObjectName(object_name)
        d.setWidget(widget)
        d.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetClosable
                      | QDockWidget.DockWidgetFloatable)
        self.addDockWidget(area, d)
        d.setVisible(visible)
        return d

    def _build_activity_bar(self) -> None:
        bar = QToolBar("Activity")
        bar.setObjectName("ActivityBar")
        bar.setMovable(False)
        bar.setFloatable(False)
        bar.setToolButtonStyle(Qt.ToolButtonTextOnly)
        bar.setOrientation(Qt.Vertical)

        for dock, text, tip in (
            (self._explorer_dock, "Files", "Toggle the file Explorer (Ctrl+B)"),
            (self._chat_dock, "Chat", "Toggle the chat panel"),
            (self._terminal_dock, "Term", "Toggle the terminal (Ctrl+`)"),
        ):
            act = dock.toggleViewAction()
            act.setText(text)
            act.setToolTip(tip)
            bar.addAction(act)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        bar.addWidget(spacer)

        router_act = QAction("Router", self)
        router_act.triggered.connect(self._on_router_panel)
        bar.addAction(router_act)
        settings_act = QAction("⚙", self)
        settings_act.setToolTip("Settings")
        settings_act.triggered.connect(self._on_settings)
        bar.addAction(settings_act)

        self.addToolBar(Qt.LeftToolBarArea, bar)
        self._activity_bar = bar

    def _wire_shortcuts(self) -> None:
        def toggle(dock):
            dock.setVisible(not dock.isVisible())
        QShortcut(QKeySequence("Ctrl+B"), self, activated=lambda: toggle(self._explorer_dock))
        QShortcut(QKeySequence("Ctrl+J"), self, activated=lambda: toggle(self._terminal_dock))
        QShortcut(QKeySequence("Ctrl+`"), self, activated=lambda: toggle(self._terminal_dock))
        QShortcut(QKeySequence("Ctrl+\\"), self, activated=lambda: toggle(self._chat_dock))
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self._editor.save_current)

    def _build_topbar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("TopBar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(8)

        # ── Left group: brand · project · project actions ──
        title = QLabel(f'<span style="color:{ACCENT};font-weight:800">✦ Iris&nbsp;Code</span>')
        lay.addWidget(title)
        lay.addSpacing(4)
        lay.addWidget(_vsep())
        lay.addSpacing(4)

        lay.addWidget(QLabel("Project:", objectName="ProjectLabel"))
        self._project_value = QLabel("none", objectName="ProjectValue")
        self._project_value.setMaximumWidth(280)
        lay.addWidget(self._project_value)
        lay.addSpacing(6)

        open_btn = QPushButton("Open…")
        open_btn.setToolTip("Choose the active project directory")
        open_btn.clicked.connect(self._on_open_project)
        lay.addWidget(open_btn)

        self._index_btn = QPushButton("Index")
        self._index_btn.setToolTip("Index the project for semantic code search")
        self._index_btn.clicked.connect(self._on_index)
        lay.addWidget(self._index_btn)

        lay.addStretch(1)

        # ── Right group: session · router status ──
        lay.addWidget(QLabel("Session:", objectName="ProjectLabel"))
        self._session_combo = QComboBox()
        self._session_combo.setMinimumWidth(140)
        self._session_combo.activated.connect(self._on_session_selected)
        lay.addWidget(self._session_combo)

        new_btn = QPushButton("＋")
        new_btn.setToolTip("New session")
        new_btn.setFixedWidth(34)
        new_btn.clicked.connect(self._on_new_session)
        lay.addWidget(new_btn)

        lay.addSpacing(4)
        lay.addWidget(_vsep())
        lay.addSpacing(4)

        self._status_dot = QLabel("●", objectName="StatusDot")
        self._status_dot.setStyleSheet(f"color:{TEXT_DIM}")
        self._status_dot.setToolTip("Router status")
        lay.addWidget(self._status_dot)
        self._status_text = QLabel("checking…")
        self._status_text.setStyleSheet(f"color:{TEXT_DIM}; font-size:12px;")
        self._status_text.setToolTip("hermes-router connection")
        lay.addWidget(self._status_text)

        return bar

    def _build_chat_panel(self) -> QWidget:
        wrap = QWidget()
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._chat, 1)

        composer_row = QWidget()
        crl = QHBoxLayout(composer_row)
        crl.setContentsMargins(8, 6, 8, 8)
        crl.setSpacing(8)
        self._composer = QPlainTextEdit()
        self._composer.setObjectName("Composer")
        self._composer.setPlaceholderText("Ask Forge to write, debug, run, or find code…  (Enter to send)")
        self._composer.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self._composer.setFixedHeight(70)
        crl.addWidget(self._composer, 1)
        self._send_btn = QPushButton("Send")
        self._send_btn.setObjectName("Send")
        self._send_btn.setFixedHeight(70)
        self._send_btn.clicked.connect(self._on_send)
        crl.addWidget(self._send_btn)
        lay.addWidget(composer_row)

        self._composer.installEventFilter(self)
        return wrap

    # ── input handling ─────────────────────────────────────────────────

    def eventFilter(self, obj, event):  # noqa: N802 (Qt naming)
        from PySide6.QtCore import QEvent
        if obj is self._composer and event.type() == QEvent.KeyPress:
            key = event.key()
            if key in (Qt.Key_Return, Qt.Key_Enter) and not (event.modifiers() & Qt.ShiftModifier):
                self._on_send()
                return True
        return super().eventFilter(obj, event)

    # ── chat flow ──────────────────────────────────────────────────────

    def _busy(self, busy: bool) -> None:
        self._send_btn.setEnabled(not busy)
        self._composer.setReadOnly(busy)
        self._send_btn.setText("…" if busy else "Send")

    def _on_send(self) -> None:
        if self._chat_worker is not None:
            return
        text = self._composer.toPlainText().strip()
        if not text:
            return
        self._composer.clear()
        self._chat.add_user(text)
        self._chat.begin_assistant()
        self._busy(True)

        self._chat_worker = ChatWorker(self._agent, text, self._history)
        self._chat_worker.token.connect(self._chat.append_token)
        self._chat_worker.tool_status.connect(self._chat.add_tool_status)
        self._chat_worker.finished_ok.connect(self._on_chat_done)
        self._chat_worker.failed.connect(self._on_chat_failed)
        self._chat_worker.start()

    def _on_chat_done(self) -> None:
        self._chat.end_assistant()
        self._store.save(self._conv_id, self._history)
        self._chat_worker = None
        self._busy(False)
        self._refresh_sessions()

    def _on_chat_failed(self, msg: str) -> None:
        self._chat.end_assistant()
        self._chat.add_system_note(f"⚠ Error: {msg}")
        self._chat_worker = None
        self._busy(False)
        self._check_health()

    # ── project / index ────────────────────────────────────────────────

    def _on_open_project(self) -> None:
        start = self._config.project_dir or os.path.expanduser("~")
        path = QFileDialog.getExistingDirectory(self, "Select project directory", start)
        if not path:
            return
        resolved = self._agent.set_project(path)
        self._config.save_overrides()
        self._auto_indexed = False  # new project — allow one auto-index pass
        self._update_project_label()
        self._chat.add_system_note(f"Active project set to {resolved}")
        self._maybe_auto_index()

    def _maybe_auto_index(self) -> None:
        """Index the active project in the background when it isn't indexed yet.
        Gated on router connectivity (embeddings go through the router) and runs at
        most once per project open, so the user never has to click Index manually."""
        pd = self._config.project_dir
        if not pd or self._auto_indexed or self._index_worker is not None:
            return
        if self._agent.index.stats(pd)["chunk_count"]:
            self._auto_indexed = True
            return
        if not self._router_ok:
            self._chat.add_system_note("Connect the router to enable semantic code search.")
            return
        self._auto_indexed = True
        self._chat.add_system_note(f"Indexing {pd} for semantic search…")
        self._start_index(force=False)

    def _on_send_file_to_forge(self, path: str) -> None:
        rel = os.path.relpath(path, self._config.project_dir) if self._config.project_dir else path
        self._composer.setPlainText(f"Take a look at `{rel}` and explain what it does.")
        self._chat_dock.setVisible(True)
        self._composer.setFocus()

    def _update_project_label(self) -> None:
        pd = self._config.project_dir
        if not pd:
            self._project_value.setText("none")
            self._index_btn.setEnabled(False)
            return
        stack = detect_stack(pd)
        short = pd if len(pd) < 48 else "…" + pd[-46:]
        self._project_value.setText(short + (f"  ({stack})" if stack else ""))
        self._index_btn.setEnabled(True)
        stats = self._agent.index.stats(pd)
        if stats["chunk_count"]:
            self._index_btn.setText(f"Index ✓ {stats['chunk_count']}")
        else:
            self._index_btn.setText("Index")
        # Root the explorer + terminal at the project.
        self._file_tree.set_root(pd)
        self._explorer_dock.setVisible(True)
        self._terminal.set_cwd(pd)

    def _on_index(self) -> None:
        pd = self._config.project_dir
        if not pd or self._index_worker is not None:
            return
        self._chat.add_system_note(f"Indexing {pd} …")
        self._start_index(force=False)

    def _start_index(self, force: bool) -> None:
        """Kick off a background index pass (shared by the Index button and the
        auto-index-on-open path)."""
        pd = self._config.project_dir
        if not pd or self._index_worker is not None:
            return
        self._index_btn.setEnabled(False)
        self._index_btn.setText("Indexing…")
        self._index_worker = IndexWorker(self._agent, pd, force=force)
        self._index_worker.progress.connect(lambda m: self._chat.add_system_note(m))
        self._index_worker.done.connect(self._on_index_done)
        self._index_worker.failed.connect(self._on_index_failed)
        self._index_worker.start()

    def _on_index_done(self, n: int) -> None:
        self._chat.add_system_note(f"Index complete — {n} chunks embedded this run.")
        self._index_worker = None
        self._update_project_label()

    def _on_index_failed(self, msg: str) -> None:
        self._chat.add_system_note(f"⚠ Index failed: {msg}")
        self._index_worker = None
        self._update_project_label()

    # ── sessions ───────────────────────────────────────────────────────

    def _refresh_sessions(self) -> None:
        self._session_combo.blockSignals(True)
        self._session_combo.clear()
        ids = [s[0] for s in self._store.list_sessions()]
        if self._conv_id not in ids:
            ids.insert(0, self._conv_id)
        for cid in ids:
            self._session_combo.addItem(_label_of(cid), cid)
        idx = self._session_combo.findData(self._conv_id)
        if idx >= 0:
            self._session_combo.setCurrentIndex(idx)
        self._session_combo.blockSignals(False)

    def _on_session_selected(self, _i: int) -> None:
        cid = self._session_combo.currentData()
        if cid and cid != self._conv_id:
            self._switch_to(cid)

    def _on_new_session(self) -> None:
        name, ok = QInputDialog.getText(self, "New session", "Session name:")
        if ok and name.strip():
            self._switch_to(_conv_id(name.strip()))

    def _switch_to(self, cid: str) -> None:
        self._store.save(self._conv_id, self._history)
        self._conv_id = cid
        self._history = self._store.load(cid)
        self._store.save(cid, self._history)
        self._chat.reset(self._history)
        self._refresh_sessions()

    # ── settings / health ──────────────────────────────────────────────

    def _maybe_first_run(self) -> None:
        """If the router isn't set up (and the user hasn't dismissed it or picked a
        custom provider), offer the one-click setup wizard."""
        if self._config.is_custom_provider or self._config.setup_dismissed:
            return
        from forge.router import RouterAdmin
        admin = RouterAdmin(self._config.router_url, self._config.api_key,
                            router_dir=self._config.router_dir)
        if admin.is_set_up():
            return
        from .setup_wizard import SetupDialog
        dlg = SetupDialog(self._config, self)
        dlg.setup_done.connect(self._on_setup_complete)
        dlg.exec()
        self._check_health()

    def _on_setup_complete(self, folder: str) -> None:
        self._chat.add_system_note(f"hermes-router set up in {folder}.")
        self._check_health()

    def _on_router_panel(self) -> None:
        from .router_panel import RouterDialog
        dlg = RouterDialog(self._config, self)
        dlg.router_changed.connect(self._check_health)
        dlg.exec()
        self._check_health()

    def _on_settings(self) -> None:
        dlg = SettingsDialog(self._config, self)
        dlg.clear_history.connect(self._on_clear_history)
        dlg.clear_everything.connect(self._on_clear_everything)
        if dlg.exec():
            changed = dlg.apply_to(self._config)
            if changed:
                self._rebuild_agent()
            self._check_health()

    def _reset_view(self) -> None:
        """Drop back to a fresh, empty conversation and refresh the UI."""
        self._conv_id = _DEFAULT_SESSION
        self._history = []
        self._chat.reset(self._history)
        self._refresh_sessions()
        self._update_project_label()

    def _on_clear_history(self) -> None:
        self._store.clear_all()
        self._reset_view()
        self._chat.add_system_note("Chat history cleared.")

    def _on_clear_everything(self) -> None:
        self._store.clear_all()
        self._agent.forget_all()
        self._agent.index.clear_all()
        self._auto_indexed = False
        self._reset_view()
        self._chat.add_system_note("Cleared all conversations, remembered facts, and the code index.")

    def _rebuild_agent(self) -> None:
        try:
            self._agent.close()
        except Exception:
            pass
        self._agent = Agent(self._config)
        self._update_project_label()
        self._chat.add_system_note("Reconnected to router with new settings.")

    def _check_health(self) -> None:
        if self._health_worker is not None:
            return
        self._health_worker = HealthWorker(
            self._config.router_url, self._config.base_url,
            self._config.api_key, self._config.is_custom_provider,
        )
        self._health_worker.result.connect(self._on_health)
        self._health_worker.start()

    def _on_health(self, ok: bool, detail: str) -> None:
        became_online = ok and not self._router_ok
        self._router_ok = ok
        color = OK if ok else ERR
        self._status_dot.setStyleSheet(f"color:{color}")
        self._status_dot.setToolTip(f"Router: {detail}")
        self._status_text.setText("Connected" if ok else "Offline")
        self._status_text.setStyleSheet(f"color:{color if not ok else TEXT_DIM}; font-size:12px;")
        endpoint = self._config.base_url if self._config.is_custom_provider else self._config.router_url
        self._status_text.setToolTip(
            f"{'Custom provider' if self._config.is_custom_provider else 'hermes-router'} "
            f"at {endpoint} — {detail}"
            + ("" if ok else "\nStart your router, or change the provider in Settings (⚙).")
        )
        self._health_worker = None
        # First time we see the router online, index the active project if needed.
        if became_online:
            self._maybe_auto_index()

    # ── layout persistence ─────────────────────────────────────────────

    def _restore_layout(self) -> None:
        try:
            s = QSettings("IrisCode", "IrisCode")
            geo = s.value("geometry")
            state = s.value("windowState")
            if geo is not None:
                self.restoreGeometry(geo)
            if state is not None:
                self.restoreState(state)
        except Exception:
            pass  # a stale/old layout blob must never block startup

    def _save_layout(self) -> None:
        try:
            s = QSettings("IrisCode", "IrisCode")
            s.setValue("geometry", self.saveGeometry())
            s.setValue("windowState", self.saveState())
        except Exception:
            pass

    # ── lifecycle ──────────────────────────────────────────────────────

    def closeEvent(self, event):  # noqa: N802
        try:
            if self._editor.has_unsaved():
                from PySide6.QtWidgets import QMessageBox
                box = QMessageBox(self)
                box.setWindowTitle("Unsaved changes")
                box.setIcon(QMessageBox.Warning)
                box.setText("You have unsaved files. Quit anyway?")
                box.setStandardButtons(QMessageBox.Discard | QMessageBox.Cancel)
                box.setDefaultButton(QMessageBox.Cancel)
                if box.exec() == QMessageBox.Cancel:
                    event.ignore()
                    return
            self._save_layout()
            if self._chat_worker is not None:
                self._chat_worker.wait(2000)
            self._terminal.shutdown()
            self._store.save(self._conv_id, self._history)
            self._agent.close()
            self._store.close()
        except Exception:
            pass
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Iris Code")
    app.setOrganizationName("IrisCode")
    # Note: deliberately NOT calling setApplicationDisplayName — on Windows Qt
    # appends it to every window title, producing "Iris Code — Forge - Iris Code".
    app.setWindowIcon(_app_icon())
    app.setStyleSheet(STYLESHEET)
    try:
        config = Config.load()
        win = MainWindow(config)
    except Exception as e:  # noqa: BLE001 — show a friendly dialog, not a crash box
        import traceback
        from PySide6.QtWidgets import QMessageBox
        box = QMessageBox()
        box.setWindowTitle("Iris Code — startup error")
        box.setIcon(QMessageBox.Critical)
        box.setText("Iris Code couldn't start.")
        box.setInformativeText(str(e))
        box.setDetailedText(traceback.format_exc())
        box.exec()
        return 1
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
