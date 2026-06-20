"""Chat transcript rendering.

The transcript is a list of completed turns plus an optional in-progress
assistant turn. On every update we rebuild a single HTML document and hand it to
the QTextBrowser. Markdown (with fenced code + syntax highlighting) is rendered
via the `markdown` library; if it's unavailable we fall back to escaped text so
the app still works. Scroll is pinned to the bottom while streaming.
"""
from __future__ import annotations

import html

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QTextBrowser

from .style import CHAT_CSS, ACCENT, TEXT_DIM, CYAN

_EMPTY_HTML = f"""
<div style="text-align:center; margin-top:120px; color:{TEXT_DIM};">
  <div style="font-size:34px; color:{ACCENT}; font-weight:800;">&#10022; Iris Code</div>
  <div style="font-size:15px; margin-top:10px;">Your personal coding agent, powered by hermes-router.</div>
  <div style="font-size:13px; margin-top:22px; line-height:1.8;">
    1. Open a project with <b style="color:{CYAN};">Open&hellip;</b> &nbsp;&middot;&nbsp;
       2. <b style="color:{CYAN};">Index</b> it for code search &nbsp;&middot;&nbsp;
       3. Ask Forge anything<br>
    <span style="color:{TEXT_DIM};">e.g. &ldquo;run the tests and fix what fails&rdquo; &nbsp;or&nbsp; &ldquo;where is auth handled?&rdquo;</span>
  </div>
</div>
"""

def welcome_html() -> str:
    """The branded empty-state, shared by the chat view and the editor area."""
    return CHAT_CSS + _EMPTY_HTML


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


_ACTIONS = {
    "search_codebase": "Searching the codebase",
    "read_file": "Reading a file",
    "write_file": "Writing a file",
    "run_command": "Running a command",
    "run_tests": "Running tests",
    "git_status": "Checking git status",
    "git_diff": "Reading the git diff",
    "git_log": "Reading git history",
    "git_blame_line": "Running git blame",
    "fetch_url": "Fetching a web page",
}


def _friendly_action(tool_line: str) -> str:
    """'> run_command(command=...)' -> 'Running a command'."""
    name = tool_line.lstrip("> ").split("(", 1)[0].strip()
    return _ACTIONS.get(name, "Working")


class ChatView(QTextBrowser):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setOpenExternalLinks(True)
        self._turns: list[dict] = []          # {role, text, tools:[...]}
        self._streaming: dict | None = None    # {text, tools:[...]}
        # Animated "thinking" indicator shown while waiting for the first token
        # or while a tool runs (Claude-Code style).
        self._thinking = ""
        self._think_phase = 0
        self._think_timer = QTimer(self)
        self._think_timer.setInterval(350)
        self._think_timer.timeout.connect(self._tick)

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
        self._thinking = "Forge is thinking"
        self._think_phase = 0
        self._think_timer.start()
        self._render()

    def append_token(self, chunk: str) -> None:
        if self._streaming is None:
            self.begin_assistant()
        if chunk.strip() and self._thinking:
            self._thinking = ""           # real output arrived — drop the indicator
            self._think_timer.stop()
        self._streaming["text"] += chunk
        self._render()

    def add_tool_status(self, line: str) -> None:
        if self._streaming is None:
            self.begin_assistant()
        # Strip rich-markup tags like [dim]...[/dim] that come from the agent.
        clean = line.replace("[dim]", "").replace("[/dim]", "").strip()
        if clean:
            self._streaming["tools"].append(clean)
            # While a tool runs, show what it's doing as the live indicator.
            self._thinking = _friendly_action(clean)
            self._think_phase = 0
            if not self._think_timer.isActive():
                self._think_timer.start()
            self._render()

    def end_assistant(self) -> None:
        self._think_timer.stop()
        self._thinking = ""
        if self._streaming is not None:
            self._turns.append({
                "role": "forge",
                "text": self._streaming["text"],
                "tools": self._streaming["tools"],
            })
            self._streaming = None
            self._render()

    def _tick(self) -> None:
        self._think_phase += 1
        if self._streaming is not None and self._thinking:
            self._render()
        else:
            self._think_timer.stop()

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
        if not self._turns and self._streaming is None:
            self.setHtml(CHAT_CSS + _EMPTY_HTML)
            return
        body = [CHAT_CSS]
        for t in self._turns:
            body.append(self._turn_html(t["role"], t["text"], t["tools"]))
        if self._streaming is not None:
            parts = ['<div class="role-forge">Forge</div>']
            for t in self._streaming["tools"]:
                parts.append('<div class="tool">' + html.escape(t) + "</div>")
            text = self._streaming["text"]
            if text.strip():
                parts.append('<div class="bubble">' + _render_md(text) + "</div>")
            elif self._thinking:
                dots = "●" * (self._think_phase % 4) + "○" * (3 - self._think_phase % 4)
                parts.append(
                    f'<div class="thinking">{html.escape(self._thinking)} '
                    f'<span class="dots">{dots}</span></div>'
                )
            body.append('<div class="turn">' + "".join(parts) + "</div>")
        self.setHtml("".join(body))
        sb = self.verticalScrollBar()
        sb.setValue(sb.maximum())
