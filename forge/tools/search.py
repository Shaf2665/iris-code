"""
Codebase search tool — wraps ProjectIndex.search() for the agent.

The active project dir and the shared ProjectIndex live in tools.context; the
Agent sets them. If the project hasn't been indexed, the tool says so rather
than failing silently, so the model knows to suggest /index.
"""
from .base import ToolDefinition, register
from . import context

_MAX_CHUNK_CHARS = 1200


def search_codebase(query: str, k: int = 5) -> str:
    index = context.get_index()
    project_dir = context.get_project_dir()
    if not project_dir:
        return "Error: no active project. Set one with /project <path> first."
    if index is None:
        return "Error: project index unavailable."
    try:
        k = int(k)
    except (TypeError, ValueError):
        k = 5

    results = index.search(query, project_dir, k=k)
    if not results:
        stats = index.stats(project_dir)
        if stats["chunk_count"] == 0:
            return ("No index for this project yet. Ask the developer to run /index, "
                    "or read files directly with read_file.")
        return f"No matching code found for: {query!r}"

    out = []
    for r in results:
        content = r["content"]
        if len(content) > _MAX_CHUNK_CHARS:
            content = content[:_MAX_CHUNK_CHARS] + "\n...[truncated]..."
        out.append(
            f"[{r['file_path']}, chunk {r['chunk_index']}, score {r['score']}]\n{content}"
        )
    return "\n\n".join(out)


register(ToolDefinition(
    name="search_codebase",
    description=(
        "Semantic search over the indexed project. Returns the most relevant code "
        "chunks with their file paths. Prefer this over reading files one-by-one when "
        "looking for where a feature, function, or behaviour lives."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to look for (natural language or code)."},
            "k": {"type": "integer", "description": "Number of chunks to return (default 5)."},
        },
        "required": ["query"],
    },
    fn=search_codebase,
))
