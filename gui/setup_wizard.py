"""
First-run setup wizard — get hermes-router running with one click.

Pipeline (in SetupWorker, off the UI thread, with streamed progress):
  1. git clone (or pull) hermes-router into the chosen folder
  2. write a minimal .env (PORT + the client key Iris Code uses)
  3. optionally add one provider key
  4. docker compose up -d --build   (streamed line-by-line)
  5. poll /health until the router answers

The dialog gates the run on Docker actually running (Docker Desktop / engine),
with a Re-check button, so a newcomer gets a clear message instead of a failure.
"""
from __future__ import annotations

import os
import subprocess
import time

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QPlainTextEdit, QFileDialog,
)

from forge.config import Config
from forge.router import RouterAdmin, PROVIDERS, default_router_dir
from .worker import CallWorker
from .style import OK, ERR, TEXT_DIM, ACCENT

_MONO = 'font-family:"Cascadia Code","Consolas","DejaVu Sans Mono",monospace; font-size:12px;'


class SetupWorker(QThread):
    progress = Signal(str)
    done = Signal(bool, str)

    def __init__(self, admin: RouterAdmin, dest: str, proxy_key: str,
                 provider_id: str, provider_key: str, parent=None):
        super().__init__(parent)
        self._admin = admin
        self._dest = dest
        self._proxy_key = proxy_key
        self._provider_id = provider_id
        self._provider_key = provider_key

    def run(self) -> None:
        self.progress.emit("Downloading hermes-router…")
        ok, out = self._admin.clone_or_update(self._dest)
        self.progress.emit(out)
        if not ok:
            return self.done.emit(False, "Download failed — is git installed and online?")
        self._admin.router_dir = self._dest

        self.progress.emit("Preparing configuration (.env)…")
        ok, out = self._admin.ensure_env(self._proxy_key)
        self.progress.emit(out)
        if not ok:
            return self.done.emit(False, "Could not write configuration.")

        if self._provider_id and self._provider_key:
            prov = next((p for p in PROVIDERS if p["id"] == self._provider_id), None)
            if prov:
                self._admin.write_env_vars({prov["keys_var"]: self._provider_key})
                self.progress.emit(f"Added a {prov['label']} key.")

        self.progress.emit("Building the image and starting the container "
                           "(the first build can take a few minutes)…")
        if not self._stream_build():
            return self.done.emit(False, "Build/start failed — see the log above.")

        self.progress.emit("Waiting for the router to come online…")
        for _ in range(20):
            if self._admin.health().get("ok"):
                return self.done.emit(True, "hermes-router is running 🎉")
            time.sleep(2)
        self.done.emit(True, "Container started; the router isn't answering yet — check Logs.")

    def _stream_build(self) -> bool:
        try:
            proc = subprocess.Popen(
                ["docker", "compose", "up", "-d", "--build"],
                cwd=self._dest, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
            for line in proc.stdout:  # type: ignore[union-attr]
                self.progress.emit(line.rstrip())
            proc.wait()
            return proc.returncode == 0
        except FileNotFoundError:
            self.progress.emit("docker is not installed or not on PATH.")
            return False
        except Exception as e:  # noqa: BLE001
            self.progress.emit(str(e))
            return False


class SetupDialog(QDialog):
    setup_done = Signal(str)  # the folder hermes-router was set up in

    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self._config = config
        self._admin = RouterAdmin(config.router_url, config.api_key)
        self._worker: SetupWorker | None = None
        self._probe: CallWorker | None = None
        self._docker_ok = False

        self.setWindowTitle("Iris Code — Set up hermes-router")
        self.setMinimumSize(640, 560)

        intro = QLabel(
            "Iris Code talks to a local <b>hermes-router</b> that fans out to free LLM "
            "providers. This will download it, configure it, and start it in Docker — "
            "no terminal needed."
        )
        intro.setWordWrap(True)

        # Docker status row
        self._docker_lbl = QLabel("Checking Docker…")
        self._docker_lbl.setWordWrap(True)
        recheck = QPushButton("Re-check")
        recheck.clicked.connect(self._check_docker)
        drow = QHBoxLayout()
        drow.addWidget(QLabel("Docker:"))
        drow.addWidget(self._docker_lbl, 1)
        drow.addWidget(recheck)

        # Folder + optional provider key
        form = QFormLayout()
        self._dir_edit = QLineEdit(self._config.router_dir or default_router_dir())
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        dir_row = QHBoxLayout(); dir_row.addWidget(self._dir_edit, 1); dir_row.addWidget(browse)
        form.addRow("Install folder", _wrap(dir_row))

        self._prov_combo = QComboBox()
        self._prov_combo.addItem("— none (add later in Router → Providers) —", "")
        for p in PROVIDERS:
            self._prov_combo.addItem(p["label"], p["id"])
        self._prov_key = QLineEdit(); self._prov_key.setEchoMode(QLineEdit.Password)
        self._prov_key.setPlaceholderText("optional: paste one free provider key to start chatting right away")
        form.addRow("Add a key (optional)", self._prov_combo)
        form.addRow("", self._prov_key)

        self._run_btn = QPushButton("Set up & Start")
        self._run_btn.setObjectName("Send")
        self._run_btn.clicked.connect(self._on_run)
        self._close_btn = QPushButton("Not now")
        self._close_btn.clicked.connect(self._on_dismiss)
        btn_row = QHBoxLayout()
        btn_row.addWidget(self._close_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self._run_btn)

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setStyleSheet(_MONO)
        self._log.setPlaceholderText("Setup progress will appear here.")

        lay = QVBoxLayout(self)
        lay.addWidget(intro)
        lay.addLayout(drow)
        lay.addLayout(form)
        lay.addWidget(self._log, 1)
        lay.addLayout(btn_row)

        self._check_docker()

    # ── docker gating ──────────────────────────────────────────────────

    def _check_docker(self) -> None:
        self._docker_lbl.setText("Checking…")
        self._docker_lbl.setStyleSheet(f"color:{TEXT_DIM}")
        self._run_btn.setEnabled(False)
        self._probe = CallWorker("", RouterAdmin.docker_status)
        self._probe.done.connect(lambda _t, res: self._apply_docker(res))
        self._probe.failed.connect(lambda _t, err: self._apply_docker({"running": False, "detail": err}))
        self._probe.start()

    def _apply_docker(self, status: dict) -> None:
        self._docker_ok = bool(status.get("running"))
        self._docker_lbl.setText(status.get("detail", ""))
        self._docker_lbl.setStyleSheet(f"color:{OK if self._docker_ok else ERR}")
        self._run_btn.setEnabled(self._docker_ok)

    # ── run ────────────────────────────────────────────────────────────

    def _browse(self) -> None:
        start = self._dir_edit.text().strip() or os.path.expanduser("~")
        path = QFileDialog.getExistingDirectory(self, "Choose install folder", start)
        if path:
            self._dir_edit.setText(os.path.join(path, "hermes-router")
                                   if not path.rstrip("/").endswith("hermes-router") else path)

    def _log_line(self, text: str) -> None:
        self._log.appendPlainText(text)

    def _on_run(self) -> None:
        if self._worker is not None:
            return
        dest = self._dir_edit.text().strip()
        if not dest:
            self._log_line("Please choose an install folder.")
            return
        self._run_btn.setEnabled(False); self._run_btn.setText("Setting up…")
        self._close_btn.setEnabled(False)
        self._log.clear()
        self._worker = SetupWorker(
            self._admin, dest, self._config.api_key,
            self._prov_combo.currentData(), self._prov_key.text().strip(),
        )
        self._worker.progress.connect(self._log_line)
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def _on_done(self, ok: bool, msg: str) -> None:
        self._log_line(("✓ " if ok else "✗ ") + msg)
        self._worker = None
        self._run_btn.setText("Set up & Start"); self._run_btn.setEnabled(True)
        self._close_btn.setEnabled(True); self._close_btn.setText("Close")
        if ok:
            dest = self._dir_edit.text().strip()
            self._config.router_dir = dest
            self._config.setup_dismissed = False
            self._config.save_overrides()
            self.setup_done.emit(dest)

    def _on_dismiss(self) -> None:
        # Remember the dismissal so we don't nag on every launch.
        self._config.setup_dismissed = True
        self._config.save_overrides()
        self.reject()


def _wrap(layout) -> QLabel:
    from PySide6.QtWidgets import QWidget
    w = QWidget(); w.setLayout(layout)
    return w
