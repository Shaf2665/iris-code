"""Integrated terminal — a command runner docked at the bottom of the window.

Pragmatic, dependency-free: each entered line runs via QProcess in the project's
working directory (`bash -lc` on POSIX, `cmd /c` on Windows), with stdout+stderr
streamed into a read-only view. It is NOT a full PTY — interactive full-screen
programs (vim, htop) won't render — but it handles normal commands, builds and
tests. `cd` is intercepted to move the shell; `clear` wipes the view.
"""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt, QProcess, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit, QLineEdit, QLabel, QPushButton,
)

from .style import TEXT_DIM, ACCENT, OK, ERR


class _CommandInput(QLineEdit):
    """QLineEdit with Up/Down command history."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._history: list[str] = []
        self._pos = 0

    def remember(self, cmd: str) -> None:
        if cmd and (not self._history or self._history[-1] != cmd):
            self._history.append(cmd)
        self._pos = len(self._history)

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key_Up and self._history:
            self._pos = max(0, self._pos - 1)
            self.setText(self._history[self._pos])
            return
        if event.key() == Qt.Key_Down and self._history:
            self._pos = min(len(self._history), self._pos + 1)
            self.setText(self._history[self._pos] if self._pos < len(self._history) else "")
            return
        super().keyPressEvent(event)


class TerminalPanel(QWidget):
    cwd_changed = Signal(str)

    def __init__(self, cwd: str = "", parent=None):
        super().__init__(parent)
        self._cwd = cwd or os.path.expanduser("~")
        self._proc: QProcess | None = None

        mono = QFont("Cascadia Code")
        mono.setStyleHint(QFont.Monospace)
        mono.setPointSize(10)

        self._out = QPlainTextEdit()
        self._out.setObjectName("TerminalOut")
        self._out.setReadOnly(True)
        self._out.setFont(mono)
        self._out.setMaximumBlockCount(5000)

        self._prompt = QLabel()
        self._prompt.setStyleSheet(f"color:{ACCENT};")
        self._prompt.setFont(mono)
        self._input = _CommandInput()
        self._input.setFont(mono)
        self._input.setPlaceholderText("Run a command…  (cd to move, clear to wipe)")
        self._input.returnPressed.connect(self._on_enter)
        self._stop = QPushButton("Stop")
        self._stop.setEnabled(False)
        self._stop.clicked.connect(self._kill)

        row = QHBoxLayout()
        row.setContentsMargins(6, 2, 6, 4)
        row.setSpacing(6)
        row.addWidget(self._prompt)
        row.addWidget(self._input, 1)
        row.addWidget(self._stop)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._out, 1)
        lay.addLayout(row)

        self._refresh_prompt()

    # ── public ─────────────────────────────────────────────────────────

    def set_cwd(self, path: str) -> None:
        if path and os.path.isdir(path):
            self._cwd = path
            self._refresh_prompt()

    # ── prompt / output ─────────────────────────────────────────────────

    def _refresh_prompt(self) -> None:
        self._prompt.setText(self._short_cwd() + " $")

    def _short_cwd(self) -> str:
        home = os.path.expanduser("~")
        c = self._cwd
        if c.startswith(home):
            c = "~" + c[len(home):]
        return c if len(c) < 40 else "…" + c[-38:]

    def _append(self, text: str, color: str = "") -> None:
        if color:
            self._out.appendHtml(f'<span style="color:{color}; white-space:pre-wrap;">{text}</span>')
        else:
            self._out.appendPlainText(text)
        sb = self._out.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ── run ─────────────────────────────────────────────────────────────

    def _on_enter(self) -> None:
        cmd = self._input.text().strip()
        self._input.clear()
        if not cmd:
            return
        self._input.remember(cmd)
        self._append(f"{self._short_cwd()} $ {cmd}", ACCENT)

        if cmd == "clear":
            self._out.clear()
            return
        if cmd == "cd" or cmd.startswith("cd ") or cmd.startswith("cd\t"):
            self._chdir(cmd[2:].strip())
            return
        if self._proc is not None:
            self._append("(a command is already running — Stop it first)", ERR)
            return
        self._spawn(cmd)

    def _chdir(self, arg: str) -> None:
        target = os.path.expanduser(arg) if arg else os.path.expanduser("~")
        if not os.path.isabs(target):
            target = os.path.join(self._cwd, target)
        target = os.path.normpath(target)
        if os.path.isdir(target):
            self._cwd = target
            self._refresh_prompt()
            self.cwd_changed.emit(target)
        else:
            self._append(f"cd: no such directory: {arg}", ERR)

    def _spawn(self, cmd: str) -> None:
        proc = QProcess(self)
        proc.setWorkingDirectory(self._cwd)
        proc.setProcessChannelMode(QProcess.MergedChannels)
        proc.readyReadStandardOutput.connect(self._on_output)
        proc.finished.connect(self._on_finished)
        proc.errorOccurred.connect(self._on_error)
        self._proc = proc
        self._stop.setEnabled(True)
        if sys.platform == "win32":
            proc.start("cmd.exe", ["/c", cmd])
        else:
            shell = "/bin/bash" if os.path.exists("/bin/bash") else "/bin/sh"
            proc.start(shell, ["-lc", cmd])

    def _on_output(self) -> None:
        if self._proc is None:
            return
        data = bytes(self._proc.readAllStandardOutput()).decode("utf-8", "replace")
        if data:
            self._out.appendPlainText(data.rstrip("\n"))
            sb = self._out.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _on_finished(self, code: int, _status) -> None:
        self._on_output()
        if code != 0:
            self._append(f"[exit {code}]", ERR)
        else:
            self._append("[done]", OK)
        self._proc = None
        self._stop.setEnabled(False)

    def _on_error(self, _err) -> None:
        if self._proc is not None:
            self._append("(failed to start command)", ERR)
            self._proc = None
            self._stop.setEnabled(False)

    def _kill(self) -> None:
        if self._proc is not None:
            self._proc.kill()
            self._append("(stopped)", TEXT_DIM)

    def shutdown(self) -> None:
        if self._proc is not None:
            self._proc.kill()
            self._proc.waitForFinished(500)
