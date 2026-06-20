import json
import os
from dataclasses import dataclass
from pathlib import Path

_SETTINGS_FILE = "forge_settings.json"  # optional editable overrides (JSON overlay)


@dataclass
class Config:
    """Runtime configuration for Forge (Iris Code).

    Simpler than Iris Teams' Config — no Discord, no dashboard, no org profile.
    Single developer, single mode. Adds `project_dir` (the active codebase) and
    `shell_timeout` (subprocess hard timeout), which are Forge-specific.
    """
    router_url: str = "http://localhost:8319"
    api_key: str = "sk-router-hermes-1"
    model: str = "hermes-router"
    db_path: str = "forge_memory.db"
    max_history_messages: int = 30
    project_dir: str = ""        # active project directory
    shell_timeout: int = 30      # seconds for shell command timeout
    system_prompt: str = (
        "You are Forge, a personal coding assistant. You help with writing, "
        "debugging, and understanding code. You can read and write files, run "
        "shell commands, inspect git state, and search an indexed codebase. "
        "You remember the developer's preferences and project context across "
        "sessions. Be direct and technical — favour concrete commands, diffs, "
        "and code over prose. When you need to inspect or change the project, "
        "use your tools rather than guessing."
    )

    @property
    def base_url(self) -> str:
        """OpenAI-compatible endpoint (router_url + /v1). Used by the LLM client."""
        return self.router_url.rstrip("/") + "/v1"

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            router_url=os.getenv("FORGE_ROUTER_URL", "http://localhost:8319"),
            api_key=os.getenv("FORGE_API_KEY", "sk-router-hermes-1"),
            model=os.getenv("FORGE_MODEL", "hermes-router"),
            db_path=os.getenv("FORGE_DB_PATH", "forge_memory.db"),
            project_dir=os.getenv("FORGE_PROJECT_DIR", ""),
            shell_timeout=int(os.getenv("FORGE_SHELL_TIMEOUT", "30") or "30"),
        )

    @classmethod
    def load(cls) -> "Config":
        """from_env() plus optional overrides from forge_settings.json."""
        cfg = cls.from_env()
        path = Path(_SETTINGS_FILE)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = {}
            if isinstance(data.get("system_prompt"), str) and data["system_prompt"].strip():
                cfg.system_prompt = data["system_prompt"]
            if isinstance(data.get("router_url"), str) and data["router_url"].strip():
                cfg.router_url = data["router_url"]
            if isinstance(data.get("api_key"), str) and data["api_key"].strip():
                cfg.api_key = data["api_key"]
            if isinstance(data.get("model"), str) and data["model"].strip():
                cfg.model = data["model"]
            if isinstance(data.get("project_dir"), str):
                cfg.project_dir = data["project_dir"]
            if isinstance(data.get("shell_timeout"), int):
                cfg.shell_timeout = data["shell_timeout"]
        return cfg

    def save_overrides(self) -> None:
        """Persist the GUI-editable fields to forge_settings.json (used by the
        desktop app's Settings panel). Secrets stay local to this file, which is
        gitignored alongside .env."""
        data = {
            "router_url": self.router_url,
            "api_key": self.api_key,
            "model": self.model,
            "project_dir": self.project_dir,
            "shell_timeout": self.shell_timeout,
        }
        Path(_SETTINGS_FILE).write_text(json.dumps(data, indent=2), encoding="utf-8")
