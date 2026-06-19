"""Entry point for `python -m forge`.

    forge                 # default session
    forge -c <name>       # continue/start a named session
    forge -p <path>       # set the active project on launch
    forge sessions        # list saved sessions and exit
"""
import argparse
import sys

from .config import Config
from .tui import run_tui


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="forge", description="Iris Code — personal coding agent")
    parser.add_argument("command", nargs="?", help="optional: 'sessions' to list saved sessions")
    parser.add_argument("-c", "--continue", dest="session", default=None, help="named session to continue")
    parser.add_argument("-p", "--project", dest="project", default=None, help="active project directory")
    args = parser.parse_args(argv)

    config = Config.load()
    if args.project:
        config.project_dir = args.project

    if args.command == "sessions":
        from .memory.conversations import ConversationStore
        store = ConversationStore(config.db_path)
        sessions = store.list_sessions()
        if not sessions:
            print("No saved sessions.")
        for conv_id, updated_at, count in sessions:
            label = conv_id[8:] if conv_id.startswith("session:") else conv_id
            print(f"{label:<25} {count} exchanges   last: {updated_at[:10] or 'unknown'}")
        store.close()
        return

    run_tui(config, session_id=args.session)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
