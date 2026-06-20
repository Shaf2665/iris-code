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

import re
import shutil
import subprocess
import time
from pathlib import Path

import httpx

_DOCKER_TIMEOUT = 25
_COMPOSE_TIMEOUT = 600   # builds/pulls can take minutes

# hermes-router provider registry — id, label, the .env var that holds the
# comma-separated key(s), the model-override var, and where to get a key. Mirrors
# router.py's _keys_for() calls so what the GUI writes is what the router reads.
PROVIDERS: list[dict] = [
    {"id": "gemini", "label": "Google Gemini", "keys_var": "GEMINI_API_KEYS",
     "model_var": "GEMINI_MODEL", "url": "https://aistudio.google.com/apikey",
     "note": "Free tier, resets per minute"},
    {"id": "openrouter", "label": "OpenRouter", "keys_var": "OPENROUTER_API_KEYS",
     "model_var": "OPENROUTER_MODEL", "url": "https://openrouter.ai/keys",
     "note": "50 free requests/day per key"},
    {"id": "sambanova", "label": "SambaNova", "keys_var": "SAMBANOVA_API_KEYS",
     "model_var": "SAMBANOVA_MODEL", "url": "https://cloud.sambanova.ai",
     "note": "Free, fast Llama/DeepSeek"},
    {"id": "github_models", "label": "GitHub Models", "keys_var": "GITHUB_MODELS_TOKENS",
     "model_var": "GITHUB_MODELS_MODEL", "url": "https://github.com/settings/tokens",
     "note": "Free with any GitHub PAT"},
    {"id": "cerebras", "label": "Cerebras", "keys_var": "CEREBRAS_API_KEYS",
     "model_var": "CEREBRAS_MODEL", "url": "https://cloud.cerebras.ai",
     "note": "Very fast inference, free tier"},
    {"id": "groq", "label": "Groq", "keys_var": "GROQ_API_KEYS",
     "model_var": "GROQ_MODEL", "url": "https://console.groq.com/keys",
     "note": "Very fast, free tier"},
    {"id": "mistral", "label": "Mistral", "keys_var": "MISTRAL_API_KEYS",
     "model_var": "MISTRAL_MODEL", "url": "https://console.mistral.ai/api-keys",
     "note": "Free tier"},
    {"id": "cohere", "label": "Cohere", "keys_var": "COHERE_API_KEYS",
     "model_var": "COHERE_MODEL", "url": "https://dashboard.cohere.com/api-keys",
     "note": "Free trial, 256K context"},
    {"id": "zai", "label": "Z.ai / GLM", "keys_var": "GLM_API_KEYS",
     "model_var": "ZAI_MODEL", "url": "https://z.ai",
     "note": "Free, glm-4.5-flash"},
    {"id": "naga", "label": "Naga AI", "keys_var": "NAGA_API_KEYS",
     "model_var": "NAGA_MODEL", "url": "https://naga.ac",
     "note": "Free, Nemotron-120B"},
    {"id": "nvidia", "label": "NVIDIA NIM", "keys_var": "NVIDIA_API_KEYS",
     "model_var": "NVIDIA_MODEL", "url": "https://build.nvidia.com",
     "note": "Free, DeepSeek, 1M context"},
    {"id": "huggingface", "label": "Hugging Face", "keys_var": "HUGGINGFACE_API_KEYS",
     "model_var": "HUGGINGFACE_MODEL", "url": "https://huggingface.co/settings/tokens",
     "note": "Inference providers"},
    {"id": "openai", "label": "OpenAI", "keys_var": "OPENAI_API_KEYS",
     "model_var": "OPENAI_MODEL", "url": "https://platform.openai.com/api-keys",
     "note": "Paid"},
    {"id": "anthropic", "label": "Anthropic", "keys_var": "ANTHROPIC_API_KEYS",
     "model_var": "ANTHROPIC_MODEL", "url": "https://console.anthropic.com/settings/keys",
     "note": "Paid"},
]


