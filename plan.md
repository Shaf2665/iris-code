# Iris Code — L1 to L3 Implementation Plan

## Context

Iris Code is a personal coding assistant powered by hermes-router (free, local at :8319).
It shares DNA with Iris Teams (`/root/Iris-Teams`) — same LLM client, same TUI shell,
same SQLite+embedding pattern — but is built for a single developer rather than an org.

The defining capability that Iris Teams lacks: **Forge can run shell commands and index
your codebase**. Everything else is adapted from Iris.

Read `CLAUDE.md` before starting — it has hermes-router credentials, the list of Iris
modules to copy verbatim, and the venv setup command.

---

## Layer 1 — TUI Chat + Personal Memory

**Goal:** Working terminal chat with hermes-router, persistent personal memory, named sessions.

### 1A — Project scaffold

Create the venv and install base deps:
```bash
VIRTUAL_ENV=/root/Iris-Code/.venv /root/.hermes/bin/uv venv --python 3.11 /root/Iris-Code/.venv
VIRTUAL_ENV=/root/Iris-Code/.venv /root/.hermes/bin/uv pip install openai httpx prompt_toolkit rich numpy
```

Create `requirements.txt`:
```
openai>=1.0.0
httpx>=0.27.0
prompt_toolkit>=3.0.0
rich>=13.0.0
numpy>=1.26.0
```

Scaffold empty files:
```
forge/__init__.py
forge/agent.py
forge/llm.py
forge/config.py
forge/tui.py
forge/memory/__init__.py
forge/memory/embedder.py
forge/memory/conversations.py
forge/memory/personal.py
forge/tools/__init__.py
forge/tools/base.py
forge/tools/files.py
forge/tools/web.py
main.py
.env
.env.example
```

### 1B — Copy verbatim from Iris Teams (no changes)

These files are production-hardened — copy exactly:
- `iris/memory/embedder.py`   → `forge/memory/embedder.py`
- `iris/memory/conversations.py` → `forge/memory/conversations.py`
- `iris/tools/base.py`        → `forge/tools/base.py`
- `iris/tools/files.py`       → `forge/tools/files.py`
- `iris/tools/web.py`         → `forge/tools/web.py`
- `iris/llm.py`               → `forge/llm.py`  (update env var names: FORGE_* not IRIS_*)

### 1C — Config (`forge/config.py`)

Simpler than Iris — no Discord, no dashboard, no org profile.

```python
@dataclass
class Config:
    router_url: str = "http://localhost:8319"
    api_key: str = "sk-router-hermes-1"
    model: str = "hermes-router"
    db_path: str = "forge_memory.db"
    max_history: int = 30
    project_dir: str = ""        # active project directory
    shell_timeout: int = 30      # seconds for shell commands

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            router_url=os.getenv("FORGE_ROUTER_URL", "http://localhost:8319"),
            api_key=os.getenv("FORGE_API_KEY", "sk-router-hermes-1"),
            db_path=os.getenv("FORGE_DB_PATH", "forge_memory.db"),
            project_dir=os.getenv("FORGE_PROJECT_DIR", ""),
            shell_timeout=int(os.getenv("FORGE_SHELL_TIMEOUT", "30")),
        )
```

### 1D — Personal memory (`forge/memory/personal.py`)

Same pattern as `iris/memory/owner.py` but simpler name + adapted for coding context.

Tables:
- `facts (id, fact, timestamp, embedding BLOB)` — same as Iris

Key difference: trigger words for auto-save should include coding-specific signals:
`remember`, `note`, `save`, `prefer`, `always`, `never`, `use`, `stack`, `project`.

Methods:
- `save(fact)` — dedup + embed + store
- `relevant_facts(query, k=5)` — semantic search (same as Iris)
- `recent_facts(limit=20)` — fallback
- `all_facts()` — for `/memory` command
- `update(id, fact)`, `delete(id)`, `clear()`

### 1E — Agent (`forge/agent.py`)

Simpler than Iris — no customer/channel/org mode. One mode only: the developer.

