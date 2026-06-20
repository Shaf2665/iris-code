"""Iris Code desktop GUI — a PySide6 front-end over the forge backend.

Reuses forge.config.Config and forge.agent.Agent verbatim; the GUI only adds a
windowed chat experience, a project picker, an indexer button, and a settings
panel. The agent still talks to a local hermes-router (default localhost:8319).
"""

__version__ = "0.1.0"
