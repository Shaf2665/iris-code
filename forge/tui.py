import os

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.styles import Style
from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.spinner import Spinner
from rich.text import Text

from .agent import Agent, detect_stack
from .config import Config
from .memory.conversations import ConversationStore
from .tools.git import project_git_summary

_DEFAULT_SESSION = "tui_dev"

_BANNER = """\
  ███████╗ ██████╗ ██████╗  ██████╗ ███████╗
  ██╔════╝██╔═══██╗██╔══██╗██╔════╝ ██╔════╝
  █████╗  ██║   ██║██████╔╝██║  ███╗█████╗
  ██╔══╝  ██║   ██║██╔══██╗██║   ██║██╔══╝
  ██║     ╚██████╔╝██║  ██║╚██████╔╝███████╗
  ╚═╝      ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚══════╝"""

# Gradient: ember orange → cyan → indigo. Forge = fire + steel.
_GRADIENT_STOPS = [
    (255, 138, 76),   # ember orange
    (79, 195, 247),   # sky cyan
    (26, 35, 126),    # deep indigo
]
_ACCENT = "#ff8a4c"
_BORDER = "#b5532a"

_PROMPT_STYLE = Style.from_dict({
    "": "#00bcd4",
    "prompt": "#00bcd4 bold",
})


def _gradient_color(t: float) -> tuple[int, int, int]:
    stops = _GRADIENT_STOPS
    if t <= 0:
        return stops[0]
    if t >= 1:
        return stops[-1]
    seg = t * (len(stops) - 1)
    i = min(int(seg), len(stops) - 2)
    local = seg - i
    c0, c1 = stops[i], stops[i + 1]
    return tuple(int(c0[j] + (c1[j] - c0[j]) * local) for j in range(3))


def _banner_text() -> Text:
    lines = _BANNER.split("\n")
    n = len(lines) - 1
    text = Text()
    for i, line in enumerate(lines):
        t = i / n if n > 0 else 0
        r, g, b = _gradient_color(t)
        text.append(line + "\n", style=f"bold #{r:02x}{g:02x}{b:02x}")
    text.append("      ✦ ", style=f"bold {_ACCENT}")
    text.append("I R I S   C O D E", style=f"bold {_ACCENT}")
    text.append(" ✦", style=f"bold {_ACCENT}")
    return text


def _project_label(config: Config) -> str:
    if not config.project_dir:
        return "[dim]no project set — use /project <path>[/dim]"
    stack = detect_stack(config.project_dir)
    suffix = f" [dim]({stack})[/dim]" if stack else ""
    return f"[cyan]{config.project_dir}[/cyan]{suffix}"


def _print_header(console: Console, config: Config, session_label: str = "") -> None:
    console.print(Panel(
        _banner_text(),
        border_style=_BORDER,
        padding=(0, 2),
        subtitle=f"[{_ACCENT}]Personal Coding Agent[/{_ACCENT}]",
        subtitle_align="right",
    ))
    console.print("[dim]Personal coding assistant  •  Iris Code  •  hermes-router[/dim]")
    console.print(f"[dim cyan]Project:[/dim cyan] {_project_label(config)}")
    if session_label:
        console.print(f"[dim cyan]Session:[/dim cyan] [cyan]{session_label}[/cyan]")
    console.print("[dim]Commands: /help  /project  /index  /run  /git  /memory  /exit[/dim]\n")


def _format_session_id(conv_id: str) -> str:
    if conv_id == _DEFAULT_SESSION:
        return "default"
    if conv_id.startswith("session:"):
        return conv_id[8:]
    return conv_id


_FORGE_LABEL = Text("Forge:", style=f"bold {_ACCENT}")


def _stream_response(console: Console, agent: Agent, history: list[dict], user_input: str) -> None:
    console.print()
    accumulated = ""
    error: Exception | None = None
    spinner = Spinner("dots", text=Text(" Forge is working...", style="dim cyan"))

    with Live(spinner, console=console, refresh_per_second=12, transient=True,
              vertical_overflow="visible") as live:
        def on_tool_status(msg: str) -> None:
            live.console.print(msg.lstrip("\n"))

        try:
            for token in agent.chat(user_input, history, on_tool_status=on_tool_status):
                accumulated += token
                if accumulated.strip():
                    live.update(Group(_FORGE_LABEL, Markdown(accumulated)))
        except Exception as e:
            error = e

    if error is not None:
        console.print(f"[red]Error: {error}[/red]\n")
    elif accumulated.strip():
        console.print(_FORGE_LABEL)
        console.print(Markdown(accumulated))
        console.print()
    else:
        console.print()


