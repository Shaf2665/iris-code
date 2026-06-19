# Iris Code (Forge)

A personal, developer-focused **coding agent** that runs in your terminal. It chats,
remembers your preferences across sessions, runs shell commands, inspects git, and
semantically searches your codebase — all through a local
[hermes-router](#hermes-router) instance that fans out to free LLM providers.

Iris Code is the single-developer sibling of Iris Teams. The defining difference: **Forge
can execute shell commands and index your codebase.**

## Features

- 🗣️ **Streaming TUI chat** over an OpenAI-compatible router (`prompt_toolkit` + `rich`)
- 🧠 **Persistent personal memory** — coding preferences, stack, project facts, recalled by semantic search
- 🐚 **Shell execution** — `run_command` / `run_tests` with a hard timeout, output truncation, and a destructive-command blocklist
- 🔀 **Git tools** — status, diff, log, blame
- 🔎 **Semantic codebase index** — walk → chunk → embed → search, with incremental SHA-256 re-indexing (unchanged files are skipped)
- 💾 **Named, resumable sessions** persisted to SQLite (WAL)

## Architecture

```
forge/
├── agent.py            # agentic loop (stateless per conversation; caller owns history)
├── llm.py              # hermes-router streaming client (OpenAI-compatible)
├── config.py           # Config dataclass: from_env() + JSON overlay
├── tui.py              # terminal UI + slash commands
├── memory/
│   ├── embedder.py     # hermes-router embeddings, stored as float32 BLOBs
│   ├── personal.py     # durable developer/project facts (semantic search)
│   ├── conversations.py# session persistence
│   └── project_index.py# semantic codebase index (incremental)
└── tools/
    ├── base.py         # tool registry
    ├── context.py      # shared runtime state (active project / index / timeout)
    ├── files.py        # read_file, write_file
    ├── shell.py        # run_command, run_tests
    ├── git.py          # git_status, git_diff, git_log, git_blame_line
    ├── search.py       # search_codebase
    └── web.py          # fetch_url (SSRF-guarded)
```

## Setup

Requires Python 3.11+ and a running hermes-router on `localhost:8319`.

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # edit if your router URL/key differ
python -m forge
```

### Configuration (`.env`)

| Var | Default | Meaning |
|---|---|---|
| `FORGE_ROUTER_URL` | `http://localhost:8319` | hermes-router base URL |
| `FORGE_API_KEY` | `sk-router-hermes-1` | router API key (local) |
| `FORGE_MODEL` | `hermes-router` | model / route name |
| `FORGE_DB_PATH` | `forge_memory.db` | SQLite store |
| `FORGE_PROJECT_DIR` | _(none)_ | default active project |
| `FORGE_SHELL_TIMEOUT` | `30` | shell command timeout (s) |

## Commands

```
/project <path>   set the active project        /memory          list saved facts
/run <cmd>        run a shell command            /forget          erase saved facts
/git              git status + recent log        /clear           clear session context
/index [--force]  (re)index for semantic search  /sessions        list saved sessions
/search <query>   semantic codebase search       /switch <name>   switch session
/help  /exit
```

## hermes-router

An OpenAI-API-compatible local router that auto-selects among free providers (Gemini,
OpenRouter, Cerebras, Groq, Mistral, ZAI, …) for chat, and Gemini for 3072-dim
embeddings. Point `FORGE_ROUTER_URL` at any OpenAI-compatible endpoint to use your own.

## Status

Layers L1–L3 are complete. Planned next (L4+): web dashboard, debug/TDD/refactor loops,
multi-file edits with diff review. See [`plan.md`](plan.md).

## License

MIT