```python
class Agent:
    def __init__(self, config: Config):
        self._config = config
        self._memory = PersonalMemory(config.db_path)
        self._tools = [ReadFileTool(), WriteFileTool(), FetchUrlTool()]

    def chat(self, message: str, history: list[dict]) -> Iterator[str]:
        # inject relevant memories as system context
        # run the agentic loop (same pattern as Iris agent.py)
        # auto-save facts from responses (same trigger-word pattern)
        ...
```

System prompt (lean, developer-focused):
```
You are Forge, a personal coding assistant. You help with writing, debugging, and
understanding code. You have access to file tools and web fetch. You remember the
developer's preferences and project context across sessions. Be direct and technical.
```

### 1F — TUI (`forge/tui.py`)

Adapt from `iris/tui.py`. Same prompt_toolkit shell + Rich markdown rendering.

Commands to implement in L1:
- `/clear` — clear session history
- `/memory` — list saved facts
- `/forget` — clear all facts
- `/sessions` — list saved sessions
- `/switch <name>` — switch to a named session
- `/help` — show commands

Commands to stub (implement in L2/L3):
- `/project <path>` — set active project directory
- `/run <cmd>` — run a shell command
- `/git` — show git status of active project
- `/index` — index the active project

### 1G — Entry points

**`main.py`:**
```python
from forge.tui import run_tui
from forge.config import Config

if __name__ == "__main__":
    run_tui(Config.from_env())
```

**`/usr/local/bin/forge`** (bash script):
```bash
#!/usr/bin/env bash
set -a; [ -f /root/Iris-Code/.env ] && source /root/Iris-Code/.env; set +a
exec /root/Iris-Code/.venv/bin/python -m forge "$@"
```

### 1H — Verification

```bash
# Imports work
python -c "from forge.agent import Agent; from forge.tui import run_tui; print('OK')"

# hermes-router reachable
curl -s http://localhost:8319/health

# Memory saves and retrieves
python -c "
from forge.memory.personal import PersonalMemory
m = PersonalMemory('/tmp/test_forge.db')
m.save('I prefer Python over JavaScript')
print(m.relevant_facts('what language'))  # should return the fact
"

# TUI launches
forge  # should show the chat prompt
```

---

## Layer 2 — Shell Execution + Git Tools

**Goal:** Forge can run commands in your terminal and understand your git state.

### 2A — Shell tool (`forge/tools/shell.py`)

This is the core capability that makes Forge more powerful than Iris.

**Tools to implement:**

`run_command(command: str, cwd: str | None = None, timeout: int = 30) -> dict`
- Runs any shell command in a subprocess
- Returns `{stdout, stderr, returncode, timed_out}`
- Hard timeout (kills process if exceeded)
- Truncates output > 8000 chars (keep last N chars for errors)
- `cwd` defaults to the agent's `config.project_dir` if set

`run_tests(framework: str = "auto", path: str = ".") -> dict`
- Detects test framework: pytest (py), jest (js/ts), cargo test (rust), go test (go)
- Runs the appropriate test command
- Returns structured output

**Safety rules (no sandbox needed — this is personal use, but still be sensible):**
- Never run `rm -rf /` or similar destructive root-level commands (blocklist)
- Always show the command being run before executing (agent includes it in tool_use display)
- Timeout kills the process — no hanging tools
- Capture both stdout and stderr

```python
import subprocess, shlex, os

_BLOCKLIST = ["rm -rf /", "mkfs", "dd if=", "> /dev/sd"]

def run_command(command: str, cwd: str | None = None, timeout: int = 30) -> dict:
    for blocked in _BLOCKLIST:
        if blocked in command:
            return {"error": f"Blocked: {blocked}", "returncode": -1}
    try:
        result = subprocess.run(
            command, shell=True, cwd=cwd, timeout=timeout,
            capture_output=True, text=True
        )
        out = result.stdout
        if len(out) > 8000:
            out = "...[truncated]...\n" + out[-7000:]
        return {"stdout": out, "stderr": result.stderr[-2000:], "returncode": result.returncode}
    except subprocess.TimeoutExpired:
        return {"error": f"Command timed out after {timeout}s", "timed_out": True, "returncode": -1}
```

### 2B — Git tool (`forge/tools/git.py`)

Wraps common git commands. The agent calls these as tools.

**Tools to implement:**

