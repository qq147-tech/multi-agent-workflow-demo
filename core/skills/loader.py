from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


RESOURCE_SUFFIXES = {
    ".md",
    ".txt",
    ".py",
    ".html",
    ".htm",
    ".css",
    ".js",
    ".cjs",
    ".mjs",
    ".ts",
    ".tsx",
    ".sh",
    ".bash",
    ".ps1",
    ".bat",
    ".cmd",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".template",
    ".jinja",
    ".j2",
}
MAX_RESOURCE_CHARS = 50_000
MAX_RESOURCE_TOTAL_CHARS = 150_000


@dataclass
class Skill:
    name: str
    path: Path
    content: str


class SkillLoader:
    """Loads SKILL.md files from a skills directory."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def list_skills(self) -> list[Skill]:
        skills: list[Skill] = []
        for path in self.root.glob("*/SKILL.md"):
            skills.append(Skill(path.parent.name, path, path.read_text(encoding="utf-8")))
        return skills

    def load_many(self, names: list[str]) -> str:
        chunks: list[str] = []
        for name in names:
            path = self.root / name / "SKILL.md"
            if not path.exists():
                raise FileNotFoundError(f"skill not found: {path}")
            chunks.append(f"# Skill: {name}\n\n{path.read_text(encoding='utf-8')}{self._load_resources(path.parent)}")
        return "\n\n---\n\n".join(chunks)

    def _load_resources(self, skill_dir: Path) -> str:
        resources: list[str] = []
        total_chars = 0
        for path in sorted(skill_dir.rglob("*")):
            if not path.is_file() or path.name == "SKILL.md":
                continue
            if path.suffix.lower() not in RESOURCE_SUFFIXES and path.name != "requirements.txt":
                continue
            relative = path.relative_to(skill_dir).as_posix()
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if len(content) > MAX_RESOURCE_CHARS:
                content = content[:MAX_RESOURCE_CHARS] + "\n\n[truncated]"
            total_chars += len(content)
            if total_chars > MAX_RESOURCE_TOTAL_CHARS:
                resources.append("\n\n[additional skill resources truncated]")
                break
            resources.append(f"## Resource: {relative}\n\n```text\n{content}\n```")

        if not resources:
            return ""
        return "\n\n# Skill Resources\n\n" + "\n\n".join(resources)
