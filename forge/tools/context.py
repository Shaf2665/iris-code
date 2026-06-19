"""
Shared runtime context for stateless tool functions.

Tools registered in the TOOL_REGISTRY are plain module-level functions with no
reference to the Agent or Config. But several of them (shell, git, codebase
search) need to know the *active project directory*, the shell timeout, and the
project index. The Agent owns those and pushes them here whenever they change;
the tool functions read them back. This keeps the tool signatures clean for the
LLM (it doesn't have to pass `cwd` every time) while still letting an explicit
`cwd`/`timeout` argument override the default.
"""
from __future__ import annotations

_state: dict = {
    "project_dir": "",
    "shell_timeout": 30,
    "index": None,          # forge.memory.project_index.ProjectIndex | None
}


def set_project_dir(path: str) -> None:
    _state["project_dir"] = path or ""


def get_project_dir() -> str:
    return _state["project_dir"]


def set_shell_timeout(seconds: int) -> None:
    _state["shell_timeout"] = int(seconds)


def get_shell_timeout() -> int:
    return int(_state["shell_timeout"])


def set_index(index) -> None:
    _state["index"] = index


def get_index():
    return _state["index"]


def resolve_cwd(cwd: str | None) -> str | None:
    """An explicit cwd wins; otherwise fall back to the active project dir."""
    if cwd:
        return cwd
    return _state["project_dir"] or None
