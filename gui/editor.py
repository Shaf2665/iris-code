"""Editable code editor with tabs — the center pane of the IDE layout.

`EditorArea` is a tabbed container (one `CodeEditor` per open file) with a welcome
empty-state. `CodeEditor` is a `QPlainTextEdit` with a line-number gutter, current
line highlight, dirty tracking, Ctrl+S to save, and pygments-driven syntax
highlighting. Binary or very large files open read-only with a banner.

No new dependencies — pygments is already used by the chat/file-preview path.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QRect, QSize, QTimer, Signal
from PySide6.QtGui import (
    QColor, QFont, QPainter, QTextCharFormat, QTextFormat, QSyntaxHighlighter,
    QTextOption,
)
from PySide6.QtWidgets import (
    QPlainTextEdit, QWidget, QVBoxLayout, QTabWidget, QTextBrowser, QStackedLayout,
    QMessageBox, QTextEdit,
)

from .style import BG, BG_ELEV, BG_INPUT, BORDER, TEXT, TEXT_DIM, ACCENT
from .chat_view import welcome_html

_MAX_EDIT_BYTES = 2_000_000      # above this: open read-only, no highlighting
_MAX_HIGHLIGHT = 400_000         # above this: skip syntax highlighting (too slow)

try:
    import pygments
    from pygments.lexers import get_lexer_for_filename
    from pygments.lexers.special import TextLexer
    from pygments.token import Token
    _PYGMENTS = True
except Exception:  # pragma: no cover
    _PYGMENTS = False


# pygments token type → color (monokai-ish, matches the chat code theme).
if _PYGMENTS:
    _TOKEN_COLORS = {
        Token.Keyword: "#F92672",
        Token.Operator: "#F92672",
        Token.Name.Builtin: "#66D9EF",
        Token.Name.Builtin.Pseudo: "#66D9EF",
        Token.Name.Function: "#A6E22E",
        Token.Name.Class: "#A6E22E",
        Token.Name.Decorator: "#A6E22E",
        Token.Name.Namespace: "#A6E22E",
        Token.Name.Tag: "#F92672",
        Token.Name.Attribute: "#A6E22E",
        Token.String: "#E6DB74",
        Token.String.Doc: "#E6DB74",
        Token.Comment: "#75715E",
        Token.Number: "#AE81FF",
        Token.Literal: "#AE81FF",
        Token.Keyword.Constant: "#AE81FF",
    }


class _PygmentsHighlighter(QSyntaxHighlighter):
    """Highlights by tokenizing the whole document once per (debounced) change and
    applying the spans that overlap each block. Correct across multi-line strings/
    comments, and cheap enough under the size cap."""

    def __init__(self, document, path: str):
        super().__init__(document)
        self._spans: list[tuple[int, int, QTextCharFormat]] = []
        self._fmt_cache: dict[str, QTextCharFormat] = {}
        self._enabled = _PYGMENTS
        self._lexer = None
        if _PYGMENTS:
            try:
                self._lexer = get_lexer_for_filename(path, stripnl=False)
            except Exception:
                self._lexer = TextLexer()

    def _fmt(self, tok) -> QTextCharFormat | None:
        t = tok
        while t is not None:
            color = _TOKEN_COLORS.get(t)
            if color:
                fmt = self._fmt_cache.get(color)
                if fmt is None:
                    fmt = QTextCharFormat()
                    fmt.setForeground(QColor(color))
                    self._fmt_cache[color] = fmt
                return fmt
            t = t.parent
        return None

    def recompute(self) -> None:
        """Re-tokenize the document and repaint. Call (debounced) after edits."""
        if not self._enabled or self._lexer is None:
            return
        text = self.document().toPlainText()
        if len(text) > _MAX_HIGHLIGHT:
            self._spans = []
            return
        spans: list[tuple[int, int, QTextCharFormat]] = []
        pos = 0
        try:
            for tok, val in pygments.lex(text, self._lexer):
                ln = len(val)
                if ln and val.strip():
                    fmt = self._fmt(tok)
                    if fmt is not None:
                        spans.append((pos, pos + ln, fmt))
                pos += ln
        except Exception:
            spans = []
        self._spans = spans
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:  # noqa: N802 (Qt naming)
        if not self._spans:
            return
        start = self.currentBlock().position()
        end = start + len(text)
        for s, e, fmt in self._spans:
            if e <= start or s >= end:
                continue
            a = max(s, start)
            b = min(e, end)
            self.setFormat(a - start, b - a, fmt)


class _LineNumberArea(QWidget):
    def __init__(self, editor: "CodeEditor"):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self._editor.gutter_width(), 0)

    def paintEvent(self, event):  # noqa: N802
        self._editor.paint_gutter(event)


class CodeEditor(QPlainTextEdit):
    dirty_changed = Signal(bool)

    def __init__(self, path: str, parent=None, font_size: int = 11):
        super().__init__(parent)
        self._path = path
        self._dirty = False
        self.read_only_reason = ""
        self.setWordWrapMode(QTextOption.NoWrap)
        font = QFont("Cascadia Code")
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(font_size)
        self.setFont(font)
        self.setTabStopDistance(4 * self.fontMetrics().horizontalAdvance(" "))

        self._gutter = _LineNumberArea(self)
        self.blockCountChanged.connect(lambda _n: self._update_gutter_width())
        self.updateRequest.connect(self._on_update_request)
        self.cursorPositionChanged.connect(self._highlight_current_line)
        self._update_gutter_width()

        self._highlighter: _PygmentsHighlighter | None = None
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(250)
        self._debounce.timeout.connect(self._rehighlight)

        self._load(path)
        self.textChanged.connect(self._on_text_changed)
        self._highlight_current_line()

    # ── file IO ─────────────────────────────────────────────────────────

    def _load(self, path: str) -> None:
        try:
            size = os.path.getsize(path)
            with open(path, "rb") as fh:
                raw = fh.read(_MAX_EDIT_BYTES + 1)
        except Exception as e:  # noqa: BLE001
            self.setPlainText(f"(could not read file: {e})")
            self.setReadOnly(True)
            self.read_only_reason = str(e)
            return
        if b"\x00" in raw[:8192]:
            self.setPlainText("(binary file — not shown)")
            self.setReadOnly(True)
            self.read_only_reason = "binary file"
            return
        if size > _MAX_EDIT_BYTES:
            self.setPlainText(raw.decode("utf-8", "replace"))
            self.setReadOnly(True)
            self.read_only_reason = "file too large to edit"
            return
        self.setPlainText(raw.decode("utf-8", "replace"))
        if _PYGMENTS:
            self._highlighter = _PygmentsHighlighter(self.document(), path)
            self._highlighter.recompute()

    def save(self) -> tuple[bool, str]:
        if self.isReadOnly():
            return False, self.read_only_reason or "read-only"
        try:
            with open(self._path, "w", encoding="utf-8", newline="") as fh:
                fh.write(self.toPlainText())
        except Exception as e:  # noqa: BLE001
            return False, str(e)
        self._set_dirty(False)
        return True, self._path

    @property
    def path(self) -> str:
        return self._path

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    def _set_dirty(self, dirty: bool) -> None:
        if dirty != self._dirty:
            self._dirty = dirty
            self.dirty_changed.emit(dirty)

    def _on_text_changed(self) -> None:
        if not self.isReadOnly():
            self._set_dirty(True)
        self._debounce.start()

    def _rehighlight(self) -> None:
        if self._highlighter is not None:
            self._highlighter.recompute()

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key_S and (event.modifiers() & Qt.ControlModifier):
            self.save()
            return
        super().keyPressEvent(event)

    # ── gutter (line numbers) ───────────────────────────────────────────

    def gutter_width(self) -> int:
        digits = max(2, len(str(max(1, self.blockCount()))))
        return 12 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_gutter_width(self) -> None:
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def _on_update_request(self, rect: QRect, dy: int) -> None:
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_gutter_width()

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._gutter.setGeometry(QRect(cr.left(), cr.top(), self.gutter_width(), cr.height()))

    def paint_gutter(self, event) -> None:
        painter = QPainter(self._gutter)
        painter.fillRect(event.rect(), QColor(BG_ELEV))
        block = self.firstVisibleBlock()
        num = block.blockNumber()
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        bottom = top + self.blockBoundingRect(block).height()
        painter.setPen(QColor(TEXT_DIM))
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.drawText(0, int(top), self._gutter.width() - 6,
                                 self.fontMetrics().height(), Qt.AlignRight, str(num + 1))
            block = block.next()
            top = bottom
            bottom = top + self.blockBoundingRect(block).height()
            num += 1

    def _highlight_current_line(self) -> None:
        sel = QTextEdit.ExtraSelection()
        sel.format.setBackground(QColor(BG_INPUT))
        sel.format.setProperty(QTextFormat.FullWidthSelection, True)
        sel.cursor = self.textCursor()
        sel.cursor.clearSelection()
        self.setExtraSelections([sel])


class EditorArea(QWidget):
    """Tabbed editors with a welcome empty-state when nothing is open."""

    dirty_changed = Signal()  # any tab's dirty state changed

    def __init__(self, parent=None, font_size: int = 11):
        super().__init__(parent)
        self._editors: dict[str, CodeEditor] = {}
        self._font_size = font_size

        self._welcome = QTextBrowser()
        self._welcome.setOpenExternalLinks(True)
        self._welcome.setHtml(welcome_html())

        self._tabs = QTabWidget()
        self._tabs.setTabsClosable(True)
        self._tabs.setMovable(True)
        self._tabs.setDocumentMode(True)
        self._tabs.tabCloseRequested.connect(self._close_tab)

        self._stack = QStackedLayout(self)
        self._stack.setContentsMargins(0, 0, 0, 0)
        self._stack.addWidget(self._welcome)
        self._stack.addWidget(self._tabs)
        self._show_welcome()

    def _show_welcome(self) -> None:
        self._stack.setCurrentWidget(self._welcome if self._tabs.count() == 0 else self._tabs)

    def open_file(self, path: str) -> None:
        norm = os.path.normcase(os.path.abspath(path))
        if norm in self._editors:
            self._tabs.setCurrentWidget(self._editors[norm])
            self._show_welcome()
            return
        editor = CodeEditor(path, font_size=self._font_size)
        editor.dirty_changed.connect(lambda _d, p=norm: self._on_dirty(p))
        self._editors[norm] = editor
        idx = self._tabs.addTab(editor, os.path.basename(path))
        self._tabs.setTabToolTip(idx, path)
        if editor.isReadOnly() and editor.read_only_reason:
            self._tabs.setTabText(idx, os.path.basename(path) + "  (read-only)")
        self._tabs.setCurrentIndex(idx)
        self._show_welcome()

    def _index_of(self, path: str) -> int:
        editor = self._editors.get(path)
        return self._tabs.indexOf(editor) if editor else -1

    def _on_dirty(self, norm: str) -> None:
        editor = self._editors.get(norm)
        idx = self._index_of(norm)
        if editor and idx >= 0:
            base = os.path.basename(editor.path)
            self._tabs.setTabText(idx, ("● " + base) if editor.is_dirty else base)
        self.dirty_changed.emit()

    def save_current(self) -> None:
        w = self._tabs.currentWidget()
        if isinstance(w, CodeEditor):
            w.save()

    def _close_tab(self, index: int) -> None:
        editor = self._tabs.widget(index)
        if isinstance(editor, CodeEditor):
            if editor.is_dirty and not self._confirm_discard(editor):
                return
            self._editors.pop(os.path.normcase(os.path.abspath(editor.path)), None)
        self._tabs.removeTab(index)
        self._show_welcome()

    def _confirm_discard(self, editor: CodeEditor) -> bool:
        box = QMessageBox(self)
        box.setWindowTitle("Unsaved changes")
        box.setIcon(QMessageBox.Warning)
        box.setText(f"Save changes to {os.path.basename(editor.path)} before closing?")
        box.setStandardButtons(QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        box.setDefaultButton(QMessageBox.Save)
        choice = box.exec()
        if choice == QMessageBox.Save:
            return editor.save()[0]
        return choice == QMessageBox.Discard

    def has_unsaved(self) -> bool:
        return any(e.is_dirty for e in self._editors.values())
