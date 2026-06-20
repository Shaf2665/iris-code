"""Chat transcript rendering.

The transcript is a list of completed turns plus an optional in-progress
assistant turn. On every update we rebuild a single HTML document and hand it to
the QTextBrowser. Markdown (with fenced code + syntax highlighting) is rendered
via the `markdown` library; if it's unavailable we fall back to escaped text so
the app still works. Scroll is pinned to the bottom while streaming.
"""
from __future__ import annotations

import html

from PySide6.QtWidgets import QTextBrowser

from .style import CHAT_CSS

try:
    import markdown as _md

    def _render_md(text: str) -> str:
        return _md.markdown(
            text,
            extensions=["fenced_code", "tables", "nl2br", "codehilite"],
            extension_configs={"codehilite": {"noclasses": True, "pygments_style": "monokai"}},
        )
except Exception:  # pragma: no cover - markdown/pygments missing
    def _render_md(text: str) -> str:
        return "<p>" + html.escape(text).replace("\n", "<br>") + "</p>"


class ChatView(QTextBrowser):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setOpenExternalLinks(True)
        self._turns: list[dict] = []          # {role, text, tools:[...]}
        self._streaming: dict | None = None    # {text, tools:[...]}

    # ── transcript mutation ────────────────────────────────────────────

    def reset(self, history: list[dict] | None = None) -> None:
        """Rebuild the view from a persisted history list (user/assistant only)."""
        self._turns = []
        self._streaming = None
        for m in history or []:
            role = m.get("role")
            content = m.get("content")
            if role == "user" and content:
                self._turns.append({"role": "you", "text": content, "tools": []})
            elif role == "assistant" and content:
                self._turns.append({"role": "forge", "text": content, "tools": []})
        self._render()

    def add_user(self, text: str) -> None:
        self._turns.append({"role": "you", "text": text, "tools": []})
        self._render()

    def begin_assistant(self) -> None:
        self._streaming = {"text": "", "tools": []}
        self._render()

    def append_token(self, chunk: str) -> None:
        if self._streaming is None:
            self.begin_assistant()
        self._streaming["text"] += chunk
        self._render()

    def add_tool_status(self, line: str) -> None:
        if self._streaming is None:
            self.begin_assistant()
        # Strip rich-markup tags like [dim]...[/dim] that come from the agent.
        clean = line.replace("[dim]", "").replace("[/dim]", "").strip()
        if clean:
            self._streaming["tools"].append(clean)
            self._render()

    def end_assistant(self) -> None:
        if self._streaming is not None:
            self._turns.append({
                "role": "forge",
                "text": self._streaming["text"],
                "tools": self._streaming["tools"],
            })
            self._streaming = None
            self._render()

    def add_system_note(self, text: str) -> None:
        self._turns.append({"role": "note", "text": text, "tools": []})
        self._render()

    # ── rendering ──────────────────────────────────────────────────────

    def _turn_html(self, role: str, text: str, tools: list[str]) -> str:
        parts = []
        if role == "you":
            parts.append('<div class="role-you">You</div>')
            parts.append('<div class="bubble">' + _render_md(text) + "</div>")
        elif role == "forge":
            parts.append('<div class="role-forge">Forge</div>')
            for t in tools:
                parts.append('<div class="tool">' + html.escape(t) + "</div>")
            if text.strip():
                parts.append('<div class="bubble">' + _render_md(text) + "</div>")
        else:  # system note
            parts.append('<div class="tool">' + html.escape(text) + "</div>")
        return '<div class="turn">' + "".join(parts) + "</div>"

    def _render(self) -> None:
        body = [CHAT_CSS]
        for t in self._turns:
            body.append(self._turn_html(t["role"], t["text"], t["tools"]))
        if self._streaming is not None:
            body.append(self._turn_html("forge", self._streaming["text"], self._streaming["tools"]))
        self.setHtml("".join(body))
        sb = self.verticalScrollBar()
        sb.setValue(sb.maximum())
