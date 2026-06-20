import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

_SETTINGS_FILE = "forge_settings.json"  # optional editable overrides (JSON overlay)
_APP_DIR_NAME = "IrisCode"


def user_data_dir() -> Path:
    """Per-user, writable directory for the DB and settings.

    Critical for the packaged desktop app: an installed binary runs with its
    working directory set to the (read-only) install location, so relative
    paths like 'forge_memory.db' fail with 'unable to open database file'.
    Resolve to the OS-standard app-data location instead:
      • Windows: %APPDATA%\\IrisCode
      • macOS:   ~/Library/Application Support/IrisCode
      • Linux:   $XDG_DATA_HOME/IrisCode (default ~/.local/share/IrisCode)
    """
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~\\AppData\\Roaming")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    d = Path(base) / _APP_DIR_NAME
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        d = Path(os.path.expanduser("~"))  # last resort: home dir
    return d


def settings_path() -> Path:
    """Location of forge_settings.json. Honours FORGE_SETTINGS_PATH; otherwise
    sits in the user data dir so the GUI can always write it."""
    override = os.getenv("FORGE_SETTINGS_PATH")
    return Path(override) if override else user_data_dir() / _SETTINGS_FILE


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
    router_container: str = "hermes-router"  # docker container name for the router
    router_config_path: str = ""             # path to the router's .env/config file
    router_dir: str = ""                     # hermes-router folder (docker-compose.yml + .env)
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
        # When FORGE_DB_PATH isn't set, default to a writable per-user location
        # (not the cwd), so the installed desktop app can always open its DB.
        db_path = os.getenv("FORGE_DB_PATH") or str(user_data_dir() / "forge_memory.db")
        return cls(
            router_url=os.getenv("FORGE_ROUTER_URL", "http://localhost:8319"),
            api_key=os.getenv("FORGE_API_KEY", "sk-router-hermes-1"),
            model=os.getenv("FORGE_MODEL", "hermes-router"),
            db_path=db_path,
            project_dir=os.getenv("FORGE_PROJECT_DIR", ""),
            shell_timeout=int(os.getenv("FORGE_SHELL_TIMEOUT", "30") or "30"),
            router_container=os.getenv("FORGE_ROUTER_CONTAINER", "hermes-router"),
            router_config_path=os.getenv("FORGE_ROUTER_CONFIG", ""),
            router_dir=os.getenv("FORGE_ROUTER_DIR", ""),
        )

    @classmethod
    def load(cls) -> "Config":
        """from_env() plus optional overrides from forge_settings.json."""
        cfg = cls.from_env()
        path = settings_path()
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
            if isinstance(data.get("router_container"), str) and data["router_container"].strip():
                cfg.router_container = data["router_container"]
            if isinstance(data.get("router_config_path"), str):
                cfg.router_config_path = data["router_config_path"]
            if isinstance(data.get("router_dir"), str):
                cfg.router_dir = data["router_dir"]
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
            "router_container": self.router_container,
            "router_config_path": self.router_config_path,
            "router_dir": self.router_dir,
        }
        settings_path().write_text(json.dumps(data, indent=2), encoding="utf-8")
