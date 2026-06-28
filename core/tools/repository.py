from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class RepositoryInfo:
    input: str
    kind: str
    display_name: str
    summary: str


def inspect_repository(repo_input: str, base_dir: Path | None = None) -> RepositoryInfo:
    """Classify repository input as local path first, then remote repository address."""
    value = repo_input.strip()
    base = base_dir or Path.cwd()

    local_candidate = _resolve_local_candidate(value, base)
    if local_candidate and local_candidate.exists():
        return _inspect_local_path(value, local_candidate)

    return _inspect_remote_address(value)


def _resolve_local_candidate(value: str, base: Path) -> Path | None:
    if not value:
        return None

    parsed = urlparse(value)
    if parsed.scheme in {"http", "https", "ssh", "git"}:
        return None

    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def _inspect_local_path(original: str, path: Path) -> RepositoryInfo:
    if path.is_file():
        summary = f"Local path exists but is a file, not a repository directory: {path}"
        return RepositoryInfo(original, "local_file", path.name, summary)

    entries = list(path.iterdir())
    files = sum(1 for entry in entries if entry.is_file())
    directories = sum(1 for entry in entries if entry.is_dir())
    is_git_repo = (path / ".git").exists()

    interesting = []
    for name in ["pyproject.toml", "package.json", "requirements.txt", "README.md", "AGENTS.md"]:
        if (path / name).exists():
            interesting.append(name)

    summary_lines = [
        f"Repository input type: local_path",
        f"Resolved path: {path}",
        f"Looks like Git repository: {'yes' if is_git_repo else 'no'}",
        f"Top-level files: {files}",
        f"Top-level directories: {directories}",
        f"Detected project files: {', '.join(interesting) if interesting else 'None'}",
    ]
    return RepositoryInfo(original, "local_path", path.name, "\n".join(summary_lines))


def _inspect_remote_address(value: str) -> RepositoryInfo:
    parsed = urlparse(value)
    host = parsed.netloc.lower()
    path = parsed.path.strip("/")

    if value.startswith("git@"):
        provider = "ssh_git"
        display = value.rsplit("/", 1)[-1].removesuffix(".git")
    elif "github.com" in host:
        provider = "github"
        display = path.rsplit("/", 1)[-1].removesuffix(".git") if path else value
    elif "gitlab.com" in host:
        provider = "gitlab"
        display = path.rsplit("/", 1)[-1].removesuffix(".git") if path else value
    elif "gitee.com" in host:
        provider = "gitee"
        display = path.rsplit("/", 1)[-1].removesuffix(".git") if path else value
    elif parsed.scheme in {"http", "https", "ssh", "git"}:
        provider = "remote_git"
        display = path.rsplit("/", 1)[-1].removesuffix(".git") if path else value
    else:
        provider = "unknown"
        display = value or "repository"

    summary_lines = [
        f"Repository input type: {provider}",
        f"Original address: {value}",
        "Local path was checked first and did not exist.",
        "Current prototype does not clone remote repositories yet.",
        "Next integration: validate remote address, clone into a sandbox, then analyze files.",
    ]
    return RepositoryInfo(value, provider, display, "\n".join(summary_lines))
