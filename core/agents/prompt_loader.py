from __future__ import annotations

from pathlib import Path


class AgentPromptLoader:
    def __init__(self, prompts_dir: Path | None = None) -> None:
        self.prompts_dir = prompts_dir or Path(__file__).parent / "prompts"

    def load(self, agent_name: str) -> str:
        filename = agent_name if agent_name.endswith(".md") else f"{agent_name}.md"
        path = self.prompts_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"agent prompt not found: {path}")
        return path.read_text(encoding="utf-8")
