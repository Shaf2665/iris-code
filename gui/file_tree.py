"""
File explorer pane (VS Code-style) + a read-only file preview.

A QTreeView over a QFileSystemModel rooted at the active project, with a filter
proxy that hides noise directories (.git, node_modules, .venv, …). Double-click a
file to preview it (syntax-highlighted, read-only); from there you can hand it to
Forge, which inserts a prompt referencing the file into the composer.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Signal, QDir, QSortFilterProxyModel, QModelIndex
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTreeView, QDialog, QTextBrowser,
    QPushButton, QFileSystemModel,
)

from forge.memory.project_index import _SKIP_DIRS
from .style import ACCENT, TEXT_DIM, BG_ELEV, BORDER

try:
    from pygments import highlight as _pyg_highlight
    from pygments.lexers import get_lexer_for_filename
    from pygments.lexers.special import TextLexer
    from pygments.formatters import HtmlFormatter

    def _highlight(path: str, text: str) -> str:
        try:
            lexer = get_lexer_for_filename(path, text)
        except Exception:
            lexer = TextLexer()
        return _pyg_highlight(text, lexer, HtmlFormatter(noclasses=True, style="monokai"))
except Exception:  # pragma: no cover
    import html as _html

    def _highlight(path: str, text: str) -> str:
        return "<pre>" + _html.escape(text) + "</pre>"


class _SkipDirProxy(QSortFilterProxyModel):
    """Hides directories whose name is in the project-index skip set."""

    def filterAcceptsRow(self, row: int, parent: QModelIndex) -> bool:  # noqa: N802
        model = self.sourceModel()
        idx = model.index(row, 0, parent)
        if not idx.isValid():
            return False
        if model.isDir(idx) and model.fileName(idx) in _SKIP_DIRS:
            return False
        return True


class FileTree(QWidget):
    file_activated = Signal(str)  # absolute path of a double-clicked file

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(180)

        self._fs = QFileSystemModel(self)
        self._fs.setFilter(QDir.AllEntries | QDir.NoDotAndDotDot | QDir.Hidden)
        self._proxy = _SkipDirProxy(self)
        self._proxy.setSourceModel(self._fs)

        self._tree = QTreeView()
        self._tree.setModel(self._proxy)
        self._tree.setHeaderHidden(True)
        self._tree.setAnimated(True)
        self._tree.setIndentation(14)
        for col in (1, 2, 3):           # hide size/type/date columns
            self._tree.hideColumn(col)
        self._tree.doubleClicked.connect(self._on_double_click)

        header = QLabel("EXPLORER")
        header.setStyleSheet(f"color:{TEXT_DIM}; font-size:11px; font-weight:700; padding:4px 6px;")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(header)
        lay.addWidget(self._tree, 1)

    def set_root(self, path: str) -> None:
        if not path or not os.path.isdir(path):
            return
        src = self._fs.setRootPath(path)
        self._tree.setRootIndex(self._proxy.mapFromSource(src))

    def _on_double_click(self, proxy_idx: QModelIndex) -> None:
        src = self._proxy.mapToSource(proxy_idx)
        if self._fs.isDir(src):
            return
        self.file_activated.emit(self._fs.filePath(src))


_MAX_PREVIEW = 400_000


class FilePreviewDialog(QDialog):
    """Read-only, syntax-highlighted preview with a 'Send to Forge' action."""
    send_to_forge = Signal(str)  # path the user wants Forge to look at

    def __init__(self, path: str, project_dir: str = "", parent=None):
        super().__init__(parent)
        self._path = path
        rel = os.path.relpath(path, project_dir) if project_dir else path
        self.setWindowTitle(f"Iris Code — {rel}")
        self.setMinimumSize(760, 600)

        view = QTextBrowser()
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read(_MAX_PREVIEW)
        except Exception as e:  # noqa: BLE001
            text = f"(could not read file: {e})"
        view.setHtml(
            f'<div style="font-family:\'Cascadia Code\',\'Consolas\',monospace; font-size:12px; '
            f'background:{BG_ELEV};">{_highlight(path, text)}</div>'
        )

        title = QLabel(f"<b style='color:{ACCENT}'>{rel}</b>")
        send_btn = QPushButton("Send to Forge")
        send_btn.setObjectName("Send")
        send_btn.clicked.connect(self._on_send)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)

        top = QHBoxLayout()
        top.addWidget(title)
        top.addStretch(1)
        top.addWidget(send_btn)
        top.addWidget(close_btn)

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(view, 1)

    def _on_send(self) -> None:
        self.send_to_forge.emit(self._path)
        self.accept()
