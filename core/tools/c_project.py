from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
import re


C_SOURCE_SUFFIXES = {".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hh", ".hxx"}
BUILD_FILES = {
    "CMakeLists.txt",
    "Makefile",
    "makefile",
    "Kconfig",
    "meson.build",
    "configure.ac",
    "config.mk",
}
SKIP_DIRS = {
    ".git",
    "build",
    "dist",
    "out",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
}
MAX_C_FILES = 500
MAX_SYMBOL_FILES = 80
MAX_SYMBOLS = 160


@dataclass(frozen=True)
class CProjectAnalysis:
    detected: bool
    summary: str


def analyze_c_project(root: Path) -> CProjectAnalysis:
    build_files = _find_build_files(root)
    c_files = _find_c_files(root)
    if not build_files and not c_files:
        return CProjectAnalysis(False, "")

    module_counts = _module_counts(root, c_files)
    include_counter: Counter[str] = Counter()
    macro_counter: Counter[str] = Counter()
    symbols: list[str] = []
    structs: list[str] = []

    for path in c_files[:MAX_SYMBOL_FILES]:
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        relative = path.relative_to(root).as_posix()
        include_counter.update(_extract_includes(content))
        macro_counter.update(_extract_macros(content))
        for name in _extract_functions(content):
            if len(symbols) >= MAX_SYMBOLS:
                break
            symbols.append(f"{name} ({relative})")
        for name in _extract_structs(content):
            if len(structs) >= MAX_SYMBOLS:
                break
            structs.append(f"{name} ({relative})")

    lines = [
        "C/C++ project analysis:",
        f"Detected C/C++ project: yes",
        f"C/C++ source/header files found: {len(c_files)}",
        f"Build/config files: {', '.join(path.relative_to(root).as_posix() for path in build_files) if build_files else 'None found'}",
        "",
        "Top modules by C/C++ file count:",
        _format_counter(module_counts, limit=20),
        "",
        "Most common includes:",
        _format_counter(include_counter, limit=25),
        "",
        "Detected macros:",
        _format_counter(macro_counter, limit=25),
        "",
        "Detected functions/sample definitions:",
        "\n".join(f"- {item}" for item in symbols[:80]) or "(none detected)",
        "",
        "Detected structs/classes/sample types:",
        "\n".join(f"- {item}" for item in structs[:80]) or "(none detected)",
        "",
        "C/C++ analysis notes:",
        "- This is a static lightweight scan, not a full compiler-aware clang analysis.",
        "- Macro expansion, conditional compilation, generated headers, and target-specific build flags may affect the true call graph.",
        "- For high-risk changes, inspect relevant Makefile/CMake include paths and target-specific macros before implementation.",
    ]
    return CProjectAnalysis(True, "\n".join(lines))


def _find_build_files(root: Path) -> list[Path]:
    found: list[Path] = []
    for path in _walk_files(root, limit=1200):
        if path.name in BUILD_FILES:
            found.append(path)
    return found[:40]


def _find_c_files(root: Path) -> list[Path]:
    return [
        path for path in _walk_files(root, limit=MAX_C_FILES * 4)
        if path.suffix.lower() in C_SOURCE_SUFFIXES
    ][:MAX_C_FILES]


def _walk_files(root: Path, limit: int) -> list[Path]:
    files: list[Path] = []
    stack = [root]
    while stack and len(files) < limit:
        directory = stack.pop()
        try:
            children = sorted(directory.iterdir(), key=lambda item: item.name.lower(), reverse=True)
        except OSError:
            continue
        for child in children:
            if child.is_dir():
                if child.name not in SKIP_DIRS and not child.name.startswith("."):
                    stack.append(child)
            elif child.is_file():
                files.append(child)
                if len(files) >= limit:
                    break
    return files


def _module_counts(root: Path, files: list[Path]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for path in files:
        relative = path.relative_to(root)
        module = relative.parts[0] if len(relative.parts) > 1 else "."
        counts[module] += 1
    return counts


def _extract_includes(content: str) -> list[str]:
    return re.findall(r'^\s*#\s*include\s*[<"]([^>"]+)[>"]', content, flags=re.MULTILINE)


def _extract_macros(content: str) -> list[str]:
    return re.findall(r"^\s*#\s*define\s+([A-Za-z_][A-Za-z0-9_]*)", content, flags=re.MULTILINE)


def _extract_functions(content: str) -> list[str]:
    cleaned = _remove_comments(content)
    pattern = re.compile(
        r"(?<![A-Za-z0-9_])"
        r"(?!if\b|for\b|while\b|switch\b|return\b|sizeof\b)"
        r"(?:static\s+|extern\s+|inline\s+|const\s+|unsigned\s+|signed\s+|long\s+|short\s+|struct\s+\w+\s+|enum\s+\w+\s+|[A-Za-z_][\w]*\s+|[\*\s])+"
        r"([A-Za-z_][A-Za-z0-9_]*)\s*\([^;{}]*\)\s*\{",
    )
    return [match.group(1) for match in pattern.finditer(cleaned)]


def _extract_structs(content: str) -> list[str]:
    names = re.findall(r"\b(?:struct|union|enum)\s+([A-Za-z_][A-Za-z0-9_]*)", content)
    names.extend(re.findall(r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)", content))
    return names


def _remove_comments(content: str) -> str:
    content = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)
    return re.sub(r"//.*", "", content)


def _format_counter(counter: Counter[str], limit: int) -> str:
    if not counter:
        return "(none detected)"
    return "\n".join(f"- {name}: {count}" for name, count in counter.most_common(limit))
