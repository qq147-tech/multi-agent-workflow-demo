from __future__ import annotations

import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from env_loader import load_env_file


ROOT = Path(__file__).parent
load_env_file(ROOT / ".env")

ALLOWED_SKILL_RESOURCE_SUFFIXES = {
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
MAX_SKILL_FILE_BYTES = 200_000
MAX_SKILL_PACKAGE_BYTES = 1_000_000

from workflow import Artifact, WorkflowEngine
from workflow_models import WorkflowStatus


HOST = "127.0.0.1"
PORT = 8787
ENGINE = WorkflowEngine()


def _print_llm_config() -> None:
    api_key = os.getenv("OPENAI_API_KEY", "")
    masked_key = f"{api_key[:8]}..." if api_key else "(not set)"
    print(
        "LLM config: "
        f"model={os.getenv('OPENAI_MODEL', '(not set)')} "
        f"base_url={os.getenv('OPENAI_BASE_URL', '(default)')} "
        f"api_key={masked_key}",
        flush=True,
    )


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, data: object, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path) -> None:
        body = path.read_bytes()
        content_type = "text/html; charset=utf-8" if path.suffix == ".html" else "text/plain"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_download(self, filename: str, body: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/index.html"}:
            self._send_file(ROOT / "static" / "index.html")
            return

        if parsed.path == "/api/config-options":
            prompts = sorted(path.name for path in (ROOT / "core" / "agents" / "prompts").glob("*.md"))
            skills = sorted(path.parent.name for path in (ROOT / "core" / "skills").glob("*/SKILL.md"))
            design_clarification_skills = ["design-principles"]
            if "brainstorming" in skills:
                design_clarification_skills.append("brainstorming")
            self._send_json(
                {
                    "prompts": prompts,
                    "skills": skills,
                    "llm_defaults": {
                        "base_url": os.getenv("OPENAI_BASE_URL", ""),
                        "model": os.getenv("OPENAI_MODEL", ""),
                        "timeout_seconds": os.getenv("OPENAI_TIMEOUT_SECONDS", ""),
                        "max_retries": os.getenv("OPENAI_MAX_RETRIES", ""),
                    },
                    "defaults": {
                        "DesignAgent": {
                            "prompt": "DesignAgent.md",
                            "skills": ["design-principles", "design-template"],
                            "clarification_skills": design_clarification_skills,
                            "design_skills": ["design-principles", "design-template"],
                        },
                        "DesignReviewAgent": {"prompt": "DesignReviewAgent.md", "skills": ["design-principles", "design-template"]},
                        "DevelopAgent": {"prompt": "DevelopAgent.md", "skills": ["code-style", "dt-guidelines"]},
                        "ReviewAgent": {"prompt": "ReviewAgent.md", "skills": ["code-review-rules", "code-style", "dt-guidelines"]},
                    },
                }
            )
            return

        parts = [unquote(part) for part in parsed.path.strip("/").split("/") if part]
        try:
            if len(parts) == 3 and parts[:2] == ["api", "workflows"]:
                self._send_json(ENGINE.to_dict(ENGINE.get(parts[2])))
                return

            if len(parts) == 5 and parts[:2] == ["api", "workflows"] and parts[3] == "download":
                filename, body, content_type = ENGINE.download_artifact(parts[2], Artifact(parts[4]))
                self._send_download(filename, body, content_type)
                return
        except Exception as exc:
            self._send_json({"error": str(exc)}, 404)
            return

        self._send_json({"error": "not found"}, 404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        parts = [unquote(part) for part in parsed.path.strip("/").split("/") if part]
        try:
            print(f"POST {parsed.path}", flush=True)
            if parts == ["api", "workflows"]:
                payload = self._read_json()
                state = ENGINE.create(
                    payload["repo_url"],
                    payload["requirement"],
                    payload.get("agent_config"),
                    payload.get("llm_config"),
                )
                self._send_json(ENGINE.to_dict(state))
                return

            if parts == ["api", "import-prompt"]:
                payload = self._read_json()
                filename = _safe_markdown_filename(payload.get("filename", ""))
                content = _validate_markdown_content(payload.get("content", ""))
                path = ROOT / "core" / "agents" / "prompts" / filename
                path.write_text(content, encoding="utf-8")
                self._send_json({"ok": True, "filename": filename})
                return

            if parts == ["api", "import-skill"]:
                payload = self._read_json()
                skill_name = _safe_skill_name(payload.get("skill_name", ""))
                skill_dir = ROOT / "core" / "skills" / skill_name
                skill_dir.mkdir(parents=True, exist_ok=True)
                if "files" in payload:
                    written = _write_skill_package(skill_dir, payload["files"])
                    self._send_json({"ok": True, "skill": skill_name, "files": written})
                else:
                    content = _validate_markdown_content(payload.get("content", ""))
                    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
                    self._send_json({"ok": True, "skill": skill_name, "files": ["SKILL.md"]})
                return

            if len(parts) == 4 and parts[:2] == ["api", "workflows"]:
                workflow_id = parts[2]
                action = parts[3]
                payload = self._read_json()
                handlers = {
                    "answer-clarification": lambda: ENGINE.answer_clarification(workflow_id, payload.get("answer", "")),
                    "approve-design": lambda: ENGINE.approve_design(workflow_id),
                    "reject-design": lambda: ENGINE.reject_design(workflow_id, payload.get("feedback", "")),
                    "submit-design-review-decisions": lambda: ENGINE.submit_design_review_decisions(
                        workflow_id,
                        payload.get("decisions", ""),
                        bool(payload.get("no_changes", False)),
                    ),
                    "approve-development-plan": lambda: ENGINE.approve_development_plan(workflow_id),
                    "reject-development-plan": lambda: ENGINE.reject_development_plan(workflow_id, payload.get("feedback", "")),
                    "approve-implementation": lambda: ENGINE.approve_implementation(workflow_id),
                    "reject-implementation": lambda: ENGINE.reject_implementation(workflow_id, payload.get("feedback", "")),
                    "submit-review-decisions": lambda: ENGINE.submit_review_decisions(
                        workflow_id,
                        payload.get("decisions", ""),
                        bool(payload.get("no_changes", False)),
                    ),
                    "rollback": lambda: ENGINE.rollback(
                        workflow_id,
                        WorkflowStatus(payload["target_status"]),
                        payload.get("reason", ""),
                    ),
                }
                if action in handlers:
                    self._send_json(ENGINE.to_dict(handlers[action]()))
                    return

            if len(parts) == 4 and parts[:2] == ["api", "workflows"] and parts[3] == "artifacts":
                payload = self._read_json()
                state = ENGINE.update_artifact(parts[2], Artifact(payload["artifact"]), payload["content"])
                self._send_json(ENGINE.to_dict(state))
                return

            self._send_json({"error": "not found"}, 404)
        except Exception as exc:
            self._send_json({"error": str(exc)}, 400)


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Multi-agent workflow demo running at http://{HOST}:{PORT}")
    _print_llm_config()
    server.serve_forever()


def _safe_markdown_filename(filename: str) -> str:
    name = os.path.basename(filename.strip())
    if not re.fullmatch(r"[A-Za-z0-9_.-]+\.md", name):
        raise ValueError("prompt file must be a .md file using only letters, numbers, dot, dash, or underscore")
    if name.upper() == "SKILL.MD":
        raise ValueError("prompt filename cannot be SKILL.md")
    return name


def _safe_skill_name(skill_name: str) -> str:
    name = skill_name.strip()
    if name.endswith(".md"):
        name = name[:-3]
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        raise ValueError("skill name must use only letters, numbers, dash, or underscore")
    return name


def _validate_markdown_content(content: str) -> str:
    if not isinstance(content, str) or not content.strip():
        raise ValueError("single Skill markdown content cannot be empty; use Skill folder import for a directory")
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_SKILL_FILE_BYTES:
        raise ValueError("markdown file is too large; max size is 200 KB")
    if "\x00" in content:
        raise ValueError("markdown content contains invalid NUL bytes")
    return content


def _safe_skill_relative_path(path: str) -> Path:
    if not isinstance(path, str) or not path.strip():
        raise ValueError("skill file path cannot be empty")
    normalized = path.replace("\\", "/").strip("/")
    parts = [part for part in normalized.split("/") if part and part != "."]
    if not parts or any(part == ".." for part in parts):
        raise ValueError(f"unsafe skill file path: {path}")

    # Browser folder uploads include the selected root folder name. Strip it so
    # "my-skill/SKILL.md" is stored as "SKILL.md" inside the target skill dir.
    if len(parts) > 1:
        parts = parts[1:]
    relative = Path(*parts)
    suffix = relative.suffix.lower()
    if relative.name.startswith("."):
        raise ValueError(f"hidden files are not allowed: {path}")
    if relative.name.lower() == "skill":
        return relative.with_name("SKILL.md")
    if suffix not in ALLOWED_SKILL_RESOURCE_SUFFIXES and relative.name != "requirements.txt":
        raise ValueError(f"unsupported skill package file type: {path}")
    return relative


def _write_skill_package(skill_dir: Path, files: object) -> list[str]:
    if not isinstance(files, list) or not files:
        raise ValueError("skill package files cannot be empty")

    total_bytes = 0
    normalized_files: list[tuple[Path, str]] = []
    for item in files:
        if not isinstance(item, dict):
            raise ValueError("invalid skill package file item")
        relative = _safe_skill_relative_path(str(item.get("path", "")))
        content = item.get("content", "")
        if not isinstance(content, str):
            raise ValueError(f"invalid file content: {relative.as_posix()}")
        if "\x00" in content:
            raise ValueError(f"file contains invalid NUL bytes: {relative.as_posix()}")
        encoded_size = len(content.encode("utf-8"))
        if encoded_size > MAX_SKILL_FILE_BYTES:
            raise ValueError(f"skill package file is too large: {relative.as_posix()}")
        total_bytes += encoded_size
        if total_bytes > MAX_SKILL_PACKAGE_BYTES:
            raise ValueError("skill package is too large; max size is 1 MB")
        normalized_files.append((relative, content))

    if not any(relative.as_posix().lower() == "skill.md" for relative, _ in normalized_files):
        raise ValueError("skill package must contain SKILL.md or SKILL at the selected folder root")

    for relative, content in normalized_files:
        target = skill_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    return [relative.as_posix() for relative, _ in normalized_files]


if __name__ == "__main__":
    main()
