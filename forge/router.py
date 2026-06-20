"""
hermes-router admin — a thin, Qt-free helper the GUI uses to observe and control
a locally-running router. Two surfaces:

  • HTTP   — health/providers/models/latency via the router's own endpoints.
  • Docker — start/stop/restart/logs of the router container, plus reading and
             writing its config file (e.g. its .env).

Everything is best-effort and never raises: callers (worker threads) get
structured results so the UI can show a clear state instead of crashing. Docker
calls degrade gracefully when docker isn't installed or the container is absent.
"""
from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

import httpx

_DOCKER_TIMEOUT = 25


class RouterAdmin:
    def __init__(
        self,
        base_url: str = "http://localhost:8319",
        api_key: str = "",
        container: str = "hermes-router",
        config_path: str = "",
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.container = container
        self.config_path = config_path

    # ── HTTP: health / models ──────────────────────────────────────────

    def health(self) -> dict:
        """{ok, status, providers[], latency_ms} or {ok: False, error}."""
        t0 = time.time()
        try:
            r = httpx.get(f"{self.base_url}/health", timeout=5)
            ms = int((time.time() - t0) * 1000)
            if r.status_code == 200:
                try:
                    data = r.json()
                except Exception:
                    data = {}
                return {
                    "ok": True,
                    "status": data.get("status", "ok"),
                    "providers": data.get("providers", []),
                    "latency_ms": ms,
                }
            return {"ok": False, "error": f"HTTP {r.status_code}", "latency_ms": ms}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)[:140]}

    def models(self) -> list[str]:
        """Model ids from /v1/models (empty list on any failure)."""
        try:
            headers = {"Authorization": f"Bearer {self.api_key or 'x'}"}
            r = httpx.get(f"{self.base_url}/v1/models", headers=headers, timeout=5)
            if r.status_code == 200:
                return [m.get("id", "") for m in r.json().get("data", []) if m.get("id")]
        except Exception:  # noqa: BLE001
            pass
        return []

    # ── Docker: lifecycle / logs ───────────────────────────────────────

    @staticmethod
    def docker_available() -> bool:
        return shutil.which("docker") is not None

    def _docker(self, *args: str) -> tuple[int, str]:
        try:
            p = subprocess.run(
                ["docker", *args], capture_output=True, text=True, timeout=_DOCKER_TIMEOUT
            )
            return p.returncode, (p.stdout + p.stderr).strip()
        except FileNotFoundError:
            return 127, "docker is not installed or not on PATH"
        except subprocess.TimeoutExpired:
            return -1, f"docker {args[0] if args else ''} timed out"
        except Exception as e:  # noqa: BLE001
            return -1, str(e)

    def container_status(self) -> str:
        """running | exited | paused | missing | docker-missing | unknown."""
        if not self.docker_available():
            return "docker-missing"
        rc, out = self._docker("inspect", "-f", "{{.State.Status}}", self.container)
        if rc != 0:
            return "missing"
        return out.strip() or "unknown"

    def start(self) -> tuple[bool, str]:
        rc, out = self._docker("start", self.container)
        return rc == 0, out

    def stop(self) -> tuple[bool, str]:
        rc, out = self._docker("stop", self.container)
        return rc == 0, out

    def restart(self) -> tuple[bool, str]:
        rc, out = self._docker("restart", self.container)
        return rc == 0, out

    def logs(self, tail: int = 200) -> str:
        if not self.docker_available():
            return "docker is not installed or not on PATH."
        rc, out = self._docker("logs", "--tail", str(int(tail)), self.container)
        return out or "(no output)"

    # ── Config file (e.g. the router's .env) ───────────────────────────

    def read_config(self) -> tuple[bool, str]:
        if not self.config_path:
            return False, "No config path set. Point this at the router's .env or config file."
        p = Path(self.config_path)
        if not p.exists():
            return False, f"File not found: {p}"
        try:
            return True, p.read_text(encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            return False, f"Could not read {p}: {e}"

    def write_config(self, text: str) -> tuple[bool, str]:
        if not self.config_path:
            return False, "No config path set."
        try:
            Path(self.config_path).write_text(text, encoding="utf-8")
            return True, f"Saved {self.config_path}"
        except Exception as e:  # noqa: BLE001
            return False, f"Could not write {self.config_path}: {e}"
