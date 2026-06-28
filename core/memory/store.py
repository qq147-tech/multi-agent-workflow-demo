from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MemoryStore:
    """Long-term memory and fact store placeholder."""

    facts: dict[str, str] = field(default_factory=dict)

    def remember(self, key: str, value: str) -> None:
        self.facts[key] = value

    def recall(self, key: str, default: str = "") -> str:
        return self.facts.get(key, default)
