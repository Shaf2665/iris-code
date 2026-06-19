"""
Git inspection tools. Thin wrappers over `git` via run_command — no separate
subprocess logic, so they inherit the same timeout, cwd defaulting, and output
truncation. Read-only by design (status/diff/log/blame); commits and history
rewrites go through run_command explicitly so they're always visible.
"""
from .base import ToolDefinition, register
from .shell import run_command
from . import context

_DIFF_MAX = 6000


def _git(args: str, cwd: str | None = None) -> str:
    return run_command(f"git {args}", cwd=cwd)


def git_status(cwd: str | None = None) -> str:
    """Branch + short status of the working tree."""
    branch = run_command("git branch --show-current", cwd=cwd)
    status = run_command("git status --short", cwd=cwd)
    return branch + "\n\n" + status


def git_diff(cwd: str | None = None, staged: bool = False) -> str:
    """Unified diff of unstaged (or staged) changes, truncated."""
    flag = " --staged" if staged else ""
    out = _git("diff" + flag, cwd=cwd)
    if len(out) > _DIFF_MAX:
        out = out[:_DIFF_MAX] + "\n...[diff truncated]..."
    return out


def git_log(cwd: str | None = None, n: int = 10) -> str:
    """The last n commits, one line each."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        n = 10
    return _git(f"log --oneline -n {n}", cwd=cwd)


def git_blame_line(file: str, line: int, cwd: str | None = None) -> str:
    """Who last changed a single line, and in which commit."""
    try:
        line = int(line)
    except (TypeError, ValueError):
        return "Error: line must be an integer"
    return _git(f"blame -L {line},{line} -- {file}", cwd=cwd)


def project_git_summary(cwd: str | None = None) -> str:
    """Convenience for the TUI /git command: status + recent log."""
    target = context.resolve_cwd(cwd)
    return git_status(cwd=target) + "\n\n--- recent commits ---\n" + git_log(cwd=target, n=10)


register(ToolDefinition(
    name="git_status",
    description="Show the current git branch and short working-tree status.",
    parameters={
        "type": "object",
        "properties": {"cwd": {"type": "string", "description": "Repo directory (optional)."}},
        "required": [],
    },
    fn=git_status,
))

register(ToolDefinition(
    name="git_diff",
    description="Show the git diff of unstaged changes (or staged with staged=true).",
    parameters={
        "type": "object",
        "properties": {
            "cwd": {"type": "string", "description": "Repo directory (optional)."},
            "staged": {"type": "boolean", "description": "Diff staged changes instead of unstaged."},
        },
        "required": [],
    },
    fn=git_diff,
))

register(ToolDefinition(
    name="git_log",
    description="Show the last n commits as one-line summaries (default 10).",
    parameters={
        "type": "object",
        "properties": {
            "cwd": {"type": "string", "description": "Repo directory (optional)."},
            "n": {"type": "integer", "description": "Number of commits (default 10)."},
        },
        "required": [],
    },
    fn=git_log,
))

register(ToolDefinition(
    name="git_blame_line",
    description="Show who last changed a specific line of a file (git blame for one line).",
    parameters={
        "type": "object",
        "properties": {
            "file": {"type": "string", "description": "Path to the file."},
            "line": {"type": "integer", "description": "Line number to blame."},
            "cwd": {"type": "string", "description": "Repo directory (optional)."},
        },
        "required": ["file", "line"],
    },
    fn=git_blame_line,
))
