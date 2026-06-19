"""Importing this package registers every tool into TOOL_REGISTRY.

Order doesn't matter — each module calls register() at import time. The Agent
imports this package once so the schema is complete before the first LLM call.
"""
from . import files   # noqa: F401  read_file, write_file
from . import web     # noqa: F401  fetch_url
from . import shell   # noqa: F401  run_command, run_tests   (L2)
from . import git     # noqa: F401  git_status, git_diff, git_log, git_blame_line  (L2)
from . import search  # noqa: F401  search_codebase  (L3)
