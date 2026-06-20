"""
Router panel — observe and control the local hermes-router from the GUI.

Three tabs:
  • Status — connection, container state, providers, models, latency; Start/Stop/Restart.
  • Logs   — tail of `docker logs`.
  • Config — container name + config-file path, edit the router's config, Save / Save & Restart.

All router/docker/HTTP work runs in CallWorker threads so the dialog never freezes
on a slow `docker restart` or an unreachable router.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QPushButton, QPlainTextEdit, QLineEdit, QSpinBox, QFileDialog,
)

from forge.config import Config
from forge.router import RouterAdmin
from .worker import CallWorker
from .style import OK, ERR, TEXT_DIM, ACCENT, CYAN

_MONO = 'font-family:"Cascadia Code","Consolas","DejaVu Sans Mono",monospace; font-size:12px;'

_CONTAINER_COLORS = {
    "running": OK,
    "restarting": ACCENT,
    "paused": ACCENT,
    "exited": ERR,
    "dead": ERR,
    "missing": TEXT_DIM,
    "docker-missing": TEXT_DIM,
    "unknown": TEXT_DIM,
}


class RouterDialog(QDialog):
    # Emitted after a start/stop/restart or a config save, so the main window
    # can re-run its own health check.
    router_changed = Signal()

    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self._config = config
        self._admin = RouterAdmin(
            config.router_url, config.api_key, config.router_container, config.router_config_path
        )
        self._workers: set[CallWorker] = set()

        self.setWindowTitle("Iris Code — Router")
        self.setMinimumSize(640, 520)

        tabs = QTabWidget()
        tabs.addTab(self._build_status_tab(), "Status")
        tabs.addTab(self._build_logs_tab(), "Logs")
        tabs.addTab(self._build_config_tab(), "Config")

        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        bottom.addWidget(close)

        root = QVBoxLayout(self)
        root.addWidget(tabs)
        root.addLayout(bottom)

        self.refresh_status()

    # ── worker helper ──────────────────────────────────────────────────

    def _run(self, fn, on_result, on_error=None) -> None:
        worker = CallWorker("", fn)

        def _done(_tag, res):
            self._workers.discard(worker)
            on_result(res)

        def _fail(_tag, err):
            self._workers.discard(worker)
            (on_error or (lambda e: self._set_action(f"Error: {e}", ERR)))(err)

        worker.done.connect(_done)
        worker.failed.connect(_fail)
        self._workers.add(worker)
        worker.start()

    # ── Status tab ─────────────────────────────────────────────────────

    def _build_status_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        form = QFormLayout()
        self._conn_lbl = QLabel("checking…")
        self._container_lbl = QLabel("—")
        self._latency_lbl = QLabel("—")
        self._providers_lbl = QLabel("—")
        self._providers_lbl.setWordWrap(True)
        self._models_lbl = QLabel("—")
        self._models_lbl.setWordWrap(True)
        form.addRow("Connection", self._conn_lbl)
        form.addRow("Container", self._container_lbl)
        form.addRow("Latency", self._latency_lbl)
        form.addRow("Providers", self._providers_lbl)
        form.addRow("Models", self._models_lbl)
        lay.addLayout(form)

        btn_row = QHBoxLayout()
        self._start_btn = QPushButton("Start")
        self._stop_btn = QPushButton("Stop")
        self._restart_btn = QPushButton("Restart")
        self._restart_btn.setObjectName("Send")
        refresh_btn = QPushButton("Refresh")
        self._start_btn.clicked.connect(lambda: self._docker_action("start"))
        self._stop_btn.clicked.connect(lambda: self._docker_action("stop"))
        self._restart_btn.clicked.connect(lambda: self._docker_action("restart"))
        refresh_btn.clicked.connect(self.refresh_status)
        for b in (self._start_btn, self._stop_btn, self._restart_btn):
            btn_row.addWidget(b)
        btn_row.addStretch(1)
        btn_row.addWidget(refresh_btn)
        lay.addLayout(btn_row)

        self._action_lbl = QLabel("")
        self._action_lbl.setWordWrap(True)
        self._action_lbl.setStyleSheet(f"color:{TEXT_DIM}; {_MONO}")
        lay.addWidget(self._action_lbl)
        lay.addStretch(1)
        return w

    def refresh_status(self) -> None:
        self._conn_lbl.setText("checking…")
        self._conn_lbl.setStyleSheet(f"color:{TEXT_DIM}")
        self._run(self._admin.health, self._apply_health)
        self._run(lambda: self._admin.container_status(), self._apply_container)
        self._run(self._admin.models, self._apply_models)

    def _apply_health(self, h: dict) -> None:
        if h.get("ok"):
            self._conn_lbl.setText(f"Connected  ({h.get('status', 'ok')})")
            self._conn_lbl.setStyleSheet(f"color:{OK}")
            self._latency_lbl.setText(f"{h.get('latency_ms', '?')} ms")
            provs = h.get("providers", [])
            self._providers_lbl.setText(f"{len(provs)}: " + ", ".join(provs) if provs else "—")
        else:
            self._conn_lbl.setText(f"Offline — {h.get('error', 'unreachable')}")
            self._conn_lbl.setStyleSheet(f"color:{ERR}")
            self._latency_lbl.setText("—")
            self._providers_lbl.setText("—")

    def _apply_container(self, status: str) -> None:
        color = _CONTAINER_COLORS.get(status, TEXT_DIM)
        label = {
            "docker-missing": "docker not installed / not on PATH",
            "missing": f"no container named '{self._admin.container}'",
        }.get(status, status)
        self._container_lbl.setText(label)
        self._container_lbl.setStyleSheet(f"color:{color}")
        running = status == "running"
        self._start_btn.setEnabled(status not in ("running", "docker-missing"))
        self._stop_btn.setEnabled(running)
        self._restart_btn.setEnabled(status not in ("docker-missing", "missing"))

    def _apply_models(self, models: list[str]) -> None:
        if models:
            shown = ", ".join(models[:8]) + (f"  (+{len(models) - 8} more)" if len(models) > 8 else "")
            self._models_lbl.setText(f"{len(models)}: {shown}")
        else:
            self._models_lbl.setText("—")

    def _docker_action(self, action: str) -> None:
        self._set_action(f"Running docker {action} {self._admin.container}…", ACCENT)
        for b in (self._start_btn, self._stop_btn, self._restart_btn):
            b.setEnabled(False)
        fn = {"start": self._admin.start, "stop": self._admin.stop, "restart": self._admin.restart}[action]

        def _done(result):
            ok, out = result
            self._set_action((out or f"{action} done").strip()[:400], OK if ok else ERR)
            self.router_changed.emit()
            self.refresh_status()

        self._run(fn, _done)

    def _set_action(self, text: str, color: str) -> None:
        self._action_lbl.setText(text)
        self._action_lbl.setStyleSheet(f"color:{color}; {_MONO}")

    # ── Logs tab ───────────────────────────────────────────────────────

    def _build_logs_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Tail lines:"))
        self._tail_spin = QSpinBox()
        self._tail_spin.setRange(10, 5000)
        self._tail_spin.setValue(200)
        self._tail_spin.setSingleStep(50)
        controls.addWidget(self._tail_spin)
        controls.addStretch(1)
        refresh = QPushButton("Fetch logs")
        refresh.clicked.connect(self._refresh_logs)
        controls.addWidget(refresh)
        lay.addLayout(controls)

        self._logs_view = QPlainTextEdit()
        self._logs_view.setReadOnly(True)
        self._logs_view.setStyleSheet(_MONO)
        self._logs_view.setPlaceholderText("Click 'Fetch logs' to tail `docker logs` for the router container.")
        lay.addWidget(self._logs_view, 1)
        return w

    def _refresh_logs(self) -> None:
        self._logs_view.setPlainText("Fetching…")
        tail = self._tail_spin.value()
        self._run(lambda: self._admin.logs(tail), self._logs_view.setPlainText)

    # ── Config tab ─────────────────────────────────────────────────────

    def _build_config_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        form = QFormLayout()
        self._container_edit = QLineEdit(self._config.router_container)
        form.addRow("Container name", self._container_edit)

        path_row = QHBoxLayout()
        self._path_edit = QLineEdit(self._config.router_config_path)
        self._path_edit.setPlaceholderText("Path to the router's .env / config file")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_config)
        path_row.addWidget(self._path_edit, 1)
        path_row.addWidget(browse)
        form.addRow("Config file", path_row)
        lay.addLayout(form)

        load_row = QHBoxLayout()
        load_btn = QPushButton("Load")
        load_btn.clicked.connect(self._load_config)
        load_row.addStretch(1)
        load_row.addWidget(load_btn)
        lay.addLayout(load_row)

        self._config_edit = QPlainTextEdit()
        self._config_edit.setStyleSheet(_MONO)
        self._config_edit.setPlaceholderText("Load the router config file to view/edit it here.")
        lay.addWidget(self._config_edit, 1)

        self._config_msg = QLabel("")
        self._config_msg.setWordWrap(True)
        self._config_msg.setStyleSheet(f"color:{TEXT_DIM}; {_MONO}")
        lay.addWidget(self._config_msg)

        save_row = QHBoxLayout()
        save_row.addStretch(1)
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(lambda: self._save_config(restart=False))
        save_restart = QPushButton("Save & Restart")
        save_restart.setObjectName("Send")
        save_restart.clicked.connect(lambda: self._save_config(restart=True))
        save_row.addWidget(save_btn)
        save_row.addWidget(save_restart)
        lay.addLayout(save_row)
        return w

    def _sync_admin_from_fields(self) -> None:
        """Push edited container/path into config (persisted) and the admin."""
        self._config.router_container = self._container_edit.text().strip() or "hermes-router"
        self._config.router_config_path = self._path_edit.text().strip()
        self._config.save_overrides()
        self._admin.container = self._config.router_container
        self._admin.config_path = self._config.router_config_path

    def _browse_config(self) -> None:
        start = self._path_edit.text().strip() or os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(self, "Select router config file", start)
        if path:
            self._path_edit.setText(path)

    def _load_config(self) -> None:
        self._sync_admin_from_fields()
        ok, content = self._admin.read_config()
        if ok:
            self._config_edit.setPlainText(content)
            self._config_msg.setText(f"Loaded {self._admin.config_path}")
            self._config_msg.setStyleSheet(f"color:{CYAN}; {_MONO}")
        else:
            self._config_msg.setText(content)
            self._config_msg.setStyleSheet(f"color:{ERR}; {_MONO}")

    def _save_config(self, restart: bool) -> None:
        self._sync_admin_from_fields()
        ok, msg = self._admin.write_config(self._config_edit.toPlainText())
        self._config_msg.setText(msg)
        self._config_msg.setStyleSheet(f"color:{OK if ok else ERR}; {_MONO}")
        self.router_changed.emit()
        if ok and restart:
            self._docker_action("restart")
