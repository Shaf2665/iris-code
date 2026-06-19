# Iris Code — Personal Coding Agent

## What This Project Is

Iris Code is a **personal, developer-focused coding assistant** built on hermes-router.
It is a sibling project to Iris Teams (`/root/Iris-Teams`) but serves a completely different
purpose: instead of org-level customer support, it is a local tool for a single developer
— helping with code, running commands, understanding codebases, and remembering your
preferences across projects.

**Key difference from Iris Teams:** Iris Code can execute shell commands and index codebases.
Iris Teams cannot (too risky for customer-facing use). Iris Code is personal, so it's trusted.

---

## hermes-router Reference

Everything runs through the local hermes-router instance. It is OpenAI-API-compatible.

| Setting | Value |
|---|---|
| Base URL | `http://localhost:8319/v1` |
| API Key | `sk-router-hermes-1` |
| Default model | `hermes-router` (auto-routes to best free provider) |
| Coding model | `gpt-5.3-codex` via `openai-codex` provider |
| Embeddings | `/v1/embeddings` → Gemini `gemini-embedding-001`, 3072-dim, cached |

### Providers (free, auto-selected by router)
- **Gemini** (primary, round-robin across multiple keys)
- **OpenRouter** — `nvidia/nemotron-3-super-120b-a12b:free`
- **Cerebras** — `gpt-oss-120b` (fast inference)
- **Groq** — `llama-3.1-8b-instant` (very fast, fallback)
- **Mistral** — `mistral-small-latest`
- **ZAI** — `glm-4.5-flash`
- **openai-codex** — `gpt-5.3-codex` (coding-optimized)

### Key endpoints
```
POST /v1/chat/completions    # streaming chat, OpenAI-compatible
POST /v1/embeddings          # 3072-dim float32, identical requests are cached
GET  /health                 # returns 200 if router is up
```

### Embeddings — storage format
Vectors are stored as **float32 BLOB** (4 bytes/dim = 12 KB per 3072-dim vector).
See `/root/Iris-Teams/iris/memory/embedder.py` for the reference implementation —
copy it verbatim into `forge/memory/embedder.py`, it is already production-hardened.

```python
# pack/unpack pattern (copy from Iris Teams)
def pack(vec) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()

def unpack(stored) -> np.ndarray | None:
    if stored is None: return None
    if isinstance(stored, (bytes, bytearray)):
        return np.frombuffer(stored, dtype=np.float32)
    try: return np.asarray(json.loads(stored), dtype=np.float32)  # legacy
    except Exception: return None
```

---

## Iris Teams Reference (reuse, don't reinvent)

**Location:** `/root/Iris-Teams`
**venv:** `/root/Iris-Teams/.venv` (Python 3.11, uv-managed)

### Modules to copy/adapt directly
| Iris Teams file | Forge equivalent | Changes needed |
|---|---|---|
| `iris/llm.py` | `forge/llm.py` | None — identical |
| `iris/config.py` | `forge/config.py` | Remove Discord/dashboard fields; add `project_dir`, `shell_timeout` |
| `iris/tui.py` | `forge/tui.py` | Add `/project`, `/index`, `/git` commands |
| `iris/agent.py` | `forge/agent.py` | Remove customer/channel/org logic; add shell tool routing |
| `iris/memory/embedder.py` | `forge/memory/embedder.py` | Copy verbatim |
| `iris/memory/conversations.py` | `forge/memory/conversations.py` | Copy verbatim |
| `iris/tools/files.py` | `forge/tools/files.py` | Copy verbatim |
| `iris/tools/web.py` | `forge/tools/web.py` | Copy verbatim |

### What NOT to copy
- `iris/discord_bot.py` — no Discord in Iris Code
- `iris/dashboard/` — no web dashboard in L1–L3
- `iris/memory/customer.py` — no customer tracking
- `iris/memory/owner.py` → replace with simpler `forge/memory/personal.py`
- `iris/memory/discord_cache.py` — not needed

### Iris Teams conventions to follow
- **SQLite + WAL + threading.Lock** for all DB access (bot + dashboard may share)
- **`check_same_thread=False, timeout=5.0`** on all `sqlite3.connect()` calls
- **uv** for package installs: `VIRTUAL_ENV=/root/Iris-Code/.venv /root/.hermes/bin/uv pip install <pkg>`
- Never use `pip uninstall` on uv-managed packages — delete site-packages dirs directly if needed
- `reasoning_effort: none` equivalent → don't pass `max_tokens` unless necessary
- Stream LLM responses; accumulate tool call chunks by index

---

## Development Environment

```bash
# Create venv
VIRTUAL_ENV=/root/Iris-Code/.venv /root/.hermes/bin/uv venv --python 3.11 /root/Iris-Code/.venv

# Install packages
VIRTUAL_ENV=/root/Iris-Code/.venv /root/.hermes/bin/uv pip install <pkg>

# Run (once main.py exists)
/root/Iris-Code/.venv/bin/python -m forge
# or via CLI entry:
/usr/local/bin/forge
```

### .env file (create at /root/Iris-Code/.env)
```
FORGE_ROUTER_URL=http://localhost:8319
FORGE_API_KEY=sk-router-hermes-1
FORGE_PROJECT_DIR=        # optional default project dir
FORGE_SHELL_TIMEOUT=30    # seconds for shell command timeout
```

---

## Planned Build Layers

See `plan.md` for the full L1–L3 plan. Summary:

| Layer | What |
|---|---|
| L1 | TUI chat loop + hermes-router + personal memory |
| L2 | Shell execution tool + git tool |
| L3 | Project indexer (semantic codebase search via embeddings) |
| L4 (future) | Web dashboard (port ideas from Iris dashboard) |
| L5 (future) | Coding workflows: debug loop, TDD loop, refactor mode |

---

## Repo Structure (target after L1–L3)

```
Iris Code/
├── forge/
│   ├── __init__.py
│   ├── agent.py          # core agent loop (stateless, caller owns history)
│   ├── llm.py            # hermes-router streaming client
│   ├── config.py         # Config dataclass, from_env() + JSON overlay
│   ├── tui.py            # prompt_toolkit TUI
│   ├── memory/
│   │   ├── __init__.py
│   │   ├── embedder.py   # hermes-router embeddings (copy from Iris)
│   │   ├── conversations.py  # session persistence (copy from Iris)
│   │   └── personal.py   # personal facts (coding prefs, stack, projects)
│   └── tools/
│       ├── __init__.py
│       ├── base.py        # Tool base class (copy from Iris)
│       ├── files.py       # read_file, write_file (copy from Iris)
│       ├── shell.py       # NEW: run_command, run_python, run_tests
│       ├── git.py         # NEW: git_status, git_diff, git_log
│       └── web.py         # fetch_url (copy from Iris)
├── main.py
├── requirements.txt
├── .env                  # (gitignore this)
├── .env.example
├── CLAUDE.md             # this file
└── plan.md               # L1–L3 implementation plan
```

---

## Important Notes for New Sessions

1. **hermes-router must be running** — check with `systemctl is-active hermes-router` or `curl http://localhost:8319/health`
2. **Iris Teams is a reference, not a dependency** — copy files, don't import across repos
3. **Shell tool is the key differentiator** — implement it carefully with a timeout, working directory tracking, and output truncation for large outputs
4. **No customer-facing features** — Iris Code is single-user, no auth, no support mode
5. **DB file**: `forge_memory.db` in the project root (separate from `iris_memory.db`)
6. **CLI entry point**: `/usr/local/bin/forge` (create after L1 is working)
