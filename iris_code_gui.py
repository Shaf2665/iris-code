"""Frozen-app entry point (used by PyInstaller) and a convenient local launcher.

    python iris_code_gui.py              # run the desktop GUI
    python iris_code_gui.py --selftest   # build the window headless, exit 0

The --selftest path renders the main window under the offscreen Qt platform and
quits immediately. It needs no router and no display, so CI can use it to prove
the packaged binary actually starts.

Kept at the repo root as a single, import-light script so PyInstaller has an
obvious target.
"""
import os
import sys


def _selftest() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer
    from forge.config import Config
    from gui.style import STYLESHEET
    from gui.app import MainWindow

    app = QApplication(sys.argv)
    app.setStyleSheet(STYLESHEET)
    win = MainWindow(Config.load())
    win.show()
    QTimer.singleShot(300, app.quit)
    app.exec()
    win.close()
    print("selftest OK — window built and rendered")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return _selftest()
    from gui.app import main as gui_main
    return gui_main()


if __name__ == "__main__":
    raise SystemExit(main())