def _cmd_help(console: Console) -> None:
    console.print(Panel(
        Text.from_markup(
            f"[bold {_ACCENT}]Iris Code[/bold {_ACCENT}] [bold cyan]— Terminal Commands[/bold cyan]\n\n"
            "[bold]Chat & memory[/bold]\n"
            "  [cyan]/memory[/cyan]          List saved facts about you and your projects\n"
            "  [cyan]/forget[/cyan]          Erase all saved facts (asks confirmation)\n"
            "  [cyan]/clear[/cyan]           Clear this session's context\n"
            "  [cyan]/sessions[/cyan]        List saved chat sessions\n"
            "  [cyan]/switch <name>[/cyan]   Switch to a different named session\n\n"
            "[bold]Project & tools[/bold]\n"
            "  [cyan]/project <path>[/cyan]  Set the active project directory\n"
            "  [cyan]/run <cmd>[/cyan]       Run a shell command in the project\n"
            "  [cyan]/git[/cyan]             Show git status + recent log\n"
            "  [cyan]/index[/cyan]           Index the project for semantic search\n"
            "  [cyan]/index --force[/cyan]   Re-index everything from scratch\n"
            "  [cyan]/search <query>[/cyan]  Semantic search across the codebase\n\n"
            "  [cyan]/help[/cyan]            Show this help\n"
            "  [cyan]/exit[/cyan]            Quit  (session saved automatically)"
        ),
        border_style="#1e3a5f",
        padding=(0, 2),
    ))


def _cmd_memory(console: Console, agent: Agent) -> None:
    facts = agent.list_facts()
    if not facts:
        console.print("[dim]No facts saved yet.[/dim]\n")
        return
    console.print(f"[bold {_ACCENT}]Forge Memory[/bold {_ACCENT}] [dim]({len(facts)} facts)[/dim]")
    console.print("─" * 40)
    for i, (_fid, fact) in enumerate(facts, 1):
        console.print(f"  [cyan]{i}.[/cyan] {fact}")
    console.print()


def _cmd_sessions(console: Console, store: ConversationStore) -> None:
    sessions = store.list_sessions()
    if not sessions:
        console.print("[dim]No saved sessions.[/dim]\n")
        return
    console.print(f"[bold cyan]Saved Sessions[/bold cyan] [dim]({len(sessions)})[/dim]")
    console.print("─" * 50)
    for conv_id, updated_at, count in sessions:
        label = _format_session_id(conv_id)
        date = updated_at[:10] if updated_at else "unknown"
        console.print(f"  [cyan]{label:<25}[/cyan] {count} exchanges  [dim]last: {date}[/dim]")
    console.print()


def _cmd_project(console: Console, agent: Agent, config: Config, path: str) -> None:
    if not path:
        console.print(f"[red]Usage: /project <path>[/red]\n")
        return
    expanded = os.path.expanduser(path)
    if not os.path.isdir(expanded):
        console.print(f"[red]Not a directory: {path}[/red]\n")
        return
    resolved = agent.set_project(expanded)
    stack = detect_stack(resolved)
    console.print(f"[green]Active project:[/green] {resolved}" + (f" [dim]({stack})[/dim]" if stack else ""))
    stats = agent.index.stats(resolved)
    if stats["chunk_count"]:
        console.print(f"[dim]Indexed: {stats['file_count']} files, {stats['chunk_count']} chunks.[/dim]")
    else:
        console.print("[dim]Not indexed yet — run /index for semantic search.[/dim]")
    if os.path.isdir(os.path.join(resolved, ".git")):
        console.print("\n" + project_git_summary(resolved))
    console.print()


def _cmd_run(console: Console, config: Config, cmd: str) -> None:
    if not cmd:
        console.print("[red]Usage: /run <command>[/red]\n")
        return
    from .tools.shell import run_command
    console.print(f"[dim]$ {cmd}[/dim]")
    console.print(run_command(cmd))
    console.print()


def _cmd_git(console: Console, config: Config) -> None:
    if not config.project_dir:
        console.print("[red]No project set — use /project <path> first.[/red]\n")
        return
    if not os.path.isdir(os.path.join(config.project_dir, ".git")):
        console.print(f"[yellow]{config.project_dir} is not a git repository.[/yellow]\n")
        return
    console.print(project_git_summary(config.project_dir))
    console.print()


def _cmd_index(console: Console, agent: Agent, config: Config, force: bool) -> None:
    if not config.project_dir:
        console.print("[red]No project set — use /project <path> first.[/red]\n")
        return
    console.print(f"[dim]Indexing {config.project_dir}{' (force)' if force else ''}...[/dim]")
    try:
        n = agent.index.index(config.project_dir, force=force, on_progress=lambda m: console.print(f"[dim]{m}[/dim]"))
    except Exception as e:
        console.print(f"[red]Index failed: {e}[/red]\n")
        return
    stats = agent.index.stats(config.project_dir)
    console.print(f"[green]Indexed[/green] — {stats['file_count']} files, {stats['chunk_count']} chunks "
                  f"({n} embedded this run).\n")


