from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
from urllib.parse import urlparse

from .c_project import analyze_c_project

SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "build",
    ".venv",
    "venv",
}
KEY_FILES = [
    "README.md",
    "AGENTS.md",
    "pyproject.toml",
    "requirements.txt",
    "package.json",
    "vite.config.ts",
    "src",
    "app",
    "server.py",
    "engine.py",
]
MAX_TREE_ENTRIES = 120
MAX_FILE_CHARS = 2500
MAX_CODEGRAPH_CHARS = 8000


@dataclass(frozen=True)
class RepositoryInfo:
    input: str
    kind: str
    display_name: str
    summary: str


def inspect_repository(repo_input: str, base_dir: Path | None = None, query: str = "") -> RepositoryInfo:
    """Classify repository input as local path first, then remote repository address."""
    value = repo_input.strip()
    base = base_dir or Path.cwd()

    local_candidate = _resolve_local_candidate(value, base)
    if local_candidate and local_candidate.exists():
        return _inspect_local_path(value, local_candidate, query)

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


def _inspect_local_path(original: str, path: Path, query: str = "") -> RepositoryInfo:
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

    tree = _build_directory_tree(path)
    key_file_summaries = _read_key_files(path)
    c_project = analyze_c_project(path)
    codegraph_summary = _analyze_with_codegraph(path, query)
    summary_lines = [
        f"Repository input type: local_path",
        f"Resolved path: {path}",
        "Directory scan completed: yes",
        f"Looks like Git repository: {'yes' if is_git_repo else 'no'}",
        f"Top-level files: {files}",
        f"Top-level directories: {directories}",
        f"Detected project files: {', '.join(interesting) if interesting else 'None'}",
        "",
        "Directory tree snapshot:",
        tree or "(no readable entries)",
        "",
        "Key file excerpts:",
        key_file_summaries or "(no key files found or readable)",
    ]
    if c_project.detected:
        summary_lines.extend(["", c_project.summary])
    if codegraph_summary:
        summary_lines.extend(["", codegraph_summary])
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
        "Directory scan completed: no",
        "Reason: remote repository cloning is not enabled in this local prototype.",
        "Use a local repository path if you want actual directory scanning.",
    ]
    return RepositoryInfo(value, provider, display, "\n".join(summary_lines))


def _build_directory_tree(root: Path) -> str:
    lines: list[str] = []

    def walk(directory: Path, prefix: str = "", depth: int = 0) -> None:
        if len(lines) >= MAX_TREE_ENTRIES or depth > 3:
            return
        try:
            children = sorted(directory.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))
        except OSError:
            return

        visible_children = [
            child for child in children
            if not child.name.startswith(".") and child.name not in SKIP_DIRS
        ]
        for index, child in enumerate(visible_children):
            if len(lines) >= MAX_TREE_ENTRIES:
                lines.append("... (directory tree truncated)")
                return
            connector = "`-- " if index == len(visible_children) - 1 else "|-- "
            suffix = "/" if child.is_dir() else ""
            lines.append(f"{prefix}{connector}{child.name}{suffix}")
            if child.is_dir():
                extension = "    " if index == len(visible_children) - 1 else "|   "
                walk(child, prefix + extension, depth + 1)

    walk(root)
    return "\n".join(lines)


def _read_key_files(root: Path) -> str:
    snippets: list[str] = []
    candidates: list[Path] = []
    for name in KEY_FILES:
        path = root / name
        if path.is_file():
            candidates.append(path)
        elif path.is_dir():
            for child in sorted(path.iterdir(), key=lambda item: item.name.lower()):
                if child.is_file() and child.suffix.lower() in {".py", ".ts", ".tsx", ".js", ".md", ".json"}:
                    candidates.append(child)
                    break

    seen: set[Path] = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        relative = path.relative_to(root).as_posix()
        snippet = content[:MAX_FILE_CHARS]
        if len(content) > MAX_FILE_CHARS:
            snippet += "\n... (file excerpt truncated)"
        snippets.append(f"## {relative}\n```text\n{snippet}\n```")

    return "\n\n".join(snippets)


def _analyze_with_codegraph(root: Path, query: str) -> str:
    if os.getenv("CODEGRAPH_AUTO_INIT", "true").lower() not in {"1", "true", "yes", "on"}:
        return "CodeGraph analysis skipped: CODEGRAPH_AUTO_INIT is disabled."

    timeout = int(os.getenv("CODEGRAPH_TIMEOUT_SECONDS", "90"))
    lines = ["CodeGraph analysis:"]
    initialized = (root / ".codegraph").exists()

    if initialized:
        lines.append("CodeGraph index available before scan: yes")
    else:
        lines.append("CodeGraph index available before scan: no")
        init_result = _run_codegraph(["init", str(root)], root, timeout)
        lines.append("CodeGraph auto init attempted: yes")
        lines.append(_format_codegraph_result("init", init_result))
        initialized = (root / ".codegraph").exists() or init_result.returncode == 0

    if not initialized:
        lines.append("CodeGraph analysis available: no")
        return "\n".join(lines)

    status_result = _run_codegraph(["status", str(root)], root, timeout)
    files_result = _run_codegraph(["files"], root, timeout)
    explore_query = query.strip() or "project architecture entry points important modules"
    explore_result = _run_codegraph(["explore", explore_query], root, timeout)

    lines.append("CodeGraph analysis available: yes")
    lines.append(_format_codegraph_result("status", status_result))
    lines.append(_format_codegraph_result("files", files_result))
    lines.append(_format_codegraph_result("explore", explore_result))
    return "\n".join(lines)


def _run_codegraph(args: list[str], cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    command = ["cmd", "/c", "codegraph", *args] if os.name == "nt" else ["codegraph", *args]
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        return subprocess.CompletedProcess(command, 127, "", f"codegraph command not found: {exc}")
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        error = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
        return subprocess.CompletedProcess(command, 124, output, f"codegraph timed out after {timeout}s\n{error}")


def _format_codegraph_result(label: str, result: subprocess.CompletedProcess[str]) -> str:
    output = (result.stdout or "").strip()
    error = (result.stderr or "").strip()
    combined = output if result.returncode == 0 else "\n".join(part for part in [output, error] if part)
    if len(combined) > MAX_CODEGRAPH_CHARS:
        combined = combined[:MAX_CODEGRAPH_CHARS] + "\n... (CodeGraph output truncated)"
    return (
        f"## codegraph {label}\n"
        f"exit_code: {result.returncode}\n"
        f"```text\n{combined or '(no output)'}\n```"
    )
