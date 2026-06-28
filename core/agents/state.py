from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AgentThreadState:
    """Per-agent thread state placeholder.

    This is where future conversation history, tool traces, and runtime metadata can live.
    """

    agent_name: str
    messages: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
