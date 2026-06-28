from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class ToolRegistry:
    """Registry for built-in tools, MCP tools, and skill-management tools."""

    tools: dict[str, Callable] = field(default_factory=dict)

    def register(self, name: str, tool: Callable) -> None:
        self.tools[name] = tool

    def get(self, name: str) -> Callable:
        if name not in self.tools:
            raise KeyError(f"tool not registered: {name}")
        return self.tools[name]
