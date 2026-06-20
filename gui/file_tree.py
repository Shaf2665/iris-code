"""
File explorer pane (VS Code-style) + a read-only file preview.

A QTreeView over a QFileSystemModel rooted at the active project, with a filter
proxy that hides noise directories (.git, node_modules, .venv, …). Double-click a
file to preview it (syntax-highlighted, read-only); from there you can hand it to
Forge, which inserts a prompt referencing the file into the composer.
"""
from __future__ import annotations

import os

from PySide6.QtCore import (
    Signal, QDir, QSortFilterProxyModel, QModelIndex, QFileInfo, Qt, QRectF, QUrl,
)
from PySide6.QtGui import (
    QIcon, QPixmap, QPainter, QColor, QFont, QPainterPath, QDesktopServices,
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTreeView, QDialog, QTextBrowser,
    QPushButton, QFileSystemModel, QFileIconProvider, QApplication, QMenu,
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


# Per-language colors (GitHub-linguist-ish), keyed by extension without the dot.
# Several extensions can share a swatch; the badge text is the extension itself.
_EXT_COLOR = {
    "py": "#3572A5", "pyw": "#3572A5", "ipynb": "#da5b0b",
    "js": "#f1e05a", "mjs": "#f1e05a", "cjs": "#f1e05a",
    "ts": "#3178c6", "tsx": "#3178c6", "jsx": "#61dafb",
    "json": "#cbcb41", "json5": "#cbcb41",
    "yml": "#d4a72c", "yaml": "#d4a72c", "toml": "#9c6b30",
    "md": "#519aba", "markdown": "#519aba", "rst": "#519aba", "txt": "#8b93a3",
    "html": "#e34c26", "htm": "#e34c26", "xml": "#0060ac", "svg": "#ff9a00",
    "css": "#2965f1", "scss": "#c6538c", "sass": "#c6538c", "less": "#1d365d",
    "sh": "#89e051", "bash": "#89e051", "zsh": "#89e051", "ps1": "#012456",
    "rs": "#dea584", "go": "#00ADD8", "rb": "#701516", "php": "#4F5D95",
    "java": "#b07219", "kt": "#A97BFF", "swift": "#F05138", "c": "#555555",
    "h": "#555555", "hpp": "#555555", "cpp": "#f34b7d", "cc": "#f34b7d",
    "cs": "#178600", "sql": "#e38c00", "vue": "#41b883", "lua": "#000080",
    "dart": "#00B4AB", "r": "#198CE7", "scala": "#c22d40", "pl": "#0298c3",
    "ini": "#6e6e6e", "cfg": "#6e6e6e", "conf": "#6e6e6e", "env": "#6e6e6e",
    "lock": "#6e6e6e", "gitignore": "#6e6e6e", "dockerfile": "#384d54",
}
_DEFAULT_COLOR = "#8b93a3"


def _badge_text(info: QFileInfo) -> str:
    """Short uppercase label for a file's badge (extension, or special names)."""
    name = info.fileName().lower()
    if name in ("dockerfile",):
        return "DK"
    suffix = info.suffix().lower()
    if not suffix:                       # e.g. ".gitignore", "LICENSE", "Makefile"
        if name.startswith("."):
            return name[1:3].upper() or "•"
        return name[:2].upper() or "•"
    return suffix[:3].upper()


def _color_for(info: QFileInfo) -> str:
    name = info.fileName().lower()
    if name == "dockerfile":
        return _EXT_COLOR["dockerfile"]
    key = info.suffix().lower() or name.lstrip(".")
    return _EXT_COLOR.get(key, _DEFAULT_COLOR)


def _text_on(color: QColor) -> QColor:
    """Pick black/white text for contrast against a badge color."""
    lum = 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
    return QColor("#1a1a1a") if lum > 150 else QColor("#ffffff")


class _IconProvider(QFileIconProvider):
    """Paints VS Code-style colored badges per file type (and a folder glyph),
    instead of relying on OS shell icons — which come back blank in a frozen
    PyInstaller app. Icons are cached by type key so painting happens once."""

    _SIZE = 16

    def __init__(self) -> None:
        super().__init__()
        self._cache: dict[str, QIcon] = {}

    def icon(self, arg):  # noqa: N802 (Qt naming) — overloaded: QFileInfo | IconType
        if isinstance(arg, QFileInfo):
            if arg.isDir():
                return self._dir_icon()
            return self._file_icon(arg)
        return super().icon(arg)

    def _dir_icon(self) -> QIcon:
        if "<dir>" not in self._cache:
            self._cache["<dir>"] = self._paint_folder()
        return self._cache["<dir>"]

    def _file_icon(self, info: QFileInfo) -> QIcon:
        key = info.fileName().lower() if not info.suffix() else info.suffix().lower()
        if key not in self._cache:
            self._cache[key] = self._paint_badge(_badge_text(info), QColor(_color_for(info)))
        return self._cache[key]

    def _new_pixmap(self) -> QPixmap:
        pm = QPixmap(self._SIZE, self._SIZE)
        pm.fill(Qt.transparent)
        return pm

    def _paint_badge(self, text: str, color: QColor) -> QIcon:
        pm = self._new_pixmap()
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(1, 2, self._SIZE - 2, self._SIZE - 4)
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(rect, 3, 3)
        font = QFont()
        font.setPixelSize(7 if len(text) >= 3 else 8)
        font.setBold(True)
        p.setFont(font)
        p.setPen(_text_on(color))
        p.drawText(rect, Qt.AlignCenter, text)
        p.end()
        return QIcon(pm)

    def _paint_folder(self) -> QIcon:
        pm = self._new_pixmap()
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(ACCENT))
        path = QPainterPath()
        path.moveTo(2, 5)
        path.lineTo(6, 5)
        path.lineTo(7.5, 6.5)
        path.lineTo(14, 6.5)
        path.lineTo(14, 13)
        path.lineTo(2, 13)
        path.closeSubpath()
        p.drawPath(path)
        p.end()
        return QIcon(pm)


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
    file_activated = Signal(str)  # absolute path of an opened file
    index_folder = Signal(str)    # absolute path of a folder to (re)index

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(180)
        self._root_path = ""

        self._fs = QFileSystemModel(self)
        self._icon_provider = _IconProvider()
        self._fs.setIconProvider(self._icon_provider)
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
        # VS Code opens files on a single click; folders expand on click too.
        self._tree.clicked.connect(self._on_clicked)
        self._tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addLayout(self._build_header())
        lay.addWidget(self._tree, 1)

    # ── header ─────────────────────────────────────────────────────────

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(6, 4, 4, 2)
        row.setSpacing(2)

        title = QLabel("EXPLORER")
        title.setStyleSheet(f"color:{TEXT_DIM}; font-size:11px; font-weight:700;")
        self._project_label = QLabel("")
        self._project_label.setStyleSheet(f"color:{ACCENT}; font-size:11px; font-weight:700;")

        refresh = QPushButton("⟳")
        refresh.setObjectName("TreeAction")
        refresh.setToolTip("Refresh")
        refresh.setFixedSize(22, 22)
        refresh.clicked.connect(self._refresh)
        collapse = QPushButton("⌄")
        collapse.setObjectName("TreeAction")
        collapse.setToolTip("Collapse all")
        collapse.setFixedSize(22, 22)
        collapse.clicked.connect(self._tree.collapseAll)

        row.addWidget(title)
        row.addSpacing(6)
        row.addWidget(self._project_label, 1)
        row.addWidget(refresh)
        row.addWidget(collapse)
        return row

    # ── model wiring ───────────────────────────────────────────────────

    def set_root(self, path: str) -> None:
        if not path or not os.path.isdir(path):
            return
        self._root_path = path
        self._project_label.setText(os.path.basename(path.rstrip("/\\")).upper())
        src = self._fs.setRootPath(path)
        self._tree.setRootIndex(self._proxy.mapFromSource(src))

    def _refresh(self) -> None:
        if self._root_path:
            self._fs.setRootPath("")          # force the model to re-read
            self.set_root(self._root_path)

    def _path_at(self, proxy_idx: QModelIndex) -> tuple[str, bool]:
        src = self._proxy.mapToSource(proxy_idx)
        return self._fs.filePath(src), self._fs.isDir(src)

    def _on_clicked(self, proxy_idx: QModelIndex) -> None:
        path, is_dir = self._path_at(proxy_idx)
        if is_dir:
            self._tree.setExpanded(proxy_idx, not self._tree.isExpanded(proxy_idx))
            return
        self.file_activated.emit(path)

    # ── context menu ───────────────────────────────────────────────────

    def _on_context_menu(self, pos) -> None:
        proxy_idx = self._tree.indexAt(pos)
        if not proxy_idx.isValid():
            return
        path, is_dir = self._path_at(proxy_idx)
        menu = QMenu(self)
        if is_dir:
            menu.addAction("Re-index project", lambda: self.index_folder.emit(self._root_path))
        else:
            menu.addAction("Open / Preview", lambda: self.file_activated.emit(path))
            menu.addAction("Send to Forge", lambda: self.file_activated.emit(path))
        menu.addSeparator()
        menu.addAction("Reveal in file manager", lambda: self._reveal(path, is_dir))
        menu.addAction("Copy path", lambda: QApplication.clipboard().setText(path))
        menu.addAction("Copy relative path", lambda: self._copy_rel(path))
        menu.exec(self._tree.viewport().mapToGlobal(pos))

    def _reveal(self, path: str, is_dir: bool) -> None:
        target = path if is_dir else os.path.dirname(path)
        QDesktopServices.openUrl(QUrl.fromLocalFile(target))

    def _copy_rel(self, path: str) -> None:
        rel = os.path.relpath(path, self._root_path) if self._root_path else path
        QApplication.clipboard().setText(rel)


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