`git_status(cwd: str | None = None) -> str`
- Runs `git status --short` + `git branch --show-current`
- Returns formatted string

`git_diff(cwd: str | None = None, staged: bool = False) -> str`
- Runs `git diff` or `git diff --staged`
- Truncates at 6000 chars

`git_log(cwd: str | None = None, n: int = 10) -> str`
- Runs `git log --oneline -n {n}`

`git_blame_line(file: str, line: int, cwd: str | None = None) -> str`
- Runs `git blame -L {line},{line} {file}`
- Useful for "who changed this line and why?"

All git tools use `run_command()` internally — no separate subprocess logic.

### 2C — TUI commands for L2

Add to the TUI:
- `/project <path>` — sets `config.project_dir`, prints confirmation + git status if it's a repo
- `/run <cmd>` — runs command in `config.project_dir`, streams output
- `/git` — prints git status + recent log of active project

### 2D — Agent update for L2

Add `ShellTool`, `RunTestsTool`, `GitStatusTool`, `GitDiffTool`, `GitLogTool` to the agent's tool list.

Update the system prompt to mention the active project directory if one is set:
```
Active project: /home/shafiq/myapp (detected: Python/FastAPI)
```

**Project detection** (simple heuristic, no indexing yet):
- Look for `requirements.txt` / `pyproject.toml` → Python
- `package.json` → Node.js
- `Cargo.toml` → Rust
- `go.mod` → Go
- `pom.xml` / `build.gradle` → Java

### 2E — Verification

```bash
# Shell tool works
python -c "
from forge.tools.shell import run_command
r = run_command('echo hello && ls -la', cwd='/root')
print(r['stdout'][:200])
"

# Timeout works
python -c "
from forge.tools.shell import run_command
r = run_command('sleep 60', timeout=2)
print(r)  # should show timed_out: True
"

# Git tool works (in a git repo)
python -c "
from forge.tools.git import git_status
print(git_status('/root/Iris-Teams'))
"

# In TUI: /project /root/Iris-Teams → shows git status
# In TUI: /run pytest → runs tests
# Ask: 'what files changed recently?' → agent calls git_log automatically
```

---

## Layer 3 — Project Indexer (Semantic Codebase Search)

**Goal:** Forge reads your entire project, embeds key files, and can answer "where is X?" without you copying and pasting code.

### 3A — Indexer (`forge/memory/project_index.py`)

**What it does:**
1. Walks the project directory, skipping `node_modules`, `.venv`, `__pycache__`, `.git`, `dist`, `build`
2. Reads text files up to a size limit (skip binaries)
3. Chunks large files into overlapping windows (~500 tokens, 100-token overlap)
4. Embeds each chunk via hermes-router `/v1/embeddings`
5. Stores chunks as float32 BLOBs in SQLite (same pattern as Iris customer memory)

**Schema:**
```sql
CREATE TABLE project_chunks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_dir TEXT NOT NULL,
    file_path   TEXT NOT NULL,     -- relative to project_dir
    chunk_index INTEGER NOT NULL,  -- chunk number within file
    content     TEXT NOT NULL,     -- the actual code text
    embedding   BLOB,              -- float32 BLOB, 3072-dim
    indexed_at  TEXT NOT NULL
);
CREATE INDEX idx_project_dir ON project_chunks(project_dir);
```

**Key methods:**
```python
class ProjectIndex:
    def index(self, project_dir: str, force: bool = False) -> int:
        """Walk + chunk + embed the project. Returns chunk count."""

    def search(self, query: str, project_dir: str, k: int = 5) -> list[dict]:
        """Semantic search. Returns [{file_path, chunk_index, content, score}]"""

    def clear(self, project_dir: str) -> None:
        """Remove all chunks for a project (re-index from scratch)."""

    def stats(self, project_dir: str) -> dict:
        """Return {file_count, chunk_count, last_indexed}"""
```

### 3B — Chunking strategy

