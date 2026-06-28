from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MCPClientRegistry:
    """Placeholder registry for Model Context Protocol servers."""

    servers: dict[str, str] = field(default_factory=dict)

    def add_server(self, name: str, command_or_url: str) -> None:
        self.servers[name] = command_or_url
