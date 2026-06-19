import json
import os
import re
from pathlib import Path
from typing import Callable, Iterator

from .config import Config
from .llm import LLMClient
from .memory.personal import PersonalMemory
from .memory.project_index import ProjectIndex
from . import tools as _tools_pkg  # noqa: F401 — runs __init__.py, registers all tools
from .tools.base import get_tools_schema, TOOL_REGISTRY
from .tools import context as tool_context

# Coding-oriented trigger words. The LLM extractor still gates on these (it
# returns NONE for non-facts), so a broad list here just decides *when to ask*,
# not *what to store*.
_REMEMBER_TRIGGERS = (
    "remember", "remember this", "don't forget", "dont forget", "do not forget",
    "keep in mind", "note that", "note this", "make a note", "take note",
    "save that", "save this", "memorize", "memorise",
    "prefer", "i always", "i never", "we use", "i use", "my stack", "stack is",
)

_TRIGGER_RE = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in _REMEMBER_TRIGGERS) + r")\b",
    re.IGNORECASE,
)

_MAX_TOOL_ROUNDS = 10

# (marker file, label) — first match wins for the active-project banner.
_STACK_MARKERS = [
    ("pyproject.toml", "Python"),
    ("requirements.txt", "Python"),
    ("setup.py", "Python"),
    ("package.json", "Node.js"),
    ("Cargo.toml", "Rust"),
    ("go.mod", "Go"),
    ("pom.xml", "Java (Maven)"),
    ("build.gradle", "Java/Kotlin (Gradle)"),
    ("Gemfile", "Ruby"),
    ("composer.json", "PHP"),
]


def detect_stack(project_dir: str) -> str:
    """Best-effort language/stack label from marker files. '' if unknown."""
    if not project_dir or not os.path.isdir(project_dir):
        return ""
    for marker, label in _STACK_MARKERS:
        if os.path.exists(os.path.join(project_dir, marker)):
            return label
    return ""


class Agent:
    """Forge's brain. Stateless per conversation — the caller (TUI) owns the
    history list and passes it into chat(). One developer, one mode."""

    def __init__(self, config: Config):
        self._config = config
        self._llm = LLMClient(config)
        self._memory = PersonalMemory(config.db_path)
        self._index = ProjectIndex(config.db_path)

        # Publish runtime context to the stateless tool functions.
        tool_context.set_shell_timeout(config.shell_timeout)
        tool_context.set_index(self._index)
        if config.project_dir:
            tool_context.set_project_dir(config.project_dir)

    # ── project ────────────────────────────────────────────────────────

    def set_project(self, path: str) -> str:
        """Point Forge at a project directory. Returns the resolved path or ''."""
        resolved = str(Path(path).expanduser().resolve()) if path else ""
        self._config.project_dir = resolved
        tool_context.set_project_dir(resolved)
        return resolved

    @property
    def project_dir(self) -> str:
        return self._config.project_dir

    @property
    def index(self) -> ProjectIndex:
        return self._index

    # ── memory ─────────────────────────────────────────────────────────

    def _should_remember(self, text: str) -> bool:
        return _TRIGGER_RE.search(text) is not None

    def _fallback_fact(self, message: str) -> str:
        text = _TRIGGER_RE.sub("", message)
        text = re.sub(r"\s+", " ", text).strip(" .,:;-\n\t")
        return text[:200]

    def _trim_history(self, history: list[dict]) -> None:
        cap = self._config.max_history_messages
        if len(history) <= cap:
            return
        idx = len(history) - cap
        while idx < len(history) and history[idx]["role"] != "user":
            idx += 1
        del history[:idx]

    # ── system prompt ──────────────────────────────────────────────────

    def _build_system_message(self, query: str = "") -> dict:
        content = self._config.system_prompt

        # Personal facts (semantic when we have a query, else most recent).
        facts = self._memory.relevant_facts(query, k=5) if query else self._memory.recent_facts(limit=5)
        if facts:
            content += "\n\nWhat you remember about the developer:\n" + "\n".join(f"- {f}" for f in facts)

        # Active project + stack + index status.
        pd = self._config.project_dir
        if pd:
            stack = detect_stack(pd)
            line = f"\n\nActive project: {pd}"
            if stack:
                line += f" (detected: {stack})"
            stats = self._index.stats(pd)
            if stats["chunk_count"]:
                line += (
                    f"\nCodebase indexed: {stats['file_count']} files, "
                    f"{stats['chunk_count']} chunks — use search_codebase() to find code "
                    "before reading files one by one."
                )
            else:
                line += "\nNot indexed yet (the developer can run /index)."
            content += line

        return {"role": "system", "content": content}

    # ── tool execution ─────────────────────────────────────────────────

    def _execute_tool(self, name: str, args_json: str, on_status: Callable[[str], None]) -> str:
        tool = TOOL_REGISTRY.get(name)
        if tool is None:
            return f"Error: unknown tool '{name}'"
        try:
            args = json.loads(args_json) if args_json else {}
        except json.JSONDecodeError:
            return f"Error: invalid JSON arguments for tool '{name}': {args_json}"
        preview = ", ".join(f"{k}={repr(v)[:40]}" for k, v in args.items())
        on_status(f"\n[dim]  > {name}({preview})[/dim]")
        try:
            return tool.fn(**args)
        except Exception as e:
            return f"Error executing {name}: {e}"

    # ── chat ───────────────────────────────────────────────────────────

    def chat(
        self,
        user_message: str,
        history: list[dict],
        *,
        on_tool_status: Callable[[str], None] | None = None,
    ) -> Iterator[str]:
        if self._should_remember(user_message):
            fact = (self._llm.extract(user_message) or "").strip()
            if fact.rstrip(".").upper() == "NONE":
                fact = ""
            elif not fact:
                fact = self._fallback_fact(user_message)
            if fact:
                self._memory.save(fact)

        history.append({"role": "user", "content": user_message})
        self._trim_history(history)

        _status = on_tool_status or (lambda _: None)
        tools_schema = get_tools_schema()
        system_message = self._build_system_message(query=user_message)

        for _round in range(_MAX_TOOL_ROUNDS):
            messages = [system_message] + history
            accumulated_tool_calls: list = []
            full_response = ""

            for token in self._llm.stream_with_tools(messages, tools_schema, accumulated_tool_calls):
                full_response += token
                yield token

            if not accumulated_tool_calls:
                history.append({"role": "assistant", "content": full_response})
                return

            history.append({
                "role": "assistant",
                "content": full_response or None,
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": tc["arguments"]},
                    }
                    for tc in accumulated_tool_calls
                ],
            })

            for tc in accumulated_tool_calls:
                result = self._execute_tool(tc["name"], tc["arguments"], _status)
                history.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })

        yield "\n[tool loop exceeded maximum rounds — stopping]"

    # ── memory access for the TUI ──────────────────────────────────────

    def list_facts(self) -> list[tuple[int, str]]:
        return self._memory.all_facts()

    def add_fact(self, fact: str) -> None:
        self._memory.save(fact)

    def forget_all(self) -> None:
        self._memory.clear()

    def close(self):
        self._memory.close()
        self._index.close()
