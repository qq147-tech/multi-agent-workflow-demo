from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SubagentDelegator:
    """Tracks sub-agent delegation requests."""

    assignments: list[dict] = field(default_factory=list)

    def assign(self, parent: str, child: str, task: str) -> None:
        self.assignments.append({"parent": parent, "child": child, "task": task})
