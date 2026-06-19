"""
Shell execution — the capability that makes Forge more powerful than Iris Teams.

Runs commands in a subprocess with a hard timeout, captures stdout+stderr,
truncates large output, and blocks a small set of catastrophic commands. This is
a personal, trusted tool (no sandbox), but the blocklist and timeout keep an
LLM mistake — or a prompt injection from fetched web content — from nuking the
machine or hanging forever.
"""
import subprocess

from .base import ToolDefinition, register
from . import context

# Substrings that should never run. Catastrophic / irreversible at the root level.
_BLOCKLIST = (
    "rm -rf /",
    "rm -rf /*",
    ":(){:|:&};:",     # fork bomb
    "mkfs",
    "dd if=",
    "> /dev/sd",
    "of=/dev/sd",
    "chmod -R 000 /",
)

_MAX_STDOUT = 8000
_MAX_STDERR = 2000


def _blocked(command: str) -> str | None:
    lowered = command.replace("  ", " ")
    for bad in _BLOCKLIST:
        if bad in command or bad in lowered:
            return bad
    return None


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    # Keep the tail — errors and final output usually matter most.
    return "...[truncated " + str(len(text) - limit) + " chars]...\n" + text[-limit:]


def run_command(command: str, cwd: str | None = None, timeout: int | None = None) -> str:
    """Run a shell command and return a formatted result string.

    cwd defaults to the active project directory; timeout to config.shell_timeout.
    """
    bad = _blocked(command)
    if bad:
        return f"Error: refused to run — command matches blocklist entry '{bad}'"

    run_cwd = context.resolve_cwd(cwd)
    run_timeout = timeout if timeout is not None else context.get_shell_timeout()

    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=run_cwd,
            timeout=run_timeout,
            capture_output=True,
            text=True,
        )
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {run_timeout}s (process killed):\n$ {command}"
    except Exception as e:
        return f"Error running command: {e}"

    stdout = _truncate(result.stdout or "", _MAX_STDOUT)
    stderr = _truncate(result.stderr or "", _MAX_STDERR)

    parts = [f"$ {command}", f"(exit {result.returncode}, cwd={run_cwd or '.'})"]
    if stdout.strip():
        parts.append("--- stdout ---\n" + stdout.rstrip())
    if stderr.strip():
        parts.append("--- stderr ---\n" + stderr.rstrip())
    if not stdout.strip() and not stderr.strip():
        parts.append("(no output)")
    return "\n".join(parts)


# Auto-detection table for run_tests: (marker filename, test command).
_TEST_DETECT = [
    ("pytest.ini", "pytest"),
    ("pyproject.toml", "pytest"),
    ("setup.py", "pytest"),
    ("requirements.txt", "pytest"),
    ("package.json", "npm test"),
    ("Cargo.toml", "cargo test"),
    ("go.mod", "go test ./..."),
    ("pom.xml", "mvn test"),
    ("build.gradle", "gradle test"),
]


def run_tests(framework: str = "auto", path: str = ".") -> str:
    """Detect the project's test framework and run it.

    framework: one of auto|pytest|jest|npm|cargo|go|maven|gradle.
    path: directory to run in (relative to the project dir, or absolute).
    """
    import os

    base = context.resolve_cwd(None) or "."
    target = path if os.path.isabs(path) else os.path.join(base, path)

    cmd_map = {
        "pytest": "pytest",
        "jest": "npx jest",
        "npm": "npm test",
        "cargo": "cargo test",
        "go": "go test ./...",
        "maven": "mvn test",
        "gradle": "gradle test",
    }

    if framework != "auto":
        cmd = cmd_map.get(framework)
        if not cmd:
            return f"Error: unknown framework '{framework}'. Use one of: auto, {', '.join(cmd_map)}"
    else:
        cmd = None
        for marker, test_cmd in _TEST_DETECT:
            if os.path.exists(os.path.join(target, marker)):
                cmd = test_cmd
                break
        if cmd is None:
            return ("Error: could not auto-detect a test framework in "
                    f"{target} (no pytest/package.json/Cargo.toml/go.mod/etc). "
                    "Pass framework= explicitly.")

    return run_command(cmd, cwd=target)


register(ToolDefinition(
    name="run_command",
    description=(
        "Run a shell command in the developer's terminal and return stdout, stderr, "
        "and exit code. Runs in the active project directory by default. Has a hard "
        "timeout and blocks catastrophic commands. Use this to build, run, inspect, "
        "or modify the environment."
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The shell command to run."},
            "cwd": {"type": "string", "description": "Working directory (optional; defaults to the active project)."},
            "timeout": {"type": "integer", "description": "Timeout in seconds (optional)."},
        },
        "required": ["command"],
    },
    fn=run_command,
))

register(ToolDefinition(
    name="run_tests",
    description=(
        "Detect and run the project's test suite (pytest, jest/npm, cargo, go, "
        "maven, gradle). Returns the test output."
    ),
    parameters={
        "type": "object",
        "properties": {
            "framework": {
                "type": "string",
                "description": "auto (default) or one of pytest|jest|npm|cargo|go|maven|gradle.",
            },
            "path": {"type": "string", "description": "Directory to test in (optional, default '.')."},
        },
        "required": [],
    },
    fn=run_tests,
))
