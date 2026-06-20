"""Settings dialog — choose the LLM provider Iris Code talks to.

Default is the local hermes-router; you can also point Iris Code at any
OpenAI-compatible endpoint (OpenAI, OpenRouter, a local server, another router)
via a preset or a custom base URL. Writes through Config.save_overrides().
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QComboBox, QLineEdit, QLabel, QPushButton, QHBoxLayout,
    QVBoxLayout, QSpinBox, QFrame,
)

from forge.config import Config
from .worker import CallWorker
from .style import OK, ERR, TEXT_DIM, ACCENT

# label -> (base_url or "" for hermes, default model, endpoint placeholder)
_PRESETS: list[tuple[str, str, str]] = [
    ("hermes-router (local)", "", "hermes-router"),
    ("OpenAI", "https://api.openai.com/v1", "gpt-4o-mini"),
    ("OpenRouter", "https://openrouter.ai/api/v1", "openai/gpt-4o-mini"),
    ("Custom (OpenAI-compatible)", "custom", ""),
]


class SettingsDialog(QDialog):
    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Iris Code — Settings")
        self.setMinimumSize(540, 460)
        self._config = config
        self._probe: CallWorker | None = None

        self._provider = QComboBox()
        for label, _base, _model in _PRESETS:
            self._provider.addItem(label)
        self._provider.currentIndexChanged.connect(self._on_preset)

        self._endpoint = QLineEdit()
        self._key = QLineEdit()
        self._key.setEchoMode(QLineEdit.Password)
        self._model = QLineEdit()

        self._shell_timeout = QSpinBox()
        self._shell_timeout.setRange(5, 600)
        self._shell_timeout.setSuffix(" s")
        self._shell_timeout.setValue(config.shell_timeout)
        self._max_history = QSpinBox()
        self._max_history.setRange(4, 200)
        self._max_history.setValue(config.max_history_messages)

        conn_hdr = QLabel("Connection")
        conn_hdr.setStyleSheet(f"color:{ACCENT}; font-weight:700;")

        form = QFormLayout()
        form.setVerticalSpacing(10)
        form.addRow(conn_hdr)
        form.addRow("Provider", self._provider)
        self._endpoint_label = QLabel("Router URL")
        form.addRow(self._endpoint_label, self._endpoint)
        form.addRow("API key", self._key)
        form.addRow("Model", self._model)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine); sep.setStyleSheet(f"color:{TEXT_DIM};")
        form.addRow(sep)
        beh_hdr = QLabel("Behaviour")
        beh_hdr.setStyleSheet(f"color:{ACCENT}; font-weight:700;")
        form.addRow(beh_hdr)
        form.addRow("Shell timeout", self._shell_timeout)
        form.addRow("Chat history kept", self._max_history)

        self._hint = QLabel("")
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet(f"color:{TEXT_DIM};")

        self._test_result = QLabel("")
        self._test_result.setTextFormat(Qt.RichText)
        test_btn = QPushButton("Test connection")
        test_btn.clicked.connect(self._on_test)
        test_row = QHBoxLayout()
        test_row.addWidget(test_btn)
        test_row.addWidget(self._test_result, 1)

        save_btn = QPushButton("Save"); save_btn.setObjectName("Send")
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel"); cancel_btn.clicked.connect(self.reject)
        btn_row = QHBoxLayout(); btn_row.addStretch(1); btn_row.addWidget(cancel_btn); btn_row.addWidget(save_btn)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._hint)
        layout.addLayout(test_row)
        layout.addStretch(1)
        layout.addLayout(btn_row)

        self._load_from_config()

    # ── preset/value wiring ────────────────────────────────────────────

    def _load_from_config(self) -> None:
        # Match current config to a preset, prefill its defaults, then restore
        # the actually-stored endpoint/key/model on top (stored values win).
        if self._config.is_custom_provider:
            base = self._config.base_url_override.strip()
            idx = next((i for i, (_, b, _) in enumerate(_PRESETS) if b and b != "custom" and b == base), 3)
        else:
            idx = 0
        self._provider.blockSignals(True)
        self._provider.setCurrentIndex(idx)
        self._provider.blockSignals(False)
        self._on_preset(idx)
        self._endpoint.setText(
            self._config.base_url_override.strip() if self._config.is_custom_provider
            else self._config.router_url
        )
        self._key.setText(self._config.api_key)
        self._model.setText(self._config.model)

    def _is_hermes(self) -> bool:
        return self._provider.currentIndex() == 0

    def _on_preset(self, idx: int) -> None:
        """Prefill canonical endpoint/model for the chosen preset (used on
        interactive switch; _load_from_config overrides afterwards on open)."""
        _label, base, model = _PRESETS[idx]
        if idx == 0:  # hermes-router
            self._endpoint_label.setText("Router URL")
            self._endpoint.setPlaceholderText("http://localhost:8319")
            self._endpoint.setText("http://localhost:8319")
            self._hint.setText("Local hermes-router. Default: http://localhost:8319")
        else:
            self._endpoint_label.setText("Base URL")
            self._endpoint.setPlaceholderText("https://…/v1")
            self._endpoint.setText("" if base == "custom" else base)
            self._hint.setText("Any OpenAI-compatible endpoint. Include the full path (usually ending in /v1).")
        if model:
            self._model.setText(model)

    def _effective_base(self) -> str:
        ep = self._endpoint.text().strip().rstrip("/")
        return (ep + "/v1") if self._is_hermes() else ep

    # ── test connection ────────────────────────────────────────────────

    def _on_test(self) -> None:
        self._test_result.setText(f'<span style="color:{TEXT_DIM}">testing…</span>')
        base = self._effective_base()
        key = self._key.text().strip()
        is_hermes = self._is_hermes()
        router_url = self._endpoint.text().strip()

        def probe():
            import httpx
            try:
                if is_hermes:
                    r = httpx.get(f"{router_url.rstrip('/')}/health", timeout=5)
                else:
                    r = httpx.get(f"{base}/models", headers={"Authorization": f"Bearer {key}"}, timeout=6)
                return (r.status_code == 200, "connected" if r.status_code == 200 else f"HTTP {r.status_code}")
            except Exception as e:  # noqa: BLE001
                return (False, str(e)[:70])

        self._probe = CallWorker("", probe)
        self._probe.done.connect(lambda _t, res: self._on_test_result(*res))
        self._probe.failed.connect(lambda _t, err: self._on_test_result(False, err))
        self._probe.start()

    def _on_test_result(self, ok: bool, detail: str) -> None:
        color = OK if ok else ERR
        label = "connected ✓" if ok else f"unreachable — {detail}"
        self._test_result.setText(f'<span style="color:{color}">{label}</span>')

    # ── apply ──────────────────────────────────────────────────────────

    def apply_to(self, config: Config) -> bool:
        """Write edited values into config. Returns True if the connection
        changed (so the caller rebuilds the Agent)."""
        new_key = self._key.text().strip() or "sk-router-hermes-1"
        new_model = self._model.text().strip() or "hermes-router"
        if self._is_hermes():
            new_url = self._endpoint.text().strip() or "http://localhost:8319"
            new_override = ""
        else:
            new_url = config.router_url
            new_override = self._endpoint.text().strip()

        changed = (
            new_url != config.router_url
            or new_key != config.api_key
            or new_model != config.model
            or new_override != config.base_url_override
        )
        config.router_url = new_url
        config.api_key = new_key
        config.model = new_model
        config.base_url_override = new_override
        config.shell_timeout = self._shell_timeout.value()
        config.max_history_messages = self._max_history.value()
        config.save_overrides()
        return changed