```python
_MAX_FILE_SIZE = 100_000   # bytes — skip files larger than this
_CHUNK_CHARS = 1500        # characters per chunk (roughly 375 tokens)
_OVERLAP_CHARS = 200       # overlap between consecutive chunks
_SKIP_DIRS = {'.git', '__pycache__', 'node_modules', '.venv', 'venv',
              'dist', 'build', '.next', 'target', '.mypy_cache', '.pytest_cache'}
_SKIP_EXTENSIONS = {'.pyc', '.pyo', '.so', '.dylib', '.dll', '.exe',
                    '.png', '.jpg', '.gif', '.mp4', '.zip', '.tar', '.gz',
                    '.lock', '.bin', '.db', '.sqlite'}

def _should_index(path: Path) -> bool:
    if path.suffix in _SKIP_EXTENSIONS: return False
    if path.stat().st_size > _MAX_FILE_SIZE: return False
    return True

def _chunk_text(text: str, file_path: str) -> list[str]:
    """Split text into overlapping chunks, prefixed with the file path."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + _CHUNK_CHARS
        chunk = f"# {file_path}\n{text[start:end]}"
        chunks.append(chunk)
        start += _CHUNK_CHARS - _OVERLAP_CHARS
    return chunks
```

### 3C — Search tool (`forge/tools/search.py`)

Wraps `ProjectIndex.search()` as an agent tool.

`search_codebase(query: str) -> str`
- Uses `config.project_dir` as the project
- Returns top-k chunks formatted as:
  ```
  [auth/middleware.py, chunk 2]
  def verify_token(token: str) -> bool:
      ...
  ```

### 3D — Incremental re-indexing

Don't re-embed unchanged files. Track a `file_hash` (SHA-256 of content) per file. On `index()`:
1. Compute hash of current file content
2. Check if any chunk exists with that file path + same hash
3. If match: skip re-embedding
4. If changed or new: delete old chunks for that file, embed new ones

Add `file_hash TEXT` column to `project_chunks`.

### 3E — TUI commands for L3

- `/index` — index the active project (shows progress: "Indexing 247 files...")
- `/index --force` — re-index everything even if hashes match
- `/search <query>` — directly call the search tool and print results

### 3F — Agent update for L3

Add `SearchCodebaseTool` to the agent's tool list.

Update system prompt when project is indexed:
```
Active project: /home/shafiq/myapp (Python/FastAPI)
Codebase indexed: 247 files, 1,832 chunks — use search_codebase() to find code.
```

The agent should call `search_codebase` before reading specific files when the user asks about a feature or bug — this avoids reading every file manually.

### 3G — Verification

```bash
# Index the Iris-Agent project (good test — real codebase)
python -c "
from forge.memory.project_index import ProjectIndex
idx = ProjectIndex('forge_memory.db')
n = idx.index('/root/Iris-Teams')
print(f'Indexed {n} chunks')
"

# Search works
python -c "
from forge.memory.project_index import ProjectIndex
idx = ProjectIndex('forge_memory.db')
results = idx.search('how are customer embeddings stored', '/root/Iris-Teams', k=3)
for r in results:
    print(r['file_path'], '---')
    print(r['content'][:200])
    print()
"

# In TUI:
# /project /root/Iris-Teams
# /index
# Ask: 'where is the duplicate question detection logic?'
# → agent calls search_codebase, finds customer.py, answers correctly
```

---

## Deferred (L4+)

- **Web dashboard** — port from Iris dashboard, adapt for single-user (no auth needed? or keep it)
- **Debug loop** — structured mode: paste error → Forge iterates until fixed
- **TDD loop** — write test → implement → run → repeat
- **Refactor mode** — Forge suggests improvements, you approve each
- **Multi-file edit** — Forge proposes changes across files, you review a diff before apply
- **GitHub integration** — PR review, issue triage

---

## Notes

- **Don't over-engineer L1.** The goal is a working TUI that talks to hermes-router and remembers things. Get that working first, then add tools.
- **Shell tool is L2's whole value.** If Forge can run `pytest` and see the output, it can debug. Everything else is nice-to-have.
- **The indexer is slow on first run** (embedding 1000 files = 1000 HTTP calls to hermes-router). The hash-based incremental update makes repeat runs fast. Show progress during initial index.
- **Embeddings are cached by hermes-router** for identical inputs — so if two projects share boilerplate files, the second index is faster.
- **DB file is `forge_memory.db`** — keep it separate from `iris_memory.db`.
