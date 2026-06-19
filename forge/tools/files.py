import pathlib

from .base import ToolDefinition, register

# Writes under these system directories are blocked (injection-driven sabotage guard).
_WRITE_BLOCKED_DIRS = ("/etc", "/usr", "/bin", "/sbin", "/boot", "/sys", "/proc", "/dev", "/lib")
# Credential files are off-limits regardless of location.
_WRITE_BLOCKED_NAMES = ("auth.json", ".env")


def _is_write_blocked(path: str) -> bool:
    p = pathlib.Path(path).resolve()
    if p.name in _WRITE_BLOCKED_NAMES:
        return True
    return any(p == pathlib.Path(d) or str(p).startswith(d + "/") for d in _WRITE_BLOCKED_DIRS)


def read_file(path: str) -> str:
    try:
        return pathlib.Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return f"Error: file not found: {path}"
    except PermissionError:
        return f"Error: permission denied: {path}"
    except Exception as e:
        return f"Error reading file: {e}"


def write_file(path: str, content: str) -> str:
    if _is_write_blocked(path):
        return f"Error: writing to {path} is blocked (protected system path)"
    try:
        p = pathlib.Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"OK: wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error writing file: {e}"


register(ToolDefinition(
    name="read_file",
    description="Read the contents of a file on disk and return them as text.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute or relative path to the file."},
        },
        "required": ["path"],
    },
    fn=read_file,
))

register(ToolDefinition(
    name="write_file",
    description="Write text content to a file on disk, creating parent directories as needed.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to write to."},
            "content": {"type": "string", "description": "The text content to write."},
        },
        "required": ["path", "content"],
    },
    fn=write_file,
))
