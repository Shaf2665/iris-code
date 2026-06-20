"""Iris Code desktop application (PySide6).

A windowed chat over the forge Agent: project picker, semantic-index button,
router health indicator, settings, and named sessions. All network/CPU work runs
in worker threads so the UI stays responsive.
"""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QTextOption
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFrame,
    QLabel, QPushButton, QPlainTextEdit, QComboBox, QFileDialog, QInputDialog,
)

from forge.config import Config
from forge.agent import Agent, detect_stack
from forge.memory.conversations import ConversationStore

from .style import STYLESHEET, OK, ERR, TEXT_DIM, ACCENT
from .chat_view import ChatView
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
        self._history: list[dict] = self._store.load(self._conv_id)
        self._chat_worker: ChatWorker | None = None
        self._index_worker: IndexWorker | None = None
        self._health_worker: HealthWorker | None = None

        self.setWindowTitle("Iris Code — Forge")
        self.setWindowIcon(_app_icon())
        self.resize(940, 720)
        self.setMinimumSize(720, 520)
        self._build_ui()
        self._store.save(self._conv_id, self._history)

        self._refresh_sessions()
        self._chat.reset(self._history)
        self._update_project_label()
        self._check_health()

        # Periodic, lightweight health poll.
        self._health_timer = QTimer(self)
        self._health_timer.timeout.connect(self._check_health)
        self._health_timer.start(20000)

    # ── UI construction ────────────────────────────────────────────────

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_topbar())

        self._chat = ChatView()
        root.addWidget(self._chat, 1)

        root.addWidget(self._build_composer())
        self.setCentralWidget(central)

    def _build_topbar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("TopBar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(8)

        title = QLabel(f'<span style="color:{ACCENT};font-weight:800">✦ Iris Code</span>')
        lay.addWidget(title)

        lay.addSpacing(6)
        lay.addWidget(QLabel("Project:", objectName="ProjectLabel"))
        self._project_value = QLabel("none", objectName="ProjectValue")
        lay.addWidget(self._project_value)

        open_btn = QPushButton("Open…")
        open_btn.setToolTip("Choose the active project directory")
        open_btn.clicked.connect(self._on_open_project)
        lay.addWidget(open_btn)

        self._index_btn = QPushButton("Index")
        self._index_btn.setToolTip("Index the project for semantic code search")
        self._index_btn.clicked.connect(self._on_index)
        lay.addWidget(self._index_btn)

        lay.addStretch(1)

        self._session_combo = QComboBox()
        self._session_combo.setMinimumWidth(150)
        self._session_combo.activated.connect(self._on_session_selected)
        lay.addWidget(self._session_combo)

        new_btn = QPushButton("＋")
        new_btn.setToolTip("New session")
        new_btn.setFixedWidth(36)
        new_btn.clicked.connect(self._on_new_session)
        lay.addWidget(new_btn)

        self._status_dot = QLabel("●", objectName="StatusDot")
        self._status_dot.setStyleSheet(f"color:{TEXT_DIM}")
        self._status_dot.setToolTip("Router status")
        lay.addWidget(self._status_dot)
        self._status_text = QLabel("checking…")
        self._status_text.setStyleSheet(f"color:{TEXT_DIM}; font-size:12px;")
        self._status_text.setToolTip("hermes-router connection")
        lay.addWidget(self._status_text)

        settings_btn = QPushButton("⚙")
        settings_btn.setFixedWidth(36)
        settings_btn.setToolTip("Settings")
        settings_btn.clicked.connect(self._on_settings)
        lay.addWidget(settings_btn)

        return bar

    def _build_composer(self) -> QWidget:
        wrap = QWidget()
        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(12, 8, 12, 12)
        lay.setSpacing(8)

        self._composer = QPlainTextEdit()
        self._composer.setObjectName("Composer")
        self._composer.setPlaceholderText("Ask Forge to write, debug, run, or find code…  (Enter to send, Shift+Enter for newline)")
        self._composer.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self._composer.setFixedHeight(70)
        lay.addWidget(self._composer, 1)

        self._send_btn = QPushButton("Send")
        self._send_btn.setObjectName("Send")
        self._send_btn.setFixedHeight(70)
        self._send_btn.clicked.connect(self._on_send)
        lay.addWidget(self._send_btn)

        # Enter sends; Shift+Enter inserts a newline (handled by eventFilter).
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
        self._update_project_label()
        self._chat.add_system_note(f"Active project set to {resolved}")

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

    def _on_index(self) -> None:
        pd = self._config.project_dir
        if not pd or self._index_worker is not None:
            return
        self._index_btn.setEnabled(False)
        self._index_btn.setText("Indexing…")
        self._chat.add_system_note(f"Indexing {pd} …")
        self._index_worker = IndexWorker(self._agent, pd, force=False)
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

    def _on_settings(self) -> None:
        dlg = SettingsDialog(self._config, self)
        if dlg.exec():
            changed = dlg.apply_to(self._config)
            if changed:
                self._rebuild_agent()
            self._check_health()

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
        self._health_worker = HealthWorker(self._config.router_url)
        self._health_worker.result.connect(self._on_health)
        self._health_worker.start()

    def _on_health(self, ok: bool, detail: str) -> None:
        color = OK if ok else ERR
        self._status_dot.setStyleSheet(f"color:{color}")
        self._status_dot.setToolTip(f"Router: {detail}")
        self._status_text.setText("Connected" if ok else "Offline")
        self._status_text.setStyleSheet(f"color:{color if not ok else TEXT_DIM}; font-size:12px;")
        self._status_text.setToolTip(
            f"hermes-router at {self._config.router_url} — {detail}"
            + ("" if ok else "\nStart your router, or change the URL in Settings (⚙).")
        )
        self._health_worker = None

    # ── lifecycle ──────────────────────────────────────────────────────

    def closeEvent(self, event):  # noqa: N802
        try:
            if self._chat_worker is not None:
                self._chat_worker.wait(2000)
            self._store.save(self._conv_id, self._history)
            self._agent.close()
            self._store.close()
        except Exception:
            pass
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Iris Code")
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
