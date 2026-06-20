"""Background workers so the Qt event loop never blocks on the network.

ChatWorker runs one agent.chat() turn in its own thread, emitting a signal per
streamed token and per tool-status line. IndexWorker runs a project index pass
the same way. The main window connects to these signals to update the UI.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal

from forge.agent import Agent


class ChatWorker(QThread):
    token = Signal(str)         # one streamed chunk of the assistant reply
    tool_status = Signal(str)   # a "> tool(args)" status line
    finished_ok = Signal()      # turn completed cleanly
    failed = Signal(str)        # exception text

    def __init__(self, agent: Agent, message: str, history: list[dict], parent: QObject | None = None):
        super().__init__(parent)
        self._agent = agent
        self._message = message
        self._history = history

    def run(self) -> None:
        try:
            for chunk in self._agent.chat(
                self._message,
                self._history,
                on_tool_status=lambda m: self.tool_status.emit(m.strip()),
            ):
                self.token.emit(chunk)
            self.finished_ok.emit()
        except Exception as e:  # noqa: BLE001 — surface any failure to the UI
            self.failed.emit(str(e))


class IndexWorker(QThread):
    progress = Signal(str)
    done = Signal(int)          # chunks embedded this run
    failed = Signal(str)

    def __init__(self, agent: Agent, project_dir: str, force: bool = False, parent: QObject | None = None):
        super().__init__(parent)
        self._agent = agent
        self._project_dir = project_dir
        self._force = force

    def run(self) -> None:
        try:
            n = self._agent.index.index(
                self._project_dir,
                force=self._force,
                on_progress=lambda m: self.progress.emit(m),
            )
            self.done.emit(n)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class HealthWorker(QThread):
    """Checks connectivity off the UI thread. For the local hermes-router this
    pings /health; for a custom OpenAI-compatible provider (no /health) it probes
    {base_url}/models with the API key instead."""
    result = Signal(bool, str)  # (ok, detail)

    def __init__(self, router_url: str, base_url: str = "", api_key: str = "",
                 is_custom: bool = False, parent: QObject | None = None):
        super().__init__(parent)
        self._router_url = router_url.rstrip("/")
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._is_custom = is_custom

    def run(self) -> None:
        import httpx
        try:
            if self._is_custom:
                r = httpx.get(f"{self._base_url}/models",
                              headers={"Authorization": f"Bearer {self._api_key}"}, timeout=6)
            else:
                r = httpx.get(f"{self._router_url}/health", timeout=5)
            self.result.emit(r.status_code == 200,
                             "connected" if r.status_code == 200 else f"HTTP {r.status_code}")
        except Exception as e:  # noqa: BLE001
            self.result.emit(False, str(e)[:60])


class CallWorker(QThread):
    """Runs an arbitrary callable off the UI thread and emits its return value.

    Used by the Router panel for health/models/logs/docker calls so a slow
    `docker restart` or an unreachable router never freezes the window. A tag
    string is echoed back so one handler can route several call types.
    """
    done = Signal(str, object)   # (tag, result)
    failed = Signal(str, str)    # (tag, error)

    def __init__(self, tag, fn, parent: QObject | None = None):
        super().__init__(parent)
        self._tag = tag
        self._fn = fn

    def run(self) -> None:
        try:
            self.done.emit(self._tag, self._fn())
        except Exception as e:  # noqa: BLE001
            self.failed.emit(self._tag, str(e))
