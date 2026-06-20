"""Settings dialog — edit the hermes-router connection and the model.

Writes through Config.save_overrides() to forge_settings.json. A "Test
connection" button pings /health off the UI thread. Changing the router URL or
key rebuilds the Agent in the main window (so the new endpoint takes effect).
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QLabel, QPushButton, QHBoxLayout, QVBoxLayout,
)

from forge.config import Config
from .worker import HealthWorker
from .style import OK, ERR, TEXT_DIM


class SettingsDialog(QDialog):
    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Iris Code — Settings")
        self.setMinimumWidth(440)
        self._config = config
        self._health: HealthWorker | None = None

        self._url = QLineEdit(config.router_url)
        self._key = QLineEdit(config.api_key)
        self._key.setEchoMode(QLineEdit.Password)
        self._model = QLineEdit(config.model)

        form = QFormLayout()
        form.addRow("Router URL", self._url)
        form.addRow("API key", self._key)
        form.addRow("Model", self._model)

        hint = QLabel("Forge connects to a local hermes-router. Default: http://localhost:8319")
        hint.setProperty("class", "dim")
        hint.setStyleSheet(f"color: {TEXT_DIM};")
        hint.setWordWrap(True)

        self._test_result = QLabel("")
        self._test_result.setTextFormat(Qt.RichText)

        test_btn = QPushButton("Test connection")
        test_btn.clicked.connect(self._on_test)

        save_btn = QPushButton("Save")
        save_btn.setObjectName("Send")
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)

        test_row = QHBoxLayout()
        test_row.addWidget(test_btn)
        test_row.addWidget(self._test_result, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(hint)
        layout.addLayout(test_row)
        layout.addStretch(1)
        layout.addLayout(btn_row)

    def _on_test(self) -> None:
        self._test_result.setText('<span style="color:%s">testing…</span>' % TEXT_DIM)
        self._health = HealthWorker(self._url.text().strip() or "http://localhost:8319")
        self._health.result.connect(self._on_test_result)
        self._health.start()

    def _on_test_result(self, ok: bool, detail: str) -> None:
        color = OK if ok else ERR
        label = "connected ✓" if ok else f"unreachable — {detail}"
        self._test_result.setText(f'<span style="color:{color}">{label}</span>')

    def apply_to(self, config: Config) -> bool:
        """Write edited values into config. Returns True if the connection
        (url/key) changed, so the caller knows to rebuild the Agent."""
        new_url = self._url.text().strip() or "http://localhost:8319"
        new_key = self._key.text().strip() or "sk-router-hermes-1"
        new_model = self._model.text().strip() or "hermes-router"
        changed = (new_url != config.router_url) or (new_key != config.api_key) or (new_model != config.model)
        config.router_url = new_url
        config.api_key = new_key
        config.model = new_model
        config.save_overrides()
        return changed
