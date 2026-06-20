"""Qt stylesheet — a dark "forge" theme (ember accent on charcoal/steel)."""

ACCENT = "#ff8a4c"      # ember orange
ACCENT_DIM = "#b5532a"
CYAN = "#4fc3f7"
BG = "#15171c"          # charcoal
BG_ELEV = "#1d2026"     # elevated panels
BG_INPUT = "#22262e"
BORDER = "#2c313a"
TEXT = "#e6e9ef"
TEXT_DIM = "#8b93a3"
OK = "#4caf72"
ERR = "#e0524c"

STYLESHEET = f"""
QWidget {{
    background-color: {BG};
    color: {TEXT};
    /* Cross-OS system font stack: Windows / macOS / Linux, with fallbacks. */
    font-family: "Segoe UI", "SF Pro Text", "Helvetica Neue", "Ubuntu",
                 "Noto Sans", "Cantarell", sans-serif;
    font-size: 14px;
}}
QFrame#TopBar {{
    background-color: {BG_ELEV};
    border-bottom: 1px solid {BORDER};
}}
QLabel#ProjectLabel {{ color: {TEXT_DIM}; }}
QLabel#ProjectValue {{ color: {CYAN}; font-weight: 600; }}
QLabel#StatusDot {{ font-size: 13px; }}

QTextBrowser {{
    background-color: {BG};
    border: none;
    padding: 4px 10px;
    selection-background-color: {ACCENT_DIM};
}}

QPlainTextEdit#Composer {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 9px 12px;
    color: {TEXT};
}}
QPlainTextEdit#Composer:focus {{ border: 1px solid {ACCENT}; }}

QPushButton {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 7px 14px;
    color: {TEXT};
}}
QPushButton:hover {{ border: 1px solid {ACCENT}; }}
QPushButton:disabled {{ color: {TEXT_DIM}; border-color: {BORDER}; }}
QPushButton#Send {{
    background-color: {ACCENT};
    color: #1a1004;
    font-weight: 700;
    border: none;
}}
QPushButton#Send:hover {{ background-color: #ffa066; }}
QPushButton#Send:disabled {{ background-color: {BG_INPUT}; color: {TEXT_DIM}; }}

QComboBox {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 5px 10px;
}}
QComboBox:hover {{ border: 1px solid {ACCENT}; }}
QComboBox QAbstractItemView {{
    background-color: {BG_ELEV};
    selection-background-color: {ACCENT_DIM};
    border: 1px solid {BORDER};
}}

QLineEdit {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 7px 10px;
}}
QLineEdit:focus {{ border: 1px solid {ACCENT}; }}

QTreeView {{
    background-color: {BG_ELEV};
    border: none;
    outline: 0;
    show-decoration-selected: 1;
}}
QTreeView::item {{
    height: 22px;
    padding: 1px 2px;
    border: none;
    color: {TEXT};
}}
QTreeView::item:hover {{ background: {BG_INPUT}; }}
QTreeView::item:selected {{ background: {ACCENT_DIM}; color: {TEXT}; }}
QTreeView::branch {{ background: transparent; }}
QPushButton#TreeAction {{
    background: transparent;
    border: none;
    border-radius: 5px;
    color: {TEXT_DIM};
    padding: 0;
    font-size: 14px;
}}
QPushButton#TreeAction:hover {{ background: {BG_INPUT}; color: {ACCENT}; }}

QScrollBar:vertical {{ background: {BG}; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {ACCENT_DIM}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}

QDialog {{ background-color: {BG_ELEV}; }}
QLabel.dim {{ color: {TEXT_DIM}; }}

/* ── Activity bar (left edge, VS Code-style) ── */
QToolBar#ActivityBar {{
    background-color: #101216;
    border: none;
    border-right: 1px solid {BORDER};
    padding: 6px 0;
    spacing: 4px;
}}
QToolBar#ActivityBar QToolButton {{
    background: transparent;
    border: none;
    border-left: 2px solid transparent;
    color: {TEXT_DIM};
    padding: 10px 6px;
    font-size: 11px;
    min-width: 52px;
}}
QToolBar#ActivityBar QToolButton:hover {{ color: {TEXT}; }}
QToolBar#ActivityBar QToolButton:checked {{
    color: {ACCENT};
    border-left: 2px solid {ACCENT};
}}

/* ── Dock widgets ── */
QDockWidget {{
    color: {TEXT_DIM};
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
}}
QDockWidget::title {{
    background-color: {BG_ELEV};
    padding: 5px 8px;
    border-bottom: 1px solid {BORDER};
    font-size: 11px;
    text-transform: uppercase;
}}

/* ── Editor tabs ── */
QTabWidget::pane {{ border: none; background: {BG}; }}
QTabBar {{ background: {BG_ELEV}; }}
QTabBar::tab {{
    background: {BG_ELEV};
    color: {TEXT_DIM};
    padding: 6px 14px;
    border: none;
    border-right: 1px solid {BORDER};
}}
QTabBar::tab:selected {{
    background: {BG};
    color: {TEXT};
    border-top: 2px solid {ACCENT};
}}
QTabBar::tab:hover {{ color: {TEXT}; }}

/* ── Editor + terminal ── */
QPlainTextEdit#TerminalOut {{
    background-color: #0e1013;
    border: none;
    padding: 4px 8px;
    color: {TEXT};
}}
"""

# CSS injected into the QTextBrowser HTML document (chat transcript).
CHAT_CSS = f"""
<style>
  body {{ color: {TEXT}; font-size: 14px; line-height: 1.5; }}
  .turn {{ margin: 2px 0 14px 0; }}
  .role-you {{ color: {CYAN}; font-weight: 700; margin-bottom: 2px; }}
  .role-forge {{ color: {ACCENT}; font-weight: 700; margin-bottom: 2px; }}
  .bubble {{ }}
  .tool {{ color: {TEXT_DIM}; font-family: monospace; font-size: 12px;
           margin: 3px 0; }}
  .thinking {{ color: {ACCENT}; font-style: italic; margin: 4px 0; }}
  .thinking .dots {{ letter-spacing: 2px; font-size: 11px; }}
  pre {{ background: {BG_ELEV}; border: 1px solid {BORDER}; border-radius: 8px;
         padding: 9px 11px; white-space: pre-wrap; }}
  code {{ background: {BG_ELEV}; padding: 1px 4px; border-radius: 4px;
          font-family: "Cascadia Code", "Consolas", monospace; font-size: 13px; }}
  pre code {{ background: transparent; padding: 0; }}
  a {{ color: {ACCENT}; }}
  table {{ border-collapse: collapse; }}
  th, td {{ border: 1px solid {BORDER}; padding: 4px 8px; }}
  blockquote {{ border-left: 3px solid {ACCENT_DIM}; margin: 4px 0;
                padding-left: 10px; color: {TEXT_DIM}; }}
</style>
"""
