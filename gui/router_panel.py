"""
Router Control Center — configure and run the hermes-router from the GUI.

Header: the hermes-router folder (the one with docker-compose.yml + .env), which
drives both the settings editors and the lifecycle commands.

Tabs:
  • Status    — connection, providers, models, latency, Docker; the full compose
                lifecycle (Start/Stop/Restart/Pull/Build/ps/Update), with output.
  • General   — curated .env settings (client key, rotation mode, port, log level,
                router model id, response cache, fast-route).
  • Providers — a per-provider list of API keys (masked, removable) + a model
                override; quick-add picks a provider and stacks keys.
  • Advanced  — a raw editor for the router's whole .env (everything not surfaced
                above: circuit breaker, per-provider skip/clamp, probe cache, …).
  • Logs      — `docker compose logs` tail, plus a live Follow stream.

All docker/HTTP/file work runs in CallWorker threads (or a QProcess for Follow) so
a multi-minute `compose up --build` never freezes the dialog.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Signal, QProcess
from PySide6.QtWidgets import (
    QDialog, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout,
    QLabel, QPushButton, QPlainTextEdit, QLineEdit, QSpinBox, QFileDialog,
    QScrollArea, QCheckBox, QFrame, QComboBox,
)

from forge.config import Config
from forge.router import RouterAdmin, PROVIDERS
from .worker import CallWorker
from .style import OK, ERR, TEXT_DIM, ACCENT, CYAN, BORDER

_MONO = 'font-family:"Cascadia Code","Consolas","DejaVu Sans Mono",monospace; font-size:12px;'
_PROXY_VAR = "PROXY_API_KEYS"


def _mask_key(k: str) -> str:
    tail = k[-4:] if len(k) > 4 else ""
    return "•" * max(6, min(len(k), 16)) + (f"…{tail}" if tail else "")


class _KeyList(QWidget):
    """A removable, masked list of a provider's API keys."""
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._keys: list[str] = []
        self._masked = True
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(3)
        self._render()

    def keys(self) -> list[str]:
        return list(self._keys)

    def set_keys(self, keys: list[str]) -> None:
        self._keys = [k.strip() for k in keys if k.strip()]
        self._render()

    def add(self, key: str) -> None:
        key = key.strip()
        if key and key not in self._keys:
            self._keys.append(key)
            self._render()
            self.changed.emit()

    def remove(self, key: str) -> None:
        if key in self._keys:
            self._keys.remove(key)
            self._render()
            self.changed.emit()

    def set_masked(self, masked: bool) -> None:
        self._masked = masked
        self._render()

    def _render(self) -> None:
        while self._lay.count():
            item = self._lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        if not self._keys:
            empty = QLabel("no keys yet — add one above")
            empty.setStyleSheet(f"color:{TEXT_DIM}; font-size:11px;")
            self._lay.addWidget(empty)
            return
        for key in self._keys:
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setSpacing(6)
            val = QLabel(_mask_key(key) if self._masked else key)
            val.setStyleSheet(_MONO)
            rl.addWidget(val, 1)
            rm = QPushButton("✕")
            rm.setFixedWidth(28)
            rm.setToolTip("Remove this key")
            rm.clicked.connect(lambda _checked=False, k=key: self.remove(k))
            rl.addWidget(rm)
            self._lay.addWidget(row)


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
        self._follow_proc: QProcess | None = None

        self.setWindowTitle("Iris Code — Router")
        self.setMinimumSize(760, 640)

        root = QVBoxLayout(self)
        root.addWidget(self._build_header())

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_status_tab(), "Status")
        self._tabs.addTab(self._build_general_tab(), "General")
        self._tabs.addTab(self._build_providers_tab(), "Providers")
        self._tabs.addTab(self._build_advanced_tab(), "Advanced")
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
        self._load_general()
        self._load_advanced()

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
            self._load_general()
            self._load_advanced()

    # ── Status tab ─────────────────────────────────────────────────────

    def _build_status_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        drow = QHBoxLayout()
        drow.addWidget(QLabel("Docker:"))
        self._docker_lbl = QLabel("checking…")
        self._docker_lbl.setWordWrap(True)
        drow.addWidget(self._docker_lbl, 1)
        setup_btn = QPushButton("Set up hermes-router")
        setup_btn.clicked.connect(self._open_setup)
        drow.addWidget(setup_btn)
        lay.addLayout(drow)

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

        # Lifecycle commands (the full compose set).
        self._lifecycle_btns: dict[str, QPushButton] = {}
        grid = QGridLayout()
        specs = [
            ("up", "Start"), ("down", "Stop"), ("restart", "Restart"),
            ("pull", "Pull"), ("build", "Build"), ("ps", "ps"),
            ("update", "Update"),
        ]
        for i, (action, label) in enumerate(specs):
            b = QPushButton(label)
            if action == "update":
                b.setObjectName("Send")
            b.clicked.connect(lambda _c=False, a=action: self._lifecycle(a))
            self._lifecycle_btns[action] = b
            grid.addWidget(b, i // 4, i % 4)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh_status)
        grid.addWidget(refresh, 1, 3)
        lay.addLayout(grid)

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
        self._run(RouterAdmin.docker_status, self._apply_docker)

    def _apply_docker(self, status: dict) -> None:
        running = bool(status.get("running"))
        self._docker_lbl.setText(status.get("detail", ""))
        self._docker_lbl.setStyleSheet(f"color:{OK if running else ERR}")
        # Lifecycle needs Docker — gate the buttons and explain why.
        for b in self._lifecycle_btns.values():
            b.setEnabled(running)
            b.setToolTip("" if running else "Start Docker Desktop / the Docker engine first.")

    def _open_setup(self) -> None:
        from .setup_wizard import SetupDialog
        dlg = SetupDialog(self._config, self)
        dlg.setup_done.connect(self._on_setup_done)
        dlg.exec()
        self.refresh_status()

    def _on_setup_done(self, folder: str) -> None:
        self._dir_edit.setText(folder)
        self._sync_dir()
        self._load_providers()
        self._load_general()
        self._load_advanced()
        self.router_changed.emit()

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
        verb = {
            "up": "Starting", "down": "Stopping", "restart": "Restarting",
            "pull": "Pulling images", "build": "Building image", "ps": "Querying status",
            "update": "Updating (git pull + rebuild — can take a few minutes)",
        }[action]
        self._set_action(f"{verb}…", ACCENT)
        for b in self._lifecycle_btns.values():
            b.setEnabled(False)
        fn = {
            "up": self._admin.compose_up, "down": self._admin.compose_down,
            "restart": self._admin.compose_restart, "pull": self._admin.compose_pull,
            "build": self._admin.compose_build, "ps": self._admin.compose_ps,
            "update": self._admin.compose_update,
        }[action]

        def _done(result):
            ok, out = result
            self._set_action(out.strip()[:1500], OK if ok else ERR)
            for b in self._lifecycle_btns.values():
                b.setEnabled(True)
            if action != "ps":
                self.router_changed.emit()
            self.refresh_status()

        self._run(fn, _done)

    def _set_action(self, text: str, color: str) -> None:
        self._action_lbl.setText(text)
        self._action_lbl.setStyleSheet(f"color:{color}; {_MONO}")

    # ── General tab (curated .env settings) ─────────────────────────────

    def _build_general_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        form = QFormLayout()
        form.setVerticalSpacing(9)

        self._g_proxy = QLineEdit(); self._g_proxy.setEchoMode(QLineEdit.Password)
        self._g_proxy.setPlaceholderText("the key Iris Code uses to call the router")
        prow = QHBoxLayout(); prow.setContentsMargins(0, 0, 0, 0)
        prow.addWidget(self._g_proxy, 1)
        g_show = QCheckBox("Show")
        g_show.toggled.connect(lambda s: self._g_proxy.setEchoMode(
            QLineEdit.Normal if s else QLineEdit.Password))
        prow.addWidget(g_show)
        form.addRow("Client key (PROXY_API_KEYS)", prow)

        self._g_rotation = QComboBox(); self._g_rotation.addItems(["round-robin", "sequential"])
        form.addRow("Key rotation (ROTATION_MODE)", self._g_rotation)

        self._g_port = QLineEdit(); self._g_port.setPlaceholderText("8319")
        form.addRow("Port (PORT)", self._g_port)

        self._g_loglevel = QComboBox()
        self._g_loglevel.addItems(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
        form.addRow("Log level (LOG_LEVEL)", self._g_loglevel)

        self._g_model_id = QLineEdit(); self._g_model_id.setPlaceholderText("hermes-router")
        form.addRow("Router model id (ROUTER_MODEL_ID)", self._g_model_id)

        self._g_cache_ttl = QLineEdit(); self._g_cache_ttl.setPlaceholderText("300  (0 = off)")
        form.addRow("Cache TTL secs (CACHE_TTL_SECONDS)", self._g_cache_ttl)
        self._g_cache_max = QLineEdit(); self._g_cache_max.setPlaceholderText("100")
        form.addRow("Cache max entries (CACHE_MAX_SIZE)", self._g_cache_max)
        self._g_fast = QLineEdit(); self._g_fast.setPlaceholderText("0  (0 = off)")
        form.addRow("Fast-route threshold (FAST_ROUTE_THRESHOLD)", self._g_fast)

        lay.addLayout(form)
        hint = QLabel("Empty a field to remove it and fall back to the router's default. "
                      "Less-common settings live in the Advanced (.env) tab.")
        hint.setWordWrap(True); hint.setStyleSheet(f"color:{TEXT_DIM};")
        lay.addWidget(hint)
        self._g_msg = QLabel(""); self._g_msg.setWordWrap(True)
        self._g_msg.setStyleSheet(f"color:{TEXT_DIM}; {_MONO}")
        lay.addWidget(self._g_msg)
        lay.addStretch(1)
        lay.addLayout(self._save_buttons(self._load_general,
                                         lambda: self._save_general(False),
                                         lambda: self._save_general(True)))
        return w

    def _load_general(self) -> None:
        self._sync_dir()
        env = self._admin.read_env_vars()
        self._g_proxy.setText(env.get(_PROXY_VAR, ""))
        self._g_rotation.setCurrentText(env.get("ROTATION_MODE", "round-robin")
                                        if env.get("ROTATION_MODE") in ("round-robin", "sequential")
                                        else "round-robin")
        self._g_port.setText(env.get("PORT", ""))
        lvl = env.get("LOG_LEVEL", "INFO").upper()
        if self._g_loglevel.findText(lvl) < 0:
            self._g_loglevel.addItem(lvl)
        self._g_loglevel.setCurrentText(lvl)
        self._g_model_id.setText(env.get("ROUTER_MODEL_ID", ""))
        self._g_cache_ttl.setText(env.get("CACHE_TTL_SECONDS", ""))
        self._g_cache_max.setText(env.get("CACHE_MAX_SIZE", ""))
        self._g_fast.setText(env.get("FAST_ROUTE_THRESHOLD", ""))
        self._set_msg(self._g_msg, self._loaded_text(), TEXT_DIM)

    def _save_general(self, restart: bool) -> None:
        self._sync_dir()
        if not self._config.router_dir:
            self._set_msg(self._g_msg, "Set the hermes-router folder first.", ERR)
            return
        updates = {
            _PROXY_VAR: self._g_proxy.text().strip(),
            "ROTATION_MODE": self._g_rotation.currentText(),
            "PORT": self._g_port.text().strip(),
            "LOG_LEVEL": self._g_loglevel.currentText(),
            "ROUTER_MODEL_ID": self._g_model_id.text().strip(),
            "CACHE_TTL_SECONDS": self._g_cache_ttl.text().strip(),
            "CACHE_MAX_SIZE": self._g_cache_max.text().strip(),
            "FAST_ROUTE_THRESHOLD": self._g_fast.text().strip(),
        }
        ok, msg = self._admin.write_env_vars(updates)
        self._set_msg(self._g_msg, msg, OK if ok else ERR)
        self.router_changed.emit()
        if ok and restart:
            self._tabs.setCurrentIndex(0)
            self._lifecycle("restart")

    # ── Providers tab ──────────────────────────────────────────────────

    def _build_providers_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        top = QHBoxLayout()
        top.addWidget(QLabel("Add key:"))
        self._quick_combo = QComboBox()
        for p in PROVIDERS:
            self._quick_combo.addItem(p["label"], p["id"])
        top.addWidget(self._quick_combo)
        self._quick_key = QLineEdit()
        self._quick_key.setEchoMode(QLineEdit.Password)
        self._quick_key.setPlaceholderText("paste an API key, then Add (repeat to add more)")
        self._quick_key.returnPressed.connect(self._quick_add)
        top.addWidget(self._quick_key, 1)
        add_btn = QPushButton("Add")
        add_btn.clicked.connect(self._quick_add)
        top.addWidget(add_btn)
        self._show_keys = QCheckBox("Show keys")
        self._show_keys.toggled.connect(self._toggle_key_echo)
        top.addWidget(self._show_keys)
        lay.addLayout(top)

        hint = QLabel("Keys are listed under their provider, masked by default. Save writes the "
                      "router's .env; Start/Restart it from the Status tab to apply.")
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
            keys = _KeyList()
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

        lay.addLayout(self._save_buttons(self._load_providers,
                                         lambda: self._save_providers(False),
                                         lambda: self._save_providers(True)))
        return w

    def _quick_add(self) -> None:
        pid = self._quick_combo.currentData()
        key = self._quick_key.text().strip()
        row = self._rows.get(pid)
        if not key or not row:
            return
        row["keys"].add(key)
        row["keys"].set_masked(not self._show_keys.isChecked())
        self._quick_key.clear()
        label = self._quick_combo.currentText()
        n = len(row["keys"].keys())
        self._set_msg(self._prov_msg, f"Added a key to {label} ({n} total). Click Save to write .env.", OK)

    def _toggle_key_echo(self, show: bool) -> None:
        for row in self._rows.values():
            row["keys"].set_masked(not show)

    def _load_providers(self) -> None:
        self._sync_dir()
        env = self._admin.read_env_vars()
        for prov in PROVIDERS:
            row = self._rows.get(prov["id"])
            if row:
                row["keys"].set_keys([k for k in env.get(prov["keys_var"], "").split(",")])
                row["keys"].set_masked(not self._show_keys.isChecked())
                row["model"].setText(env.get(prov["model_var"], ""))
        if not self._config.router_dir:
            self._set_msg(self._prov_msg, "Set the hermes-router folder above to load/save keys.", ACCENT)
        else:
            self._set_msg(self._prov_msg, self._loaded_text(), TEXT_DIM)

    def _save_providers(self, restart: bool) -> None:
        self._sync_dir()
        if not self._config.router_dir:
            self._set_msg(self._prov_msg, "Set the hermes-router folder first.", ERR)
            return
        updates: dict[str, str] = {}
        for prov in PROVIDERS:
            row = self._rows[prov["id"]]
            updates[prov["keys_var"]] = ",".join(row["keys"].keys())
            updates[prov["model_var"]] = row["model"].text().strip()
        ok, msg = self._admin.write_env_vars(updates)
        self._set_msg(self._prov_msg, msg, OK if ok else ERR)
        self.router_changed.emit()
        if ok and restart:
            self._tabs.setCurrentIndex(0)
            self._lifecycle("restart")

    # ── Advanced (.env) tab ─────────────────────────────────────────────

    def _build_advanced_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        note = QLabel("Raw .env editor — edits everything, including settings not shown elsewhere "
                      "(circuit breaker, per-provider skip/clamp, probe cache, server limits). "
                      "Save, then Restart from the Status tab to apply.")
        note.setWordWrap(True); note.setStyleSheet(f"color:{TEXT_DIM};")
        lay.addWidget(note)
        self._adv_edit = QPlainTextEdit()
        self._adv_edit.setStyleSheet(_MONO)
        self._adv_edit.setPlaceholderText("KEY=VALUE per line  (set the router folder above first)")
        lay.addWidget(self._adv_edit, 1)
        self._adv_msg = QLabel(""); self._adv_msg.setWordWrap(True)
        self._adv_msg.setStyleSheet(f"color:{TEXT_DIM}; {_MONO}")
        lay.addWidget(self._adv_msg)
        lay.addLayout(self._save_buttons(self._load_advanced,
                                         lambda: self._save_advanced(False),
                                         lambda: self._save_advanced(True)))
        return w

    def _load_advanced(self) -> None:
        self._sync_dir()
        ok, text = self._admin.read_env_text()
        if ok:
            self._adv_edit.setPlainText(text)
            self._set_msg(self._adv_msg, self._loaded_text(), TEXT_DIM)
        else:
            self._set_msg(self._adv_msg, text, ERR)

    def _save_advanced(self, restart: bool) -> None:
        self._sync_dir()
        ok, msg = self._admin.write_env_text(self._adv_edit.toPlainText())
        self._set_msg(self._adv_msg, msg, OK if ok else ERR)
        if ok:
            self._load_providers()
            self._load_general()
            self.router_changed.emit()
            if restart:
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
        self._follow_chk = QCheckBox("Follow")
        self._follow_chk.setToolTip("Stream `docker compose logs -f` live")
        self._follow_chk.toggled.connect(self._toggle_follow)
        controls.addWidget(self._follow_chk)
        controls.addStretch(1)
        fetch = QPushButton("Fetch logs")
        fetch.clicked.connect(self._refresh_logs)
        controls.addWidget(fetch)
        lay.addLayout(controls)

        self._logs_view = QPlainTextEdit()
        self._logs_view.setReadOnly(True)
        self._logs_view.setMaximumBlockCount(8000)
        self._logs_view.setStyleSheet(_MONO)
        self._logs_view.setPlaceholderText("Click 'Fetch logs' to tail the router, or toggle Follow to stream.")
        lay.addWidget(self._logs_view, 1)
        return w

    def _refresh_logs(self) -> None:
        self._sync_dir()
        self._logs_view.setPlainText("Fetching…")
        tail = self._tail_spin.value()
        self._run(lambda: self._admin.compose_logs(tail), self._logs_view.setPlainText)

    def _toggle_follow(self, on: bool) -> None:
        if on:
            self._sync_dir()
            if not self._config.router_dir:
                self._logs_view.appendPlainText("Set the hermes-router folder first.")
                self._follow_chk.setChecked(False)
                return
            self._start_follow()
        else:
            self._stop_follow()

    def _start_follow(self) -> None:
        self._stop_follow()
        proc = QProcess(self)
        proc.setWorkingDirectory(self._config.router_dir)
        proc.setProcessChannelMode(QProcess.MergedChannels)
        proc.readyReadStandardOutput.connect(self._on_follow_output)
        self._follow_proc = proc
        tail = self._tail_spin.value()
        proc.start("docker", ["compose", "logs", "-f", "--no-color", "--tail", str(tail)])

    def _on_follow_output(self) -> None:
        if self._follow_proc is None:
            return
        data = bytes(self._follow_proc.readAllStandardOutput()).decode("utf-8", "replace")
        if data:
            self._logs_view.appendPlainText(data.rstrip("\n"))
            sb = self._logs_view.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _stop_follow(self) -> None:
        if self._follow_proc is not None:
            self._follow_proc.readyReadStandardOutput.disconnect()
            self._follow_proc.kill()
            self._follow_proc.waitForFinished(500)
            self._follow_proc = None

    # ── shared helpers ─────────────────────────────────────────────────

    def _save_buttons(self, on_reload, on_save, on_save_restart) -> QHBoxLayout:
        btns = QHBoxLayout()
        reload_btn = QPushButton("Reload"); reload_btn.clicked.connect(on_reload)
        save_btn = QPushButton("Save"); save_btn.clicked.connect(on_save)
        save_restart = QPushButton("Save & Restart"); save_restart.setObjectName("Send")
        save_restart.clicked.connect(on_save_restart)
        btns.addWidget(reload_btn)
        btns.addStretch(1)
        btns.addWidget(save_btn)
        btns.addWidget(save_restart)
        return btns

    def _loaded_text(self) -> str:
        return f"Loaded {self._admin.env_path()}" if self._config.router_dir else "Set the router folder."

    def _set_msg(self, label: QLabel, text: str, color: str) -> None:
        label.setText(text)
        label.setStyleSheet(f"color:{color}; {_MONO}")

    def closeEvent(self, event):  # noqa: N802
        self._stop_follow()
        super().closeEvent(event)

    def reject(self):  # noqa: N802
        self._stop_follow()
        super().reject()

    def accept(self):  # noqa: N802
        self._stop_follow()
        super().accept()
