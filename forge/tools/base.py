from dataclasses import dataclass
from typing import Callable


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict
    fn: Callable[..., str]


TOOL_REGISTRY: dict[str, "ToolDefinition"] = {}


def register(tool: ToolDefinition) -> None:
    TOOL_REGISTRY[tool.name] = tool


def get_tools_schema() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in TOOL_REGISTRY.values()
    ]