class RouterAdmin:
    def __init__(
        self,
        base_url: str = "http://localhost:8319",
        api_key: str = "",
        container: str = "hermes-router",
        config_path: str = "",
        router_dir: str = "",
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.container = container
        self.config_path = config_path
        self.router_dir = router_dir

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

    # ── router folder: .env (provider keys) + docker compose lifecycle ──

    def env_path(self) -> Path:
        return Path(self.router_dir) / ".env"

    def read_env_vars(self) -> dict[str, str]:
        """Parse KEY=VALUE pairs from the router's .env (ignores comments)."""
        out: dict[str, str] = {}
        p = self.env_path()
        if not self.router_dir or not p.exists():
            return out
        for line in p.read_text(encoding="utf-8").splitlines():
            m = re.match(r"\s*([A-Za-z0-9_]+)\s*=(.*)$", line)
            if m and not line.lstrip().startswith("#"):
                out[m.group(1)] = m.group(2).strip()
        return out

    def provider_state(self) -> list[dict]:
        """Per-provider current keys + model override from .env, for the UI."""
        env = self.read_env_vars()
        state = []
        for prov in PROVIDERS:
            state.append({
                **prov,
                "keys": env.get(prov["keys_var"], ""),
                "model": env.get(prov["model_var"], ""),
            })
        return state

    def write_env_vars(self, updates: dict[str, str]) -> tuple[bool, str]:
        """Merge updates into the router's .env, preserving comments and other
        vars. An empty value removes that var (disables the provider). Creates
        the file if missing."""
        if not self.router_dir:
            return False, "Set the hermes-router folder first."
        p = self.env_path()
        try:
            lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
        except Exception as e:  # noqa: BLE001
            return False, f"Could not read {p}: {e}"

        seen: set[str] = set()
        out: list[str] = []
        for line in lines:
            m = re.match(r"\s*([A-Za-z0-9_]+)\s*=", line)
            key = m.group(1) if m and not line.lstrip().startswith("#") else None
            if key in updates:
                seen.add(key)
                val = updates[key]
                if val != "":
                    out.append(f"{key}={val}")
                # empty value → drop the line (provider disabled)
            else:
                out.append(line)
        for key, val in updates.items():
            if key not in seen and val != "":
                out.append(f"{key}={val}")

        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("\n".join(out) + "\n", encoding="utf-8")
            return True, f"Saved {p}"
        except Exception as e:  # noqa: BLE001
            return False, f"Could not write {p}: {e}"

    # docker compose lifecycle (run inside the router folder) ------------

    def _compose(self, *args: str, timeout: int = _COMPOSE_TIMEOUT) -> tuple[bool, str]:
        if not self.router_dir:
            return False, "Set the hermes-router folder first (the folder with docker-compose.yml)."
        if not (Path(self.router_dir) / "docker-compose.yml").exists() and \
           not (Path(self.router_dir) / "compose.yml").exists():
            return False, f"No docker-compose.yml in {self.router_dir}"
        try:
            p = subprocess.run(
                ["docker", "compose", *args],
                cwd=self.router_dir, capture_output=True, text=True, timeout=timeout,
            )
            return p.returncode == 0, (p.stdout + p.stderr).strip() or "(no output)"
        except FileNotFoundError:
            return False, "docker is not installed or not on PATH"
        except subprocess.TimeoutExpired:
            return False, f"docker compose {args[0] if args else ''} timed out"
        except Exception as e:  # noqa: BLE001
            return False, str(e)

    def compose_up(self) -> tuple[bool, str]:
        return self._compose("up", "-d")

    def compose_down(self) -> tuple[bool, str]:
        return self._compose("down")

    def compose_restart(self) -> tuple[bool, str]:
        return self._compose("restart")

    def compose_logs(self, tail: int = 200) -> str:
        ok, out = self._compose("logs", "--tail", str(int(tail)), "--no-color", timeout=_DOCKER_TIMEOUT)
        return out

    def compose_update(self) -> tuple[bool, str]:
        """git pull in the router folder, then rebuild + restart the container."""
        if not self.router_dir:
            return False, "Set the hermes-router folder first."
        steps = []
        try:
            g = subprocess.run(["git", "-C", self.router_dir, "pull", "--ff-only"],
                               capture_output=True, text=True, timeout=120)
            steps.append("$ git pull\n" + (g.stdout + g.stderr).strip())
            if g.returncode != 0:
                return False, "\n\n".join(steps)
        except Exception as e:  # noqa: BLE001
            steps.append(f"git pull failed: {e}")
            return False, "\n\n".join(steps)

        ok, out = self._compose("up", "-d", "--build")
        steps.append("$ docker compose up -d --build\n" + out)
        return ok, "\n\n".join(steps)
