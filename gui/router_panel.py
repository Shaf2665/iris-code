"""
Router Control Center — configure and run the hermes-router from the GUI.

Header: the hermes-router folder (the one with docker-compose.yml + .env), which
drives both the provider/key editor and the lifecycle buttons.

Tabs:
  • Status   — connection, providers, models, latency; Start / Stop / Restart / Update
               (docker compose in the router folder), with output.
  • Providers — a row per provider (enable via key, masked key field, optional model
               override, "Get key" link); Save writes the router's .env.
  • Logs     — `docker compose logs` tail.

All docker/HTTP/file work runs in CallWorker threads so a multi-minute
`compose up --build` never freezes the dialog.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout,
    QLabel, QPushButton, QPlainTextEdit, QLineEdit, QSpinBox, QFileDialog,
    QScrollArea, QCheckBox, QFrame,
)

from forge.config import Config
from forge.router import RouterAdmin, PROVIDERS
from .worker import CallWorker
from .style import OK, ERR, TEXT_DIM, ACCENT, CYAN, BORDER

_MONO = 'font-family:"Cascadia Code","Consolas","DejaVu Sans Mono",monospace; font-size:12px;'
_PROXY_VAR = "PROXY_API_KEYS"


class RouterDialog(QDialog):
    router_changed = Signal()

    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self._config = config
        self._admin = RouterAdmin(
            config.router_url, config.api_key, config.router_container,
            config.router_config_path, config.router_dir,
        )
        self._workers: set[CallWorker] = set()
        self._rows: dict[str, dict] = {}

        self.setWindowTitle("Iris Code — Router")
        self.setMinimumSize(720, 600)

        root = QVBoxLayout(self)
        root.addWidget(self._build_header())

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_status_tab(), "Status")
        self._tabs.addTab(self._build_providers_tab(), "Providers")
        self._tabs.addTab(self._build_logs_tab(), "Logs")
        root.addWidget(self._tabs)

        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        bottom.addWidget(close)
        root.addLayout(bottom)

        self.refresh_status()
        self._load_providers()

    # ── worker helper ──────────────────────────────────────────────────

    def _run(self, fn, on_result, on_error=None) -> None:
        worker = CallWorker("", fn)

        def _done(_t, res):
            self._workers.discard(worker)
            on_result(res)

        def _fail(_t, err):
            self._workers.discard(worker)
            (on_error or (lambda e: self._set_action(f"Error: {e}", ERR)))(err)

        worker.done.connect(_done)
        worker.failed.connect(_fail)
        self._workers.add(worker)
        worker.start()

    # ── header: router folder ──────────────────────────────────────────

    def _build_header(self) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 6)
        lay.addWidget(QLabel("hermes-router folder:"))
        self._dir_edit = QLineEdit(self._config.router_dir)
        self._dir_edit.setPlaceholderText("Folder containing docker-compose.yml and .env")
        self._dir_edit.editingFinished.connect(self._sync_dir)
        lay.addWidget(self._dir_edit, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_dir)
        lay.addWidget(browse)
        return w

    def _sync_dir(self) -> None:
        self._config.router_dir = self._dir_edit.text().strip()
        self._config.save_overrides()
        self._admin.router_dir = self._config.router_dir

    def _browse_dir(self) -> None:
        start = self._dir_edit.text().strip() or os.path.expanduser("~")
        path = QFileDialog.getExistingDirectory(self, "Select the hermes-router folder", start)
        if path:
            self._dir_edit.setText(path)
            self._sync_dir()
            self._load_providers()

    # ── Status tab ─────────────────────────────────────────────────────

    def _build_status_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        form = QFormLayout()
        self._conn_lbl = QLabel("checking…")
        self._latency_lbl = QLabel("—")
        self._providers_lbl = QLabel("—"); self._providers_lbl.setWordWrap(True)
        self._models_lbl = QLabel("—"); self._models_lbl.setWordWrap(True)
        form.addRow("Connection", self._conn_lbl)
        form.addRow("Latency", self._latency_lbl)
        form.addRow("Live providers", self._providers_lbl)
        form.addRow("Models", self._models_lbl)
        lay.addLayout(form)

        row = QHBoxLayout()
        self._start_btn = QPushButton("Start")
        self._stop_btn = QPushButton("Stop")
        self._restart_btn = QPushButton("Restart")
        self._update_btn = QPushButton("Update")
        self._update_btn.setObjectName("Send")
        refresh = QPushButton("Refresh")
        self._start_btn.clicked.connect(lambda: self._lifecycle("up"))
        self._stop_btn.clicked.connect(lambda: self._lifecycle("down"))
        self._restart_btn.clicked.connect(lambda: self._lifecycle("restart"))
        self._update_btn.clicked.connect(lambda: self._lifecycle("update"))
        refresh.clicked.connect(self.refresh_status)
        for b in (self._start_btn, self._stop_btn, self._restart_btn, self._update_btn):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(refresh)
        lay.addLayout(row)

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

    def _apply_models(self, models: list[str]) -> None:
        if models:
            shown = ", ".join(models[:8]) + (f"  (+{len(models) - 8})" if len(models) > 8 else "")
            self._models_lbl.setText(f"{len(models)}: {shown}")
        else:
            self._models_lbl.setText("—")

    def _lifecycle(self, action: str) -> None:
        self._sync_dir()
        if not self._config.router_dir:
            self._set_action("Set the hermes-router folder above first.", ERR)
            return
        verb = {"up": "Starting", "down": "Stopping", "restart": "Restarting",
                "update": "Updating (git pull + rebuild — can take a few minutes)"}[action]
        self._set_action(f"{verb}…", ACCENT)
        for b in (self._start_btn, self._stop_btn, self._restart_btn, self._update_btn):
            b.setEnabled(False)
        fn = {"up": self._admin.compose_up, "down": self._admin.compose_down,
              "restart": self._admin.compose_restart, "update": self._admin.compose_update}[action]

        def _done(result):
            ok, out = result
            self._set_action(out.strip()[:1200], OK if ok else ERR)
            for b in (self._start_btn, self._stop_btn, self._restart_btn, self._update_btn):
                b.setEnabled(True)
            self.router_changed.emit()
            self.refresh_status()

        self._run(fn, _done)

    def _set_action(self, text: str, color: str) -> None:
        self._action_lbl.setText(text)
        self._action_lbl.setStyleSheet(f"color:{color}; {_MONO}")

    # ── Providers tab ──────────────────────────────────────────────────

    def _build_providers_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        top = QHBoxLayout()
        top.addWidget(QLabel("Client key (PROXY_API_KEYS):"))
        self._proxy_edit = QLineEdit()
        self._proxy_edit.setPlaceholderText("the key Iris Code uses to call the router")
        top.addWidget(self._proxy_edit, 1)
        self._show_keys = QCheckBox("Show keys")
        self._show_keys.toggled.connect(self._toggle_key_echo)
        top.addWidget(self._show_keys)
        lay.addLayout(top)

        hint = QLabel("Enter one or more keys per provider (comma-separated). Empty disables a provider. "
                      "Save writes the router's .env; Start/Restart it from the Status tab to apply.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{TEXT_DIM};")
        lay.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        grid = QGridLayout(inner)
        grid.setColumnStretch(1, 3)
        grid.setColumnStretch(2, 2)
        r = 0
        for prov in PROVIDERS:
            name = QLabel(f"<b>{prov['label']}</b>")
            name.setToolTip(prov["note"])
            link = QLabel(f'<a href="{prov["url"]}" style="color:{CYAN}">Get key →</a>')
            link.setOpenExternalLinks(True)
            keys = QLineEdit(); keys.setEchoMode(QLineEdit.Password)
            keys.setPlaceholderText(f"{prov['keys_var']}  (comma-separated)")
            model = QLineEdit(); model.setPlaceholderText("model override (optional)")
            self._rows[prov["id"]] = {"keys": keys, "model": model, "prov": prov}
            head = QHBoxLayout(); hw = QWidget(); hw.setLayout(head)
            head.setContentsMargins(0, 0, 0, 0)
            head.addWidget(name); head.addSpacing(8)
            note = QLabel(prov["note"]); note.setStyleSheet(f"color:{TEXT_DIM}; font-size:11px;")
            head.addWidget(note); head.addStretch(1); head.addWidget(link)
            grid.addWidget(hw, r, 0, 1, 3); r += 1
            grid.addWidget(keys, r, 0, 1, 2)
            grid.addWidget(model, r, 2)
            r += 1
            sep = QFrame(); sep.setFrameShape(QFrame.HLine)
            sep.setStyleSheet(f"color:{BORDER};")
            grid.addWidget(sep, r, 0, 1, 3); r += 1
        scroll.setWidget(inner)
        lay.addWidget(scroll, 1)

        self._prov_msg = QLabel("")
        self._prov_msg.setWordWrap(True)
        self._prov_msg.setStyleSheet(f"color:{TEXT_DIM}; {_MONO}")
        lay.addWidget(self._prov_msg)

        btns = QHBoxLayout()
        reload_btn = QPushButton("Reload")
        reload_btn.clicked.connect(self._load_providers)
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(lambda: self._save_providers(restart=False))
        save_restart = QPushButton("Save & Restart")
        save_restart.setObjectName("Send")
        save_restart.clicked.connect(lambda: self._save_providers(restart=True))
        btns.addWidget(reload_btn)
        btns.addStretch(1)
        btns.addWidget(save_btn)
        btns.addWidget(save_restart)
        lay.addLayout(btns)
        return w

    def _toggle_key_echo(self, show: bool) -> None:
        mode = QLineEdit.Normal if show else QLineEdit.Password
        self._proxy_edit.setEchoMode(mode)
        for row in self._rows.values():
            row["keys"].setEchoMode(mode)

    def _load_providers(self) -> None:
        self._sync_dir()
        env = self._admin.read_env_vars()
        self._proxy_edit.setText(env.get(_PROXY_VAR, ""))
        for prov in PROVIDERS:
            row = self._rows.get(prov["id"])
            if row:
                row["keys"].setText(env.get(prov["keys_var"], ""))
                row["model"].setText(env.get(prov["model_var"], ""))
        if not self._config.router_dir:
            self._prov_msg.setText("Set the hermes-router folder above to load/save keys.")
            self._prov_msg.setStyleSheet(f"color:{ACCENT}; {_MONO}")
        else:
            self._prov_msg.setText(f"Loaded {self._admin.env_path()}")
            self._prov_msg.setStyleSheet(f"color:{TEXT_DIM}; {_MONO}")

    def _save_providers(self, restart: bool) -> None:
        self._sync_dir()
        if not self._config.router_dir:
            self._prov_msg.setText("Set the hermes-router folder first.")
            self._prov_msg.setStyleSheet(f"color:{ERR}; {_MONO}")
            return
        updates: dict[str, str] = {_PROXY_VAR: self._proxy_edit.text().strip()}
        for prov in PROVIDERS:
            row = self._rows[prov["id"]]
            updates[prov["keys_var"]] = row["keys"].text().strip()
            updates[prov["model_var"]] = row["model"].text().strip()
        ok, msg = self._admin.write_env_vars(updates)
        self._prov_msg.setText(msg)
        self._prov_msg.setStyleSheet(f"color:{OK if ok else ERR}; {_MONO}")
        self.router_changed.emit()
        if ok and restart:
            self._tabs.setCurrentIndex(0)
            self._lifecycle("restart")

    # ── Logs tab ───────────────────────────────────────────────────────

    def _build_logs_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Tail lines:"))
        self._tail_spin = QSpinBox(); self._tail_spin.setRange(10, 5000)
        self._tail_spin.setValue(200); self._tail_spin.setSingleStep(50)
        controls.addWidget(self._tail_spin)
        controls.addStretch(1)
        fetch = QPushButton("Fetch logs")
        fetch.clicked.connect(self._refresh_logs)
        controls.addWidget(fetch)
        lay.addLayout(controls)

        self._logs_view = QPlainTextEdit()
        self._logs_view.setReadOnly(True)
        self._logs_view.setStyleSheet(_MONO)
        self._logs_view.setPlaceholderText("Click 'Fetch logs' to tail `docker compose logs` for the router.")
        lay.addWidget(self._logs_view, 1)
        return w

    def _refresh_logs(self) -> None:
        self._sync_dir()
        self._logs_view.setPlainText("Fetching…")
        tail = self._tail_spin.value()
        self._run(lambda: self._admin.compose_logs(tail), self._logs_view.setPlainText)
