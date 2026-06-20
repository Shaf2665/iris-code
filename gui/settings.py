"""Settings dialog — VS Code-style two-pane preferences.

Left: a category list (Connection · Behaviour · Appearance · Data). Right: a
scrollable list of sections + rows. Top: a search box that filters rows by label
or keyword. Connection points Iris Code at the local hermes-router or any
OpenAI-compatible endpoint; the rest tunes behaviour, appearance, and stored data.
Writes through Config.save_overrides().
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QComboBox, QLineEdit, QLabel, QPushButton, QHBoxLayout, QVBoxLayout,
    QSpinBox, QFrame, QMessageBox, QListWidget, QScrollArea, QWidget,
)

from forge.config import Config
from .worker import CallWorker
from .style import OK, ERR, TEXT_DIM, ACCENT, BORDER

# label -> (base_url or "" for hermes, default model, endpoint placeholder)
_PRESETS: list[tuple[str, str, str]] = [
    ("hermes-router (local)", "", "hermes-router"),
    ("OpenAI", "https://api.openai.com/v1", "gpt-4o-mini"),
    ("OpenRouter", "https://openrouter.ai/api/v1", "openai/gpt-4o-mini"),
    ("Custom (OpenAI-compatible)", "custom", ""),
]

_CATEGORIES = ["Connection", "Behaviour", "Appearance", "Data"]


class SettingsDialog(QDialog):
    # Emitted (after the user confirms) so the main window can wipe stored data.
    clear_history = Signal()      # conversations only
    clear_everything = Signal()   # conversations + personal memory + index

    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Iris Code — Settings")
        self.setMinimumSize(720, 540)
        self._config = config
        self._probe: CallWorker | None = None
        self._rows: list[tuple[str, QWidget, str]] = []   # (category, row_widget, search_text)
        self._sections: dict[str, QWidget] = {}           # category -> header widget

        # ── editable widgets ──
        self._provider = QComboBox()
        for label, _b, _m in _PRESETS:
            self._provider.addItem(label)
        self._provider.currentIndexChanged.connect(self._on_preset)
        self._endpoint = QLineEdit()
        self._endpoint_label = QLabel("Router URL")
        self._key = QLineEdit(); self._key.setEchoMode(QLineEdit.Password)
        self._model = QLineEdit()
        self._shell_timeout = QSpinBox(); self._shell_timeout.setRange(5, 600); self._shell_timeout.setSuffix(" s")
        self._shell_timeout.setValue(config.shell_timeout)
        self._max_history = QSpinBox(); self._max_history.setRange(4, 200)
        self._max_history.setValue(config.max_history_messages)
        self._editor_font = QSpinBox(); self._editor_font.setRange(6, 48); self._editor_font.setSuffix(" pt")
        self._editor_font.setValue(config.editor_font_size)

        self._hint = QLabel(""); self._hint.setWordWrap(True); self._hint.setStyleSheet(f"color:{TEXT_DIM};")
        self._test_result = QLabel(""); self._test_result.setTextFormat(Qt.RichText)
        test_btn = QPushButton("Test connection"); test_btn.clicked.connect(self._on_test)
        test_row = QWidget(); trl = QHBoxLayout(test_row); trl.setContentsMargins(0, 0, 0, 0)
        trl.addWidget(test_btn); trl.addWidget(self._test_result, 1)

        clear_hist_btn = QPushButton("Clear chat history"); clear_hist_btn.clicked.connect(self._on_clear_history)
        clear_all_btn = QPushButton("Clear everything"); clear_all_btn.clicked.connect(self._on_clear_everything)
        danger_row = QWidget(); drl = QHBoxLayout(danger_row); drl.setContentsMargins(0, 0, 0, 0)
        drl.addWidget(clear_hist_btn); drl.addWidget(clear_all_btn); drl.addStretch(1)

        # ── right pane: sections + rows ──
        self._body = QWidget()
        self._body_lay = QVBoxLayout(self._body)
        self._body_lay.setContentsMargins(4, 0, 8, 0)
        self._body_lay.setSpacing(6)

        self._section("Connection")
        self._add_row("Connection", "Provider", self._provider, "provider preset endpoint")
        self._add_labeled("Connection", self._endpoint_label, self._endpoint, "router base url endpoint host")
        self._add_row("Connection", "API key", self._key, "api key token secret")
        self._add_row("Connection", "Model", self._model, "model name")
        self._add_full("Connection", self._hint, "connection hint")
        self._add_full("Connection", test_row, "test connection check")

        self._section("Behaviour")
        self._add_row("Behaviour", "Shell timeout", self._shell_timeout, "shell timeout command seconds")
        self._add_row("Behaviour", "Chat history kept", self._max_history, "chat history messages kept")

        self._section("Appearance")
        self._add_row("Appearance", "Editor font size", self._editor_font, "editor font size points appearance")

        self._section("Data")
        ddesc = QLabel("Permanently delete stored conversations, memory, and the code index.")
        ddesc.setWordWrap(True); ddesc.setStyleSheet(f"color:{TEXT_DIM};")
        self._add_full("Data", ddesc, "data danger zone")
        self._add_full("Data", danger_row, "clear chat history everything reset wipe data")
        self._body_lay.addStretch(1)

        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(self._body)
        scroll.setFrameShape(QFrame.NoFrame)
        self._scroll = scroll

        # ── left nav + search ──
        self._nav = QListWidget(); self._nav.setMaximumWidth(170); self._nav.setObjectName("SettingsNav")
        self._nav.addItems(_CATEGORIES)
        self._nav.currentTextChanged.connect(self._scroll_to)
        self._nav.setCurrentRow(0)

        self._search = QLineEdit(); self._search.setPlaceholderText("Search settings…")
        self._search.textChanged.connect(self._apply_search)
        left = QVBoxLayout(); left.addWidget(self._search); left.addWidget(self._nav, 1)

        center = QHBoxLayout(); center.addLayout(left); center.addWidget(scroll, 1)

        save_btn = QPushButton("Save"); save_btn.setObjectName("Send"); save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel"); cancel_btn.clicked.connect(self.reject)
        btn_row = QHBoxLayout(); btn_row.addStretch(1); btn_row.addWidget(cancel_btn); btn_row.addWidget(save_btn)

        root = QVBoxLayout(self)
        root.addLayout(center, 1)
        root.addLayout(btn_row)

        self._load_from_config()

    # ── section/row builders ───────────────────────────────────────────

    def _section(self, title: str) -> None:
        header = QLabel(title)
        header.setStyleSheet(f"color:{ACCENT}; font-weight:700; font-size:13px; margin-top:8px;")
        self._body_lay.addWidget(header)
        sep = QFrame(); sep.setFrameShape(QFrame.HLine); sep.setStyleSheet(f"color:{BORDER};")
        self._body_lay.addWidget(sep)
        self._sections[title] = header

    def _add_row(self, category: str, label: str, field: QWidget, keywords: str) -> None:
        row = QWidget()
        rl = QHBoxLayout(row); rl.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(label); lbl.setMinimumWidth(160)
        rl.addWidget(lbl); rl.addWidget(field, 1)
        self._body_lay.addWidget(row)
        self._rows.append((category, row, f"{label} {keywords}".lower()))

    def _add_labeled(self, category: str, label_widget: QLabel, field: QWidget, keywords: str) -> None:
        row = QWidget()
        rl = QHBoxLayout(row); rl.setContentsMargins(0, 0, 0, 0)
        label_widget.setMinimumWidth(160)
        rl.addWidget(label_widget); rl.addWidget(field, 1)
        self._body_lay.addWidget(row)
        self._rows.append((category, row, f"{label_widget.text()} {keywords}".lower()))

    def _add_full(self, category: str, widget: QWidget, keywords: str) -> None:
        self._body_lay.addWidget(widget)
        self._rows.append((category, widget, keywords.lower()))

    # ── nav / search ───────────────────────────────────────────────────

    def _scroll_to(self, category: str) -> None:
        header = self._sections.get(category)
        if header:
            self._scroll.ensureWidgetVisible(header, 0, 0)

    def _apply_search(self, text: str) -> None:
        q = text.strip().lower()
        visible_cats: set[str] = set()
        for category, widget, search_text in self._rows:
            show = (q == "" or q in search_text)
            widget.setVisible(show)
            if show:
                visible_cats.add(category)
        for category, header in self._sections.items():
            header.setVisible(q == "" or category in visible_cats)
            # the separator follows the header in the layout; toggle it too
            idx = self._body_lay.indexOf(header)
            if idx >= 0 and idx + 1 < self._body_lay.count():
                sep = self._body_lay.itemAt(idx + 1).widget()
                if isinstance(sep, QFrame):
                    sep.setVisible(header.isVisible())

    # ── preset/value wiring ────────────────────────────────────────────

    def _load_from_config(self) -> None:
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

    # ── danger zone ────────────────────────────────────────────────────

    def _confirm(self, title: str, text: str) -> bool:
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setIcon(QMessageBox.Warning)
        box.setText(text)
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
        box.setDefaultButton(QMessageBox.Cancel)
        return box.exec() == QMessageBox.Yes

    def _on_clear_history(self) -> None:
        if self._confirm("Clear chat history", "Delete all saved conversations? This cannot be undone."):
            self.clear_history.emit()

    def _on_clear_everything(self) -> None:
        if self._confirm("Clear everything",
                         "Delete all conversations, remembered facts, and the code index? "
                         "This cannot be undone."):
            self.clear_everything.emit()

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
        config.editor_font_size = self._editor_font.value()
        config.save_overrides()
        return changed