def _cmd_search(console: Console, agent: Agent, config: Config, query: str) -> None:
    if not config.project_dir:
        console.print("[red]No project set — use /project <path> first.[/red]\n")
        return
    if not query:
        console.print("[red]Usage: /search <query>[/red]\n")
        return
    results = agent.index.search(query, config.project_dir, k=5)
    if not results:
        console.print("[dim]No matches (is the project indexed? run /index).[/dim]\n")
        return
    for r in results:
        console.print(f"[bold cyan]{r['file_path']}[/bold cyan] [dim]chunk {r['chunk_index']} · score {r['score']}[/dim]")
        snippet = r["content"][:400]
        console.print(f"[dim]{snippet}[/dim]")
        console.print()


def run_tui(config: Config, session_id: str | None = None) -> None:
    conv_id = f"session:{session_id}" if session_id else _DEFAULT_SESSION
    session_label = session_id if session_id else "default"

    console = Console()
    agent = Agent(config)
    store = ConversationStore(config.db_path)
    history: list[dict] = store.load(conv_id)
    prompt_session = PromptSession(history=InMemoryHistory(), style=_PROMPT_STYLE)

    store.save(conv_id, history)

    console.clear()
    _print_header(console, config, session_label)
    if history:
        n = sum(1 for m in history if m.get("role") == "user")
        console.print(f"[dim]Resuming '{session_label}' — {n} previous exchange(s). /clear to start fresh.[/dim]\n")

    try:
        while True:
            try:
                user_input = prompt_session.prompt([("class:prompt", "You: ")]).strip()
            except KeyboardInterrupt:
                console.print("\n[dim]Interrupted. Type /exit to quit.[/dim]")
                continue
            except EOFError:
                console.print("\n[dim]Goodbye.[/dim]")
                break

            if not user_input:
                continue

            cmd = user_input.lower()

            if cmd == "/exit":
                console.print("[dim]Goodbye.[/dim]")
                break

            if cmd == "/help":
                _cmd_help(console)
                continue

            if cmd == "/clear":
                history.clear()
                store.delete(conv_id)
                console.clear()
                _print_header(console, config, session_label)
                console.print("[green]Session cleared.[/green]\n")
                continue

            if cmd in ("/memory", "/history"):
                _cmd_memory(console, agent)
                continue

            if cmd == "/forget":
                console.print("[yellow]Erase ALL saved facts? (yes/no)[/yellow] ", end="")
                try:
                    confirm = prompt_session.prompt("").strip().lower()
                except (KeyboardInterrupt, EOFError):
                    confirm = "no"
                if confirm in ("yes", "y"):
                    agent.forget_all()
                    console.print("[green]All facts erased.[/green]\n")
                else:
                    console.print("[dim]Cancelled.[/dim]\n")
                continue

            if cmd == "/sessions":
                _cmd_sessions(console, store)
                continue

            if cmd.startswith("/switch "):
                new_name = user_input[8:].strip()
                if not new_name:
                    console.print("[red]Usage: /switch <session-name>[/red]\n")
                    continue
                store.save(conv_id, history)
                conv_id = f"session:{new_name}"
                session_label = new_name
                history.clear()
                history.extend(store.load(conv_id))
                store.save(conv_id, history)
                n = sum(1 for m in history if m.get("role") == "user")
                console.clear()
                _print_header(console, config, session_label)
                msg = f"Switched to '{new_name}' — {n} previous exchange(s)." if history else f"Started new session '{new_name}'."
                console.print(f"[dim]{msg}[/dim]\n")
                continue

            if cmd.startswith("/project"):
                _cmd_project(console, agent, config, user_input[8:].strip())
                continue

            if cmd.startswith("/run "):
                _cmd_run(console, config, user_input[5:].strip())
                continue

            if cmd == "/git":
                _cmd_git(console, config)
                continue

            if cmd.startswith("/index"):
                force = "--force" in user_input
                _cmd_index(console, agent, config, force)
                continue

            if cmd.startswith("/search "):
                _cmd_search(console, agent, config, user_input[8:].strip())
                continue

            if user_input.startswith("/"):
                console.print(f"[red]Unknown command:[/red] {user_input}  — type /help for a list\n")
                continue

            _stream_response(console, agent, history, user_input)
            store.save(conv_id, history)

    finally:
        agent.close()
        store.close()
