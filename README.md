# Iris Code (Forge)

[![Build desktop apps](https://github.com/Shaf2665/iris-code/actions/workflows/build-desktop.yml/badge.svg)](https://github.com/Shaf2665/iris-code/actions/workflows/build-desktop.yml)
[![Latest release](https://img.shields.io/github/v/release/Shaf2665/iris-code?sort=semver)](https://github.com/Shaf2665/iris-code/releases/latest)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776ab.svg)

A personal, developer-focused **coding agent** for your terminal **and** desktop. It chats,
remembers your preferences across sessions, runs shell commands, inspects git, and
semantically searches your codebase — all through a local
[hermes-router](#hermes-router) instance that fans out to free LLM providers.

Iris Code is the single-developer sibling of Iris Teams. The defining difference: **Forge
can execute shell commands and index your codebase.**

![Iris Code desktop app](docs/screenshot.png)

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

## Desktop app (GUI)

Iris Code also ships a cross-platform **desktop GUI** (PySide6) for Linux, Windows,
and macOS — a windowed chat with the same forge backend, a project picker, a one-click
semantic indexer, a router health indicator, named sessions, and a settings panel for the
router URL / key / model.

Run it from source:

```bash
pip install -r requirements.txt -r requirements-gui.txt
python iris_code_gui.py          # launch the GUI
python iris_code_gui.py --selftest   # headless build check (no display/router)
```

### Building standalone installers

Packaging is per-OS (PyInstaller can't cross-compile), so installers are built by a
**GitHub Actions matrix** ([`.github/workflows/build-desktop.yml`](.github/workflows/build-desktop.yml)).
Push a tag to produce a release with all three:

```bash
git tag v0.1.0 && git push origin v0.1.0
```

| OS | Output | Build locally |
|---|---|---|
| Linux | `IrisCode` binary + `.tar.gz` | `bash scripts/build_linux.sh` |
| Windows | `IrisCode.exe` + Inno Setup installer | `scripts\build_windows.ps1` |
| macOS | `IrisCode.app` + `.dmg` | `bash scripts/build_macos.sh` |

The bundle is fully self-contained (Python + Qt included, ~95 MB on Linux); end users
just need a running hermes-router to point it at.

## hermes-router

An OpenAI-API-compatible local router that auto-selects among free providers (Gemini,
OpenRouter, Cerebras, Groq, Mistral, ZAI, …) for chat, and Gemini for 3072-dim
embeddings. Point `FORGE_ROUTER_URL` at any OpenAI-compatible endpoint to use your own.

## Status

Layers L1–L3 are complete. Planned next (L4+): web dashboard, debug/TDD/refactor loops,
multi-file edits with diff review. See [`plan.md`](plan.md).

## License

MIT
